"""Phase 3 : les outils que Claude peut appeler, au format du Claude Agent SDK.

Chaque outil = un nom + une DESCRIPTION + un schéma d'entrée + une fonction.
La description est capitale : c'est tout ce que Claude sait de l'outil pour
décider s'il l'appelle, quand, et avec quoi. On l'écrit comme une notice
pour un collègue intelligent qui ne connaît pas le code.

Les fonctions TMDB et Pinecone (phases 1 et 2) sont synchrones : on les lance
dans un fil séparé (asyncio.to_thread) pour ne pas bloquer la boucle de l'agent.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from memory import STATUSES, Memory
from ratings_store import RatingsStore
from tmdb_client import TMDBClient, TMDBError

SERVER_NAME = "films"


@dataclass
class SessionRegistry:
    """Tous les films renvoyés par TMDB pendant la session : tmdb_id -> titre.

    Sert à la règle « aucun film inventé » : un film recommandé doit être ici.
    (La phase 5 s'en servira dans un garde-fou automatique.)
    """
    movies: dict[int, str] = field(default_factory=dict)

    def record(self, items: list[dict] | dict) -> None:
        for item in items if isinstance(items, list) else [items]:
            if item.get("tmdb_id"):
                self.movies[item["tmdb_id"]] = item.get("title") or ""


def _ok(data: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}


def _error(message: str) -> dict:
    # is_error : Claude comprend que l'appel a échoué et peut réagir (reformuler, réessayer…).
    return {"content": [{"type": "text", "text": f"Erreur : {message}"}], "is_error": True}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


INT_LIST = {"type": "array", "items": {"type": "integer"}}
STR_LIST = {"type": "array", "items": {"type": "string"}}


def build_tools(tmdb: TMDBClient, ratings: RatingsStore, registry: SessionRegistry,
                memory: Memory) -> list:
    """Construit les outils, branchés sur TMDB, Pinecone et la mémoire fournis."""

    async def run(fn, *args, record: bool = False, **kwargs) -> dict:
        """Exécute fn hors de la boucle de l'agent et formate la réponse pour Claude."""
        try:
            data = await asyncio.to_thread(fn, *args, **kwargs)
        except TMDBError as exc:
            return _error(str(exc))
        except Exception as exc:  # Pinecone, réseau… : message court, sans détail sensible
            return _error(f"{type(exc).__name__} pendant l'appel")
        if record:  # films venant de TMDB : on les note dans le registre de session
            registry.record(data)
        return _ok(data)

    # ---------- Mes goûts (Pinecone, phase 2) ----------

    @tool(
        "search_my_ratings",
        "Cherche dans les films que Mathilde a DÉJÀ VUS et notés (sur 5, avec ses commentaires). "
        "Recherche sémantique : décris une envie, une ambiance, un thème, une personne "
        "(« comédie absurde », « visuellement sublime », « trop long », « Adèle Exarchopoulos »). "
        "Filtre min_note=4 pour ce qu'elle a aimé, max_note=2 pour ce qu'elle n'a pas aimé. "
        "Chaque résultat a un score de pertinence : > 0.3 = vraie référence utilisable pour "
        "justifier une recommandation ; < 0.05 = sans rapport, à ignorer.",
        _schema({
            "query": {"type": "string", "description": "L'envie ou le thème, en français."},
            "min_note": {"type": "number", "description": "Note minimale (0 à 5)."},
            "max_note": {"type": "number", "description": "Note maximale (0 à 5)."},
            "top_k": {"type": "integer", "description": "Nombre de résultats (défaut 8)."},
        }, ["query"]),
    )
    async def search_my_ratings(args):
        return await run(ratings.search, args["query"], top_k=args.get("top_k", 8),
                         min_note=args.get("min_note"), max_note=args.get("max_note"))

    @tool(
        "check_already_seen",
        "Vérifie, pour des films (tmdb_id), si Mathilde les a déjà vus (ses notes) et ce que dit "
        "sa mémoire (vu_aime, pas_envie, plus_tard). À utiliser sur les candidats AVANT de les "
        "recommander : écarte les déjà vus et les « pas envie ».",
        _schema({"tmdb_ids": INT_LIST}, ["tmdb_ids"]),
    )
    async def check_already_seen(args):
        def check(ids):
            result = {}
            for i, note in ratings.already_seen(ids).items():
                status = memory.status_of(i)
                entry = {"deja_vu": note is not None or status == "vu_aime"}
                if note is not None:
                    entry["sa_note"] = note
                if status:
                    entry["memoire"] = status
                result[i] = entry
            return result
        return await run(check, args["tmdb_ids"])

    # ---------- La mémoire (phase 4) ----------

    @tool(
        "remember_preference",
        "Mémorise une préférence DURABLE de Mathilde, qu'elle t'a exprimée clairement "
        "(« je préfère la VO sous-titrée », « pas de films d'horreur », « jamais plus de 2h30 »). "
        "Pas pour une envie du moment (« ce soir je veux rire ») : celle-là ne vaut que pour la demande en cours. "
        "Formule-la en une phrase courte, à la 3e personne. Dis-lui ensuite que tu l'as retenue.",
        _schema({"texte": {"type": "string"}}, ["texte"]),
    )
    async def remember_preference(args):
        return await run(memory.add_preference, args["texte"])

    @tool(
        "forget_preference",
        "Supprime une préférence mémorisée (par son numéro [id] affiché dans la section Mémoire), "
        "si Mathilde dit qu'elle n'est plus vraie.",
        _schema({"id": {"type": "integer"}}, ["id"]),
    )
    async def forget_preference(args):
        return await run(lambda i: {"supprimee": memory.remove_preference(i)}, args["id"])

    @tool(
        "record_feedback",
        "Enregistre ce que Mathilde dit d'un film dans la conversation : vu_aime (elle l'a vu et aimé), "
        "pas_envie (ne plus le proposer), plus_tard (à garder de côté).",
        _schema({"tmdb_id": {"type": "integer"},
                 "statut": {"type": "string", "enum": list(STATUSES)}}, ["tmdb_id", "statut"]),
    )
    async def record_feedback(args):
        title = registry.movies.get(args["tmdb_id"]) or f"film {args['tmdb_id']}"
        return await run(lambda: memory.set_feedback(args["tmdb_id"], title, args["statut"])
                         or {"enregistre": True, "titre": title, "statut": args["statut"]})

    # ---------- Le catalogue (TMDB, phase 1) ----------

    @tool(
        "search_movie",
        "Cherche un film précis par son titre (français ou original) dans TMDB. "
        "Utile pour vérifier qu'un film existe et obtenir son tmdb_id.",
        _schema({"query": {"type": "string"}, "year": {"type": "integer"}}, ["query"]),
    )
    async def search_movie(args):
        return await run(tmdb.search_movies, args["query"], year=args.get("year"), record=True)

    @tool(
        "discover_movies",
        "Trouve des films par CRITÈRES dans TMDB : l'outil principal pour générer des idées. "
        "Tous les critères sont facultatifs et se combinent. genres : noms français "
        "(Comédie, Drame, Action, Aventure, Animation, Crime, Documentaire, Familial, Fantastique, "
        "Histoire, Horreur, Musique, Mystère, Romance, Science-Fiction, Thriller, Guerre, Western) ; "
        "plusieurs genres = le film doit les avoir TOUS. on_my_subscriptions=true : seulement les films "
        "inclus dans Netflix ou Canal+ en France. origin_country : code ISO (FR, AR, KR, JP…). "
        "original_language : code ISO 639-1 (fr, en, ko…). person_ids / keyword_ids : obtenus avec "
        "search_person / search_keyword. Si trop peu de résultats, retire des critères.",
        _schema({
            "genres": STR_LIST,
            "exclude_genres": STR_LIST,
            "year_from": {"type": "integer"},
            "year_to": {"type": "integer"},
            "min_vote_average": {"type": "number", "description": "Note TMDB minimale sur 10."},
            "min_vote_count": {"type": "integer", "description": "Défaut 100 : évite les films confidentiels mal notés."},
            "original_language": {"type": "string"},
            "origin_country": {"type": "string"},
            "person_ids": INT_LIST,
            "keyword_ids": INT_LIST,
            "max_runtime": {"type": "integer", "description": "Durée maximale en minutes."},
            "on_my_subscriptions": {"type": "boolean"},
            "sort_by": {"type": "string", "enum": ["popularity.desc", "vote_average.desc",
                                                    "primary_release_date.desc"]},
            "page": {"type": "integer", "description": "Page suivante pour plus de résultats."},
        }),
    )
    async def discover_movies(args):
        try:
            genres = await asyncio.to_thread(tmdb.genres)
        except TMDBError as exc:
            return _error(str(exc))
        genre_ids = {name.lower(): gid for gid, name in genres.items()}

        def to_ids(names):
            unknown = [n for n in names or [] if n.lower() not in genre_ids]
            if unknown:
                raise TMDBError(f"genre(s) inconnu(s) : {', '.join(unknown)}")
            return [genre_ids[n.lower()] for n in names] if names else None

        try:
            kwargs = {k: v for k, v in args.items() if k not in ("genres", "exclude_genres")}
            kwargs["genre_ids"] = to_ids(args.get("genres"))
            kwargs["exclude_genre_ids"] = to_ids(args.get("exclude_genres"))
        except TMDBError as exc:
            return _error(str(exc))
        return await run(tmdb.discover_movies, **kwargs, record=True)

    @tool(
        "get_movie_details",
        "Fiche détaillée d'un film : réalisation, casting, durée, langue originale, mots-clés, "
        "résumé (attention : le résumé peut contenir des spoilers, ne le recopie pas). "
        "À réserver aux finalistes.",
        _schema({"tmdb_id": {"type": "integer"}}, ["tmdb_id"]),
    )
    async def get_movie_details(args):
        return await run(tmdb.get_movie_details, args["tmdb_id"], record=True)

    @tool(
        "get_watch_options",
        "Où regarder un film CHEZ SOI en France, avec un lien par option, triées par priorité : "
        "abonnement (Netflix, Canal+) > gratuit (Arte, france.tv…) > location > achat > "
        "autre_abonnement (plateforme qu'elle n'a pas). Le champ link est le lien à donner.",
        _schema({"tmdb_id": {"type": "integer"}}, ["tmdb_id"]),
    )
    async def get_watch_options(args):
        return await run(tmdb.get_watch_providers, args["tmdb_id"], record=True)

    @tool(
        "search_person",
        "Trouve le person_id d'un·e cinéaste ou d'un·e acteur·rice (pour get_person_filmography "
        "ou discover_movies). Corrige l'orthographe du nom si besoin.",
        _schema({"name": {"type": "string"}}, ["name"]),
    )
    async def search_person(args):
        return await run(tmdb.search_person, args["name"])

    @tool(
        "get_person_filmography",
        "Filmographie d'une personne, du plus récent au plus ancien. role='directing' : films "
        "qu'elle a réalisés. role='acting' : films où elle joue ; max_billing=3 ne garde que les "
        "rôles principaux (les 4 premiers noms au générique).",
        _schema({
            "person_id": {"type": "integer"},
            "role": {"type": "string", "enum": ["acting", "directing"]},
            "max_billing": {"type": "integer"},
        }, ["person_id", "role"]),
    )
    async def get_person_filmography(args):
        return await run(tmdb.get_person_filmography, args["person_id"],
                         role=args["role"], max_billing=args.get("max_billing"), record=True)

    @tool(
        "search_keyword",
        "Trouve des keyword_id TMDB pour un thème (pour discover_movies). Les mots-clés TMDB "
        "sont surtout EN ANGLAIS : cherche « time travel », « road trip », « buenos aires ».",
        _schema({"query": {"type": "string"}}, ["query"]),
    )
    async def search_keyword(args):
        return await run(tmdb.search_keyword, args["query"])

    return [search_my_ratings, check_already_seen, search_movie, discover_movies,
            get_movie_details, get_watch_options, search_person, get_person_filmography,
            search_keyword, remember_preference, forget_preference, record_feedback]


def build_server(tools: list):
    """Regroupe les outils dans un serveur MCP « en mémoire » (dans le même programme)."""
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=tools)


def allowed_tool_names(tools: list) -> list[str]:
    """Le SDK nomme les outils mcp__<serveur>__<outil>."""
    return [f"mcp__{SERVER_NAME}__{t.name}" for t in tools]
