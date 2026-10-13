"""Langfuse : enregistrer chaque recherche (trace) et la noter (scores), pour l'évaluer.

- Une TRACE par recherche : ma demande, chaque outil appelé par l'agent (paramètres et
  résultat), les films proposés, le coût, les tours.
- Des SCORES : contrôles automatiques à la fin de la recherche, puis mes avis sur les
  cartes (vu et aimé, pas envie…) rattachés à la recherche qui les a proposés.

Activé seulement si LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY sont dans .env
(LANGFUSE_HOST : https://cloud.langfuse.com pour l'Europe). Sinon, ou si Langfuse ne
répond pas, tout fonctionne comme avant : le suivi ne doit jamais casser l'agent.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)
MAX_CHARS = 2000  # on tronque les gros résultats d'outils : lisible et léger


def _short(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"


class Tracer:
    def __init__(self, client=None):
        self.client = client
        self.root = None
        self.trace_id: str | None = None
        self._tools: dict[str, Any] = {}  # tool_use_id -> observation en cours

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def recherche(self, prompt: str, model: str) -> Iterator["Tracer"]:
        """Ouvre la trace d'une recherche (ne fait rien si Langfuse est désactivé)."""
        if not self.enabled:
            yield self
            return
        try:
            manager = self.client.start_as_current_observation(
                name="recommandation", as_type="agent", input={"demande": prompt}, metadata={"modele": model})
            self.root = manager.__enter__()
            self.trace_id = self.client.get_current_trace_id()
        except Exception:  # Langfuse injoignable : on continue sans suivi
            logger.warning("Langfuse indisponible : recherche non suivie")
            self.client = None
            yield self
            return
        try:
            yield self
        finally:
            self._safe(manager.__exit__, None, None, None)
            self._safe(self.client.flush)

    def tool_start(self, tool_use_id: str, name: str, params: dict) -> None:
        if self.root is not None:
            self._tools[tool_use_id] = self._safe(
                self.root.start_observation, name=name, as_type="tool", input=params)

    def tool_end(self, tool_use_id: str, output: Any, is_error: bool = False) -> None:
        span = self._tools.pop(tool_use_id, None)
        if span is not None:
            self._safe(span.update, output=_short(output), level="ERROR" if is_error else "DEFAULT")
            self._safe(span.end)

    def finish(self, output: Any, metadata: dict, scores: dict[str, float]) -> None:
        """Résultat final de la recherche, et ses contrôles automatiques."""
        if self.root is None:
            return
        self._safe(self.root.update, output=output, metadata=metadata)
        for name, value in scores.items():
            self._safe(self.client.create_score, name=name, value=value, trace_id=self.trace_id)

    @staticmethod
    def _safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.warning("Langfuse : envoi impossible (%s)", getattr(fn, "__name__", "?"))
            return None


_client = None


def get_client():
    """Le client Langfuse (un seul pour toute l'app), ou None si non configuré."""
    global _client
    if _client is None and os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse import Langfuse
            _client = Langfuse()  # lit LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
        except Exception:
            logger.warning("Langfuse non initialisé : suivi désactivé")
    return _client


def score_feedback(trace_id: str | None, film_title: str, status: str, note: float | None = None) -> None:
    """Mon avis sur une carte devient un score de la recherche qui l'a proposée."""
    client = get_client()
    if not client or not trace_id:
        return
    try:
        client.create_score(name="avis", value=status, data_type="CATEGORICAL",
                            trace_id=trace_id, comment=film_title)
        if note is not None:
            client.create_score(name="note_donnee", value=note, trace_id=trace_id, comment=film_title)
        client.flush()
    except Exception:
        logger.warning("Langfuse : avis non envoyé")
