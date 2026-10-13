"""Mes notes de films dans Pinecone : ajouter, modifier, supprimer, exporter.

C'est ce qui fait APPRENDRE l'agent : chaque film noté enrichit la base qu'il consulte
pour comprendre mes goûts (le RAG de la phase 2).

Ce que je saisis : la note, le commentaire, l'année de visionnage.
Ce qui est automatique (TMDB) : titre, année de sortie, réalisation, genres, casting, résumé.

Cohabitation avec le CSV d'origine :
- même identifiant que l'import (tmdb-12345) : pas de doublon ;
- les films ajoutés ou modifiés ici portent source="app" (ou "agent") : l'import du CSV
  ne les écrase plus et ne les supprime plus. L'app fait foi ; to_csv() permet un export.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from config import PROJECT_DIR
from memory import SEEN_STATUSES, Memory
from ratings_csv import Rating, build_record
from ratings_store import RatingsStore
from tmdb_client import TMDBClient

JOURNAL_FILE = PROJECT_DIR / "data" / "ajouts_agent.csv"
COLUMNS = ["titre", "annee_sortie", "annee_visionnage", "note_sur_5", "commentaire"]


def _check(note: float, annee_visionnage: int | None) -> int:
    if not 0 <= note <= 5:
        raise ValueError("la note doit être entre 0 et 5")
    this_year = date.today().year
    if annee_visionnage is not None and not 1900 <= annee_visionnage <= this_year:
        raise ValueError(f"l'année de visionnage doit être entre 1900 et {this_year}")
    return this_year


def save_rating(tmdb: TMDBClient, store: RatingsStore, memory: Memory, *, note: float,
                commentaire: str = "", annee_visionnage: int | None = None,
                tmdb_id: int | None = None, existing: dict | None = None,
                status: str | None = None, source: str = "app") -> dict:
    """Ajoute ou met à jour un film dans mes notes. Renvoie ses champs tels que stockés.

    - nouveau film : tmdb_id (les faits viennent de TMDB) ;
    - film existant : existing = ses champs actuels (même identifiant, texte recalculé).
    Le texte vectorisé est TOUJOURS reconstruit : la recherche suit donc mes modifications.
    """
    this_year = _check(note, annee_visionnage)
    tmdb_id = tmdb_id or (existing or {}).get("tmdb_id")
    if tmdb_id:
        details = tmdb.get_movie_details(tmdb_id)  # vérifie aussi que le film existe vraiment
        titre, annee_sortie = details["title"], details.get("year")
    else:  # film du CSV que TMDB n'avait pas reconnu : on garde ce qu'on sait déjà
        known = {"genres": existing.get("genres"), "directors": existing.get("realisation"),
                 "cast": existing.get("casting"), "original_language": existing.get("langue_originale")}
        details = {k: v for k, v in known.items() if v}  # champs absents : simplement omis
        titre, annee_sortie = existing["titre"], existing.get("annee_sortie")
    if existing:  # on garde le titre que j'utilisais et l'identifiant d'origine
        titre = existing.get("titre") or titre
    rating = Rating(titre=titre, annee_sortie=annee_sortie,
                    annee_visionnage=annee_visionnage or (existing or {}).get("annee_visionnage") or this_year,
                    note=note, commentaire=commentaire.strip(), line=0)
    record = build_record(rating, tmdb_id, details)
    if existing:
        record["_id"] = existing["id"]
    record["source"] = source
    store.upsert([record])

    if tmdb_id:  # la mémoire suit : « Vu et aimé » / « Vu et pas aimé » (et sort de « Plus tard »)
        memory.set_feedback(tmdb_id, rating.titre, status or ("vu_aime" if note >= 3 else "vu_pas_aime"))
    stored = {k: v for k, v in record.items() if k not in ("_id", "chunk_text")}
    return {"id": record["_id"], **stored}


def add_seen_film(tmdb: TMDBClient, store: RatingsStore, memory: Memory, tmdb_id: int,
                  note: float, commentaire: str = "", annee_visionnage: int | None = None,
                  status: str | None = None, source: str = "agent") -> dict:
    """« Je l'ai vu » (agent ou carte) : ajoute le film à mes notes, et un résumé pour l'agent."""
    if status is not None and status not in SEEN_STATUSES:
        raise ValueError(f"statut inconnu pour un film vu : {status}")
    stored = save_rating(tmdb, store, memory, note=note, commentaire=commentaire,
                         annee_visionnage=annee_visionnage, tmdb_id=tmdb_id, status=status, source=source)
    _append_to_journal(stored)
    return {"ajoute_a_mes_notes": True, "titre": stored["titre"], "annee": stored.get("annee_sortie"),
            "annee_visionnage": stored.get("annee_visionnage"), "note": note,
            "commentaire": stored.get("commentaire", ""),
            "statut": memory.status_of(tmdb_id)}


def delete_rating(store: RatingsStore, memory: Memory, film: dict) -> None:
    """Retire un film de mes notes (et de « Vu » dans la mémoire)."""
    store.delete([film["id"]])
    tmdb_id = film.get("tmdb_id")
    if tmdb_id and memory.status_of(tmdb_id) in SEEN_STATUSES:
        memory.clear_feedback(tmdb_id)


def to_csv(films: list[dict]) -> str:
    """Export de mes notes au format de mon CSV d'origine (+ tmdb_id), pour mon tableur."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS + ["tmdb_id"])
    for f in sorted(films, key=lambda f: (f.get("titre") or "").lower()):
        writer.writerow([f.get("titre", ""), f.get("annee_sortie", ""), f.get("annee_visionnage", ""),
                         f"{f.get('note', 0):g}", f.get("commentaire", ""), f.get("tmdb_id", "")])
    return out.getvalue()


def _append_to_journal(stored: dict) -> None:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not JOURNAL_FILE.exists()
    with JOURNAL_FILE.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(COLUMNS)
        writer.writerow([stored["titre"], stored.get("annee_sortie", ""), stored.get("annee_visionnage", ""),
                         f"{stored['note']:g}", stored.get("commentaire", "")])
