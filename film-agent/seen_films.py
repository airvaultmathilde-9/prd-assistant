"""Ajouter un film vu à mes notes (Pinecone), depuis la conversation ou l'interface.

C'est ce qui fait APPRENDRE l'agent : chaque film que je dis avoir vu enrichit
la base qu'il consulte pour comprendre mes goûts (le RAG de la phase 2).

Cohabitation avec le CSV (qui « fait foi » à l'import) :
- même identifiant que l'import (tmdb-12345) : pas de doublon, et si j'ajoute
  le film à mon CSV plus tard, c'est la version du CSV qui l'emporte ;
- les ajouts portent source="agent" : l'import ne les supprime jamais ;
- chaque ajout est aussi écrit dans data/ajouts_agent.csv (mêmes colonnes que
  mon CSV), pour que je puisse les recopier dans mon tableur.
"""

from __future__ import annotations

import csv
from datetime import date

from config import PROJECT_DIR
from memory import Memory
from ratings_csv import Rating, build_record
from ratings_store import RatingsStore
from tmdb_client import TMDBClient

JOURNAL_FILE = PROJECT_DIR / "data" / "ajouts_agent.csv"
COLUMNS = ["titre", "annee_sortie", "annee_visionnage", "note_sur_5", "commentaire"]


def add_seen_film(tmdb: TMDBClient, store: RatingsStore, memory: Memory, tmdb_id: int,
                  note: float, commentaire: str = "", annee_visionnage: int | None = None) -> dict:
    if not 0 <= note <= 5:
        raise ValueError("la note doit être entre 0 et 5")
    details = tmdb.get_movie_details(tmdb_id)  # vérifie aussi que le film existe vraiment
    rating = Rating(titre=details["title"], annee_sortie=details.get("year"),
                    annee_visionnage=annee_visionnage or date.today().year,
                    note=note, commentaire=commentaire.strip(), line=0)
    record = build_record(rating, tmdb_id, details)
    record["source"] = "agent"
    store.upsert([record])
    _append_to_journal(rating)
    # Vu : il n'a plus rien à faire dans « Plus tard » ou « Pas envie ».
    if memory.status_of(tmdb_id) in ("plus_tard", "pas_envie"):
        memory.clear_feedback(tmdb_id)
    return {"ajoute_a_mes_notes": True, "titre": rating.titre, "annee": rating.annee_sortie,
            "note": note, "commentaire": rating.commentaire}


def _append_to_journal(rating: Rating) -> None:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not JOURNAL_FILE.exists()
    with JOURNAL_FILE.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(COLUMNS)
        writer.writerow([rating.titre, rating.annee_sortie or "", rating.annee_visionnage or "",
                         f"{rating.note:g}", rating.commentaire])
