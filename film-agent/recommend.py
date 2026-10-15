"""Le moteur de l'interface : une demande -> une question OU 3 films vérifiés.

Partage des rôles, pour la fiabilité :
- Claude CHOISIT les films (par tmdb_id) et écrit « pourquoi » et « l'ambiance » ;
- les FAITS affichés (titre, affiche, durée, réalisation, lien) sont relus dans TMDB
  par notre code, jamais recopiés depuis le texte du modèle ;
- un film absent des résultats TMDB de la session est écarté (aucun film inventé).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage, query

from agent import build_options
from agent_tools import SessionRegistry
from config import Settings
from costs import CostLog, DailyBudgetExceeded
from memory import Memory
from tracing import Tracer, get_client
from tmdb_client import TMDBClient, TMDBError

ROLES = {
    "choix_sur": "🎯 Le choix sûr",
    "decouverte": "🧭 La découverte",
    "pari": "🎲 Le pari",
}

# Forme imposée à la réponse finale de l'agent (« sortie structurée »).
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["question", "recommendations"]},
        "message": {"type": "string", "description": "La question à poser, ou une phrase d'introduction."},
        "films": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "enum": list(ROLES)},
                    "tmdb_id": {"type": "integer"},
                    "why": {"type": "string", "description": "Pourquoi ce film : références à SES films notés. Aucun lien, aucune plateforme."},
                    "vibe": {"type": "string", "description": "L'ambiance, sans aucun spoiler. Aucun lien, aucune plateforme."},
                },
                "required": ["role", "tmdb_id", "why", "vibe"],
            },
        },
    },
    "required": ["kind", "message", "films"],
}

UI_INSTRUCTIONS = """

# Réponse dans l'interface web
Ta réponse finale est structurée : kind = "question" (avec la question dans message et films vide)
ou "recommendations" (films = 3 films avec role choix_sur, decouverte, pari). Pas de phrase
d'introduction : avec 3 films, message est vide. Avec moins de 3 films, message explique en UNE
phrase courte pourquoi (ex. « Un seul autre film de Dupieux est disponible chez toi. »). Dans why et vibe : AUCUN lien, AUCUNE URL, AUCUNE mention de plateforme ou d'abonnement, pas
de titre en en-tête. Ici, la règle « toujours un lien pour regarder » est appliquée par l'interface
elle-même : elle affiche le titre, l'affiche, la durée, la plateforme et un bouton pour regarder."""

LANGUAGES = {"fr": "Français", "en": "Anglais", "es": "Espagnol", "it": "Italien", "de": "Allemand",
             "ko": "Coréen", "ja": "Japonais", "zh": "Chinois", "pt": "Portugais", "da": "Danois",
             "sv": "Suédois", "no": "Norvégien", "fa": "Persan", "hi": "Hindi", "ru": "Russe"}


def format_runtime(minutes: int | None) -> str:
    """116 -> « 1 h 56 » : plus facile à lire qu'un nombre de minutes."""
    if not minutes:
        return ""
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h {mins:02d}" if mins else f"{hours} h"


@dataclass
class Film:
    role: str
    tmdb_id: int
    why: str
    vibe: str
    details: dict = field(default_factory=dict)  # faits TMDB
    watch: dict = field(default_factory=dict)    # où regarder (TMDB/JustWatch)
    trailer: dict | None = None                  # bande-annonce YouTube (TMDB)

    @property
    def role_label(self) -> str:
        return ROLES.get(self.role, self.role)

    @property
    def rating_label(self) -> str:
        """« ⭐ 7,9/10 · 11 000 votes » : la note du PUBLIC sur TMDB (pas la presse)."""
        votes = self.details.get("vote_count") or 0
        if votes < 20:  # trop peu de votes : la moyenne ne veut rien dire
            return ""
        average = f"{self.details.get('vote_average', 0):.1f}".replace(".", ",")
        thousands = f"{votes:,}".replace(",", " ")  # 11000 -> « 11 000 »
        return f"⭐ {average}/10 · {thousands} votes"

    @property
    def runtime_label(self) -> str:
        return format_runtime(self.details.get("runtime_min"))

    @property
    def language_label(self) -> str:
        code = self.details.get("original_language") or ""
        return LANGUAGES.get(code, code.upper())


@dataclass
class Answer:
    kind: str                      # "question", "recommendations" ou "error"
    message: str
    films: list[Film]
    session_id: str | None
    rejected: list[int] = field(default_factory=list)  # tmdb_id inventés ou non vérifiés
    cost_usd: float | None = None
    turns: int = 0
    trace_id: str | None = None  # la trace Langfuse de cette recherche (pour y rattacher mes avis)


_SENTENCES = re.compile(r"(?<=[.!?…])\s+")
_URL = re.compile(r"https?://\S+")


def strip_links(text: str) -> str:
    """Filet de sécurité : retire les phrases qui contiennent un lien.

    L'interface affiche déjà un bouton « Regarder sur… » ; un lien dans le texte ferait doublon.
    La consigne le demande à l'agent, mais un LLM ne la suit pas à 100 % : le code garantit.
    """
    kept = [s for s in _SENTENCES.split(text.strip())
            if not _URL.search(s) and not s.lower().startswith("lien")]
    return _URL.sub("", " ".join(kept)).strip()


