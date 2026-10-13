"""Tests des garde-fous de coût."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import costs  # noqa: E402
from agent_tools import SessionRegistry  # noqa: E402
from config import Settings  # noqa: E402
from costs import CostLog, DailyBudgetExceeded  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_costs(tmp_path, monkeypatch):
    monkeypatch.setattr(costs, "COSTS_FILE", tmp_path / "couts.json")


def test_costs_add_up_for_the_day_and_survive_a_restart():
    log = CostLog()
    log.add(0.11)
    log.add(0.09)
    log.add(None)  # coût inconnu : ignoré
    assert CostLog().today() == pytest.approx(0.20)


def test_daily_budget_blocks_new_searches():
    CostLog().add(1.02)
    with pytest.raises(DailyBudgetExceeded, match="1.02 \\$ sur 1.00 \\$"):
        CostLog().check(1.00)
    CostLog().check(2.00)  # avec un budget plus haut, ça passe


def test_recommend_refuses_without_calling_the_agent_when_budget_is_spent(monkeypatch):
    import recommend
    monkeypatch.setattr(recommend, "query", lambda **_: pytest.fail("l'agent ne doit pas être appelé"))
    CostLog().add(1.5)
    settings = Settings("k", "k", "k", "claude-sonnet-5-5", "mes-films")
    answer = asyncio.run(recommend.recommend("Un film", settings, SessionRegistry()))
    assert answer.kind == "error" and "Budget du jour atteint" in answer.message


def test_limits_come_from_env(monkeypatch):
    import config
    for key, value in {"ANTHROPIC_API_KEY": "k", "PINECONE_API_KEY": "k", "TMDB_API_KEY": "k",
                       "CLAUDE_MODEL": "m", "AGENT_MAX_TURNS": "8", "AGENT_MAX_BUDGET_USD": "0,15",
                       "AGENT_DAILY_BUDGET_USD": "2"}.items():
        monkeypatch.setenv(key, value)
    s = config.get_settings()
    assert (s.max_turns, s.max_budget_usd, s.daily_budget_usd) == (8, 0.15, 2.0)
    monkeypatch.setenv("AGENT_MAX_TURNS", "beaucoup")
    with pytest.raises(config.ConfigError, match="AGENT_MAX_TURNS"):
        config.get_settings()
