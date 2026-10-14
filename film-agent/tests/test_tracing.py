"""Tests du suivi Langfuse (faux client : rien n'est envoyé)."""

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import recommend  # noqa: E402
import tracing  # noqa: E402
from agent_tools import SessionRegistry  # noqa: E402
from config import Settings  # noqa: E402


class FakeSpan:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def start_observation(self, **kwargs):
        if kwargs.get("as_type") == "generation":
            self.log.append(("generation", kwargs["model"], kwargs["usage_details"], kwargs["cost_details"]))
        else:
            self.log.append(("tool", kwargs["name"], kwargs["input"]))
        return FakeSpan(self.log, kwargs["name"])

    def update(self, **kwargs):
        self.log.append(("update", self.name, kwargs))

    def end(self):
        self.log.append(("end", self.name))


class FakeLangfuse:
    def __init__(self):
        self.log, self.scores = [], {}

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        self.log.append(("trace", kwargs["name"], kwargs["input"]))
        yield FakeSpan(self.log, kwargs["name"])

    def get_current_trace_id(self):
        return "trace-123"

    def create_score(self, **kwargs):
        self.scores[kwargs["name"]] = kwargs["value"]

    def flush(self):
        pass


def test_disabled_tracer_does_nothing():
    tracer = tracing.Tracer(None)
    with tracer.recherche("x", "m"):
        tracer.tool_start("1", "search", {})
        tracer.finish({}, {}, {"a": 1})
    assert tracer.trace_id is None


def test_a_search_becomes_a_trace_with_tools_and_scores(monkeypatch, tmp_path):
    import costs
    monkeypatch.setattr(costs, "COSTS_FILE", tmp_path / "couts.json")
    fake = FakeLangfuse()
    monkeypatch.setattr(recommend, "get_client", lambda: fake)
    from claude_agent_sdk import AssistantMessage, ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage

    async def fake_query(prompt, options):
        yield AssistantMessage(content=[ToolUseBlock(id="t1", name="mcp__films__discover_movies",
                                                     input={"genres": ["Comédie"]})], model="m")
        yield UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="[…]", is_error=False)])
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=4,
                            session_id="s", total_cost_usd=0.08,
                            usage={"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 9000},
                            structured_output={
                                "kind": "question", "message": "Plutôt léger ?", "films": []})

    monkeypatch.setattr(recommend, "query", fake_query)
    settings = Settings("k", "k", "k", "claude-sonnet-5-5", "mes-films")
    answer = asyncio.run(recommend.recommend("Un film", settings, SessionRegistry()))
    assert answer.trace_id == "trace-123"
    assert ("trace", "recommandation", {"demande": "Un film"}) in fake.log
    assert ("tool", "discover_movies", {"genres": ["Comédie"]}) in fake.log and ("end", "discover_movies") in fake.log
    # Les appels à Claude : une « generation » avec modèle, tokens et coût exact.
    assert ("generation", "claude-sonnet-5-5", {"input": 1200, "output": 300, "cache_read_input_tokens": 9000},
            {"total": 0.08}) in fake.log
    assert fake.scores == {"films_proposes": 0, "films_ecartes": 0, "tours": 4, "cout_usd": 0.08,
                           "question_posee": 1.0, "echec": 0.0}


def test_feedback_becomes_a_score(monkeypatch):
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "get_client", lambda: fake)
    tracing.score_feedback("trace-123", "Le Daim", "vu_pas_aime", 2.0)
    assert fake.scores == {"avis": "vu_pas_aime", "note_donnee": 2.0}
    tracing.score_feedback(None, "Le Daim", "plus_tard")  # pas de trace : rien n'est envoyé
    assert fake.scores["avis"] == "vu_pas_aime"


def test_real_sdk_never_breaks_the_app_when_langfuse_is_unreachable(monkeypatch):
    pytest.importorskip("langfuse")
    from langfuse import Langfuse
    client = Langfuse(public_key="pk-lf-x", secret_key="sk-lf-x", host="http://127.0.0.1:9", timeout=1)
    tracer = tracing.Tracer(client)
    with tracer.recherche("Un film", "m"):
        tracer.tool_start("1", "search_movie", {"query": "x"})
        tracer.tool_end("1", {"r": 1})
        tracer.finish({"type": "x"}, {}, {"tours": 3})
    assert tracer.trace_id  # la trace a un identifiant même si l'envoi échoue


def test_mcp_library_spans_are_not_sent_twice():
    """La bibliothèque MCP trace aussi chaque outil : on ne garde que notre version."""
    def span(scope, attributes):
        return SimpleNamespace(instrumentation_scope=SimpleNamespace(name=scope), attributes=attributes,
                               name="tools/call get_watch_options", parent=None)
    genai = {"gen_ai.operation.name": "execute_tool"}
    assert not tracing._keep_span(span("mcp-python-sdk", genai))
    assert tracing._keep_span(span("langfuse-sdk", {}))
