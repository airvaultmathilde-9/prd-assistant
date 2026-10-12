"""Tests des outils de l'agent (phase 3), sans réseau ni LLM.

On appelle directement les fonctions des outils, comme le ferait Claude,
avec un faux TMDB et un faux Pinecone.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import build_options  # noqa: E402
from agent_tools import SessionRegistry, allowed_tool_names, build_tools  # noqa: E402
from config import Settings  # noqa: E402
from tmdb_client import TMDBError  # noqa: E402


class FakeTMDB:
    def __init__(self):
        self.calls = []

    def genres(self):
        return {35: "Comédie", 18: "Drame", 878: "Science-Fiction"}

    def discover_movies(self, **kwargs):
        self.calls.append(kwargs)
        return [{"tmdb_id": 597298, "title": "Mandibules"}, {"tmdb_id": 1, "title": "Autre"}]

    def search_movies(self, query, year=None):
        raise TMDBError("clé TMDB refusée (401)")

    def get_watch_providers(self, tmdb_id):
        return {"tmdb_id": tmdb_id, "title": "Mandibules",
                "options": [{"platform": "Netflix", "access": "abonnement", "link": "https://x"}]}


class FakeRatings:
    def already_seen(self, ids):
        return {i: (4.0 if i == 597298 else None) for i in ids}

    def search(self, query, top_k=8, min_note=None, max_note=None):
        raise RuntimeError("connexion impossible à https://secret-host")


def tools_by_name(tmdb=None, ratings=None, registry=None):
    tools = build_tools(tmdb or FakeTMDB(), ratings or FakeRatings(), registry or SessionRegistry())
    return {t.name: t for t in tools}


def call(tool, args):
    result = asyncio.run(tool.handler(args))
    text = result["content"][0]["text"]
    return result, (json.loads(text) if not result.get("is_error") else text)


def test_discover_translates_french_genre_names_and_records_movies():
    tmdb, registry = FakeTMDB(), SessionRegistry()
    tools = tools_by_name(tmdb, registry=registry)
    _, data = call(tools["discover_movies"], {"genres": ["comédie"], "on_my_subscriptions": True})
    assert tmdb.calls[0]["genre_ids"] == [35] and tmdb.calls[0]["on_my_subscriptions"] is True
    assert registry.movies == {597298: "Mandibules", 1: "Autre"}  # pour la règle « aucun film inventé »
    assert len(data) == 2


def test_unknown_genre_is_a_readable_error_for_the_agent():
    result, text = call(tools_by_name()["discover_movies"], {"genres": ["Polar nordique"]})
    assert result["is_error"] is True and "Polar nordique" in text


def test_tmdb_error_is_returned_not_raised():
    result, text = call(tools_by_name()["search_movie"], {"query": "x"})
    assert result["is_error"] is True and "clé TMDB refusée" in text


def test_unexpected_error_does_not_leak_details():
    result, text = call(tools_by_name()["search_my_ratings"], {"query": "x"})
    assert result["is_error"] is True
    assert "secret-host" not in text and "RuntimeError" in text


def test_check_already_seen_is_explicit():
    _, data = call(tools_by_name()["check_already_seen"], {"tmdb_ids": [597298, 42]})
    assert data == {"597298": {"deja_vu": True, "sa_note": 4.0}, "42": {"deja_vu": False}}


def test_agent_only_gets_our_tools_and_has_limits():
    settings = Settings("sk-ant-x", "pcsk-x", "tmdb-x", "claude-sonnet-5-5", "mes-films")
    options = build_options(settings, SessionRegistry())
    assert options.tools == []  # aucun outil intégré (terminal, fichiers, web)
    assert options.allowed_tools == allowed_tool_names(build_tools(FakeTMDB(), FakeRatings(), SessionRegistry()))
    assert all(name.startswith("mcp__films__") for name in options.allowed_tools)
    assert options.max_turns == 25 and options.max_budget_usd == 1.0
    assert options.model == "claude-sonnet-5-5" and options.setting_sources == []
    assert "Aucun film inventé" in options.system_prompt
