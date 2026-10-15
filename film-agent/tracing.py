"""Langfuse : enregistrer chaque recherche (trace) et la noter (scores), pour l'évaluer.

Ce que contient une trace « recommandation » :
- la demande, et les attributs de la trace : conversation (session), utilisatrice, version du prompt,
  étiquettes (« app » ou « eval ») pour filtrer ;
- chaque TOUR de Claude, en « generation » : modèle, durée, ce qu'il a écrit ou décidé d'appeler,
  et ses tokens (dont le cache) ;
- chaque OUTIL appelé (paramètres, résultat, erreur éventuelle) ;
- la VÉRIFICATION finale (films gardés, films écartés car non vus dans TMDB) ;
- le coût total exact (donné par le SDK) et des SCORES automatiques ; puis mes avis sur les cartes.

Activé seulement si LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY sont dans .env
(LANGFUSE_HOST : https://cloud.langfuse.com pour l'Europe). Sinon, ou si Langfuse ne
répond pas, tout fonctionne comme avant : le suivi ne doit jamais casser l'agent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator

from config import PROJECT_DIR

logger = logging.getLogger(__name__)
MAX_CHARS = 2000  # on tronque les gros résultats d'outils : lisible et léger
USER_ID = "mathilde"


def _short(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…"


def prompt_version() -> str:
    """Empreinte des instructions de l'agent (prompt + skill) : change dès qu'on les modifie.

    Dans Langfuse, on peut ainsi comparer les recherches faites avant et après une modification.
    """
    files = [PROJECT_DIR / "prompts" / "system_prompt.md",
             *sorted((PROJECT_DIR / ".claude" / "skills").glob("*/SKILL.md"))]
    digest = hashlib.sha256(b"".join(f.read_bytes() for f in files if f.exists()))
    return digest.hexdigest()[:8]


def _usage(usage: dict | None) -> dict[str, int]:
    usage = usage or {}
    tokens = {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0),
              "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
              "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0)}
    return {k: v for k, v in tokens.items() if v}


def _blocks_summary(blocks: list) -> list:
    """Ce que Claude a produit pendant un tour : du texte, ou des appels d'outils."""
    out = []
    for block in blocks:
        name = getattr(block, "name", None)
        if name:
            out.append({"appel": name.rsplit("__", 1)[-1], "parametres": getattr(block, "input", None)})
        elif getattr(block, "text", None):
            out.append({"texte": block.text})
        elif getattr(block, "thinking", None):
            out.append({"reflexion": block.thinking})
    return out


