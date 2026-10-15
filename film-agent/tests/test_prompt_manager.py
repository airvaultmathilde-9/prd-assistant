"""Le prompt système vient de Langfuse, avec le fichier local en secours (aucun réseau ici)."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import prompt_manager  # noqa: E402

LOCAL = prompt_manager.LOCAL_FILE.read_text(encoding="utf-8")


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def get_prompt(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.error:
            raise self.error
        return self.result


def test_without_langfuse_the_local_file_is_used(monkeypatch):
    monkeypatch.setattr(prompt_manager, "get_client", lambda: None)
    loaded = prompt_manager.load_system_prompt()
    assert loaded.text == LOCAL and loaded.source == "fichier local" and loaded.client is None


def test_production_version_from_langfuse(monkeypatch):
    remote = SimpleNamespace(prompt="Tu es un agent cinéphile.", version=4, is_fallback=False)
    client = FakeClient(remote)
    monkeypatch.setattr(prompt_manager, "get_client", lambda: client)
    monkeypatch.delenv("LANGFUSE_PROMPT_LABEL", raising=False)
    loaded = prompt_manager.load_system_prompt()
    assert loaded.text == "Tu es un agent cinéphile." and loaded.source == "langfuse v4 (production)"
    name, kwargs = client.calls[0]
    assert name == "film-agent-instructions" and kwargs["label"] == "production" and kwargs["fallback"] == LOCAL


def test_another_label_can_be_tested(monkeypatch):
    client = FakeClient(SimpleNamespace(prompt="x", version=5, is_fallback=False))
    monkeypatch.setattr(prompt_manager, "get_client", lambda: client)
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "staging")
    assert prompt_manager.load_system_prompt().source == "langfuse v5 (staging)"


def test_langfuse_down_or_prompt_missing_falls_back_to_the_file(monkeypatch):
    monkeypatch.setattr(prompt_manager, "get_client", lambda: FakeClient(error=RuntimeError("404")))
    assert prompt_manager.load_system_prompt().text == LOCAL
    fallback = SimpleNamespace(prompt=LOCAL, version=0, is_fallback=True)
    monkeypatch.setattr(prompt_manager, "get_client", lambda: FakeClient(fallback))
    loaded = prompt_manager.load_system_prompt()
    assert loaded.source == "fichier local" and loaded.client is None


def test_agent_uses_the_given_instructions():
    from agent import build_options
    from agent_tools import SessionRegistry
    from config import Settings
    options = build_options(Settings("a", "p", "t", "m", "i"), SessionRegistry(), system_prompt="CONSIGNES TEST")
    assert options.system_prompt.startswith("CONSIGNES TEST")
