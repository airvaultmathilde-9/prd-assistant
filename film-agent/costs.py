"""Compteur des dépenses Anthropic par jour (data/memory/couts.json, sur ma machine).

Chaque recherche renvoie son coût exact (ResultMessage.total_cost_usd) : on l'additionne
au total du jour. Avant chaque recherche, on vérifie qu'il reste du budget.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config import PROJECT_DIR

COSTS_FILE = PROJECT_DIR / "data" / "memory" / "couts.json"


class DailyBudgetExceeded(Exception):
    """Le budget du jour est atteint : on ne lance pas de nouvelle recherche."""


class CostLog:
    def __init__(self, path: Path | None = None):
        self.path = path or COSTS_FILE  # lu à l'appel : les tests peuvent le rediriger
        self.by_day: dict[str, float] = (
            json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {})

    def today(self) -> float:
        return self.by_day.get(date.today().isoformat(), 0.0)

    def add(self, cost_usd: float | None) -> None:
        if not cost_usd:
            return
        day = date.today().isoformat()
        self.by_day[day] = round(self.by_day.get(day, 0.0) + cost_usd, 4)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.by_day, indent=2), encoding="utf-8")

    def check(self, daily_budget_usd: float) -> None:
        if self.today() >= daily_budget_usd:
            raise DailyBudgetExceeded(
                f"Budget du jour atteint ({self.today():.2f} $ sur {daily_budget_usd:.2f} $). "
                "L'agent reprendra demain, ou augmente AGENT_DAILY_BUDGET_USD dans .env.")