class Tracer:
    def __init__(self, client=None):
        self.client = client
        self.root = None
        self.trace_id: str | None = None
        self._tools: dict[str, Any] = {}  # tool_use_id -> observation en cours
        self._turn = None                 # le tour de Claude en cours (generation)
        self._turn_id: str | None = None  # identifiant du message Claude de ce tour
        self._turn_blocks: list = []
        self._turns = 0
        self._last_id: str | None = None  # dernier message Claude déjà clos (pour ne pas le compter deux fois)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @contextmanager
    def trace(self, name: str, input: Any, *, as_type: str = "agent", model: str | None = None,
              session_id: str | None = None, tags: list[str] | None = None,
              instructions=None) -> Iterator["Tracer"]:
        """Ouvre une trace (ne fait rien si Langfuse est désactivé).

        instructions : le prompt système utilisé (prompt_manager.SystemPrompt). S'il vient de Langfuse,
        la trace est reliée à sa version (onglet Prompts → métriques par version)."""
        if not self.enabled:
            yield self
            return
        stack = ExitStack()
        try:
            from langfuse import propagate_attributes
            linked = getattr(instructions, "client", None)  # prompt Langfuse (None si fichier local)
            version = f"prompt-v{linked.version}" if linked is not None else prompt_version()
            extra = {"prompt": linked} if linked is not None else {}
            stack.enter_context(propagate_attributes(
                user_id=USER_ID, session_id=session_id, tags=tags, version=version,
                trace_name=name, metadata={"modele": model} if model else None, **extra))
            metadata = {"modele": model}
            if instructions is not None:
                metadata["instructions"] = instructions.source
            self.root = stack.enter_context(self.client.start_as_current_observation(
                name=name, as_type=as_type, input=input, metadata=metadata))
            self.trace_id = self.client.get_current_trace_id()
        except Exception:  # Langfuse injoignable : on continue sans suivi
            logger.warning("Langfuse indisponible : recherche non suivie")
            self._safe(stack.close)
            self.client, self.root = None, None
            yield self
            return
        try:
            yield self
        finally:
            self._end_turn()
            self._safe(stack.close)
            self._safe(self.client.flush)

    def recherche(self, prompt: str, model: str, session_id: str | None = None,
                  tags: list[str] | None = None, instructions=None):
        return self.trace("recommandation", {"demande": prompt}, model=model,
                          session_id=session_id, tags=tags or ["app"], instructions=instructions)

    # ---------- Les tours de Claude ----------

    def turn_start(self) -> None:
        """Claude commence à réfléchir (début de la recherche, ou après les résultats d'outils)."""
        if self.root is None or self._turn is not None:
            return
        self._turns += 1
        self._turn = self._safe(self.root.start_observation, name=f"claude · tour {self._turns}",
                                as_type="generation")

    def assistant_message(self, message) -> None:
        """Un message de Claude : il clôt le tour en cours (texte écrit, outils demandés, tokens)."""
        if self.root is None:
            return
        message_id = getattr(message, "message_id", None)
        if message_id and message_id == self._last_id:
            return  # suite d'une réponse dont le tour est déjà clos (plusieurs outils demandés d'un coup)
        if self._turn is None:  # message hors d'un tour ouvert (ne devrait pas arriver)
            self.turn_start()
        if self._turn is None:  # Langfuse n'a pas pu créer le tour : on n'insiste pas
            return
        if message_id and message_id == self._turn_id:  # même réponse, découpée en plusieurs blocs
            self._turn_blocks += list(message.content)
        else:
            self._turn_id, self._turn_blocks = message_id, list(message.content)
        self._safe(self._turn.update, model=getattr(message, "model", None),
                   output=_blocks_summary(self._turn_blocks), usage_details=_usage(message.usage))

    def _end_turn(self) -> None:
        if self._turn is not None:
            self._safe(self._turn.end)
            self._last_id = self._turn_id or self._last_id
        self._turn, self._turn_id, self._turn_blocks = None, None, []

    # ---------- Les outils ----------

    def tool_start(self, tool_use_id: str, name: str, params: dict) -> None:
        if self.root is not None:
            self._end_turn()  # Claude a fini son tour : il attend le résultat des outils
            self._tools[tool_use_id] = self._safe(
                self.root.start_observation, name=name, as_type="tool", input=params)

    def tool_end(self, tool_use_id: str, output: Any, is_error: bool = False) -> None:
        span = self._tools.pop(tool_use_id, None)
        if span is not None:
            self._safe(span.update, output=_short(output), level="ERROR" if is_error else "DEFAULT")
            self._safe(span.end)
        if not self._tools:  # tous les résultats sont là : Claude reprend la main
            self.turn_start()

    # ---------- Fin de la recherche ----------

    def llm_usage(self, model: str, usage: dict | None, cost_usd: float | None) -> None:
        """Le coût total exact de la recherche (donné par le SDK), en une generation à part.

        Les tours ci-dessus portent les tokens ; le SDK ne donne le coût qu'au total.
        """
        self._end_turn()
        if self.root is None:
            return
        # Tokens déjà portés par les tours : ici seulement en information (sinon comptés deux fois).
        tokens = {"metadata": {"tokens_total": _usage(usage), "tours": self._turns}} if self._turns else \
            {"usage_details": _usage(usage)}
        generation = self._safe(
            self.root.start_observation, name="claude · coût total", as_type="generation", model=model,
            cost_details={"total": cost_usd} if cost_usd is not None else None, **tokens)
        if generation is not None:
            self._safe(generation.end)

    def step(self, name: str, input: Any, output: Any, level: str = "DEFAULT") -> None:
        """Une étape de notre code (pas de Claude), par ex. la vérification des films."""
        if self.root is None:
            return
        span = self._safe(self.root.start_observation, name=name, as_type="span", input=input)
        if span is not None:
            self._safe(span.update, output=output, level=level)
            self._safe(span.end)

    def finish(self, output: Any, metadata: dict, scores: dict[str, float],
               error: str | None = None) -> None:
        """Résultat final de la trace, et ses contrôles automatiques."""
        if self.root is None:
            return
        extra = {"level": "ERROR", "status_message": error} if error else {}
        self._safe(self.root.update, output=output, metadata=metadata, **extra)
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
MCP_SCOPE = "mcp-python-sdk"


def _keep_span(span) -> bool:
    """Ce que Langfuse reçoit : son filtre habituel, SAUF les spans de la bibliothèque MCP.

    Elle trace déjà chaque appel d'outil de son côté (« tools/call … ») : sans ce filtre,
    chaque outil apparaissait deux fois, et les compteurs étaient doublés.
    """
    from langfuse.span_filter import is_default_export_span
    scope = getattr(span, "instrumentation_scope", None)
    return is_default_export_span(span) and getattr(scope, "name", None) != MCP_SCOPE


def get_client():
    """Le client Langfuse (un seul pour toute l'app), ou None si non configuré."""
    global _client
    if _client is None and os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        try:
            from langfuse import Langfuse
            # lit LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
            _client = Langfuse(should_export_span=_keep_span)
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