def verify_and_enrich(raw_films: list[dict], registry: SessionRegistry,
                      tmdb: TMDBClient) -> tuple[list[Film], list[int]]:
    """Ne garde que les films vus dans TMDB pendant la session, et relit leurs faits dans TMDB."""
    films, rejected = [], []
    for raw in raw_films:
        if any(f.tmdb_id == raw["tmdb_id"] for f in films):
            continue  # le même film proposé deux fois : on ne le garde qu'une fois
        if raw["tmdb_id"] not in registry.movies:
            rejected.append(raw["tmdb_id"])
            continue
        film = Film(raw["role"], raw["tmdb_id"], strip_links(raw["why"]), strip_links(raw["vibe"]))
        try:
            film.details = tmdb.get_movie_details(film.tmdb_id)
            film.watch = tmdb.get_watch_providers(film.tmdb_id)
        except TMDBError:
            rejected.append(film.tmdb_id)
            continue
        try:
            film.trailer = tmdb.get_trailer(film.tmdb_id)
        except TMDBError:
            film.trailer = None  # pas de bande-annonce : le film reste proposé
        films.append(film)
    return films, rejected


def _where(film: Film) -> str:
    options = film.watch.get("options") or []
    return f"{options[0]['platform']} ({options[0]['access']})" if options else "pas disponible chez elle"


async def recommend(prompt: str, settings: Settings, registry: SessionRegistry,
                    session_id: str | None = None,
                    on_tool: Callable[[str, dict], None] | None = None,
                    memory: Memory | None = None, conversation_id: str | None = None,
                    tags: list[str] | None = None) -> Answer:
    """Lance l'agent sur une demande. session_id permet de continuer la conversation
    (par exemple pour répondre à sa question de clarification).

    conversation_id regroupe dans Langfuse les recherches d'une même conversation (« session ») ;
    tags les étiquette (« app » par défaut, « eval » pour l'évaluation)."""
    costs = CostLog()
    try:
        costs.check(settings.daily_budget_usd)  # garde-fou : on ne dépense plus rien au-delà du budget du jour
    except DailyBudgetExceeded as exc:
        return Answer("error", f"💶 {exc}", [], session_id)

    tracer = Tracer(get_client())
    with tracer.recherche(prompt, settings.claude_model, conversation_id, tags):
        answer = await _run_agent(prompt, settings, registry, session_id, on_tool, memory, costs, tracer)
        tracer.finish(
            # Tout ce que je vois sur les cartes : un juge (Langfuse ou scripts/eval.py) peut tout noter.
            output={"type": answer.kind, "message": answer.message,
                    "films": [{"role": f.role_label, "titre": f.details.get("title"), "annee": f.details.get("year"),
                               "duree": f.runtime_label, "ou_voir": _where(f),
                               "pourquoi": f.why, "ambiance": f.vibe} for f in answer.films]},
            metadata={"tours": answer.turns, "cout_usd": answer.cost_usd},
            # Contrôles automatiques, visibles et filtrables dans Langfuse.
            scores={"films_proposes": len(answer.films), "films_ecartes": len(answer.rejected),
                    "tours": answer.turns, "cout_usd": answer.cost_usd or 0.0,
                    "question_posee": float(answer.kind == "question"),
                    "echec": float(answer.kind == "error")},
            error=answer.message if answer.kind == "error" else None)
    answer.trace_id = tracer.trace_id
    return answer


async def _run_agent(prompt, settings, registry, session_id, on_tool, memory, costs, tracer) -> Answer:
    options = build_options(settings, registry, memory)
    options.system_prompt += UI_INSTRUCTIONS
    options.output_format = {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    options.resume = session_id

    result: ResultMessage | None = None
    tracer.turn_start()
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            tracer.assistant_message(message)
            for block in message.content:
                # StructuredOutput = la réponse finale elle-même, pas un outil.
                if isinstance(block, ToolUseBlock) and block.name != "StructuredOutput":
                    name = block.name.rsplit("__", 1)[-1]
                    tracer.tool_start(block.id, name, block.input)
                    if on_tool:
                        on_tool(name, block.input)
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    tracer.tool_end(block.tool_use_id, block.content, bool(block.is_error))
        elif isinstance(message, ResultMessage):
            result = message
            costs.add(message.total_cost_usd)  # même une recherche interrompue a coûté
            tracer.llm_usage(settings.claude_model, message.usage, message.total_cost_usd)

    if result is None or result.is_error or not isinstance(result.structured_output, dict):
        reason = {"error_max_turns": "l'agent a atteint sa limite de tours (essaie une demande plus précise)",
                  "error_max_budget_usd": "l'agent a atteint le budget de la recherche"}.get(
                      result.subtype if result else "", "l'agent n'a pas pu terminer")
        return Answer("error", f"Désolée, {reason}. Reformule ta demande ?", [],
                      result.session_id if result else session_id,
                      cost_usd=result.total_cost_usd if result else None, turns=result.num_turns if result else 0)

    output = result.structured_output
    films, rejected = [], []
    if output.get("kind") == "recommendations":
        films, rejected = verify_and_enrich(output.get("films", []), registry,
                                            TMDBClient(settings.tmdb_api_key))
        tracer.step("verification", input=output.get("films", []),
                    output={"gardes": [f"{f.details.get('title')} ({f.tmdb_id})" for f in films],
                            "ecartes_non_vus_dans_tmdb": rejected},
                    level="WARNING" if rejected else "DEFAULT")
    return Answer(output.get("kind", "recommendations"), output.get("message", ""), films,
                  result.session_id, rejected, result.total_cost_usd, result.num_turns)
