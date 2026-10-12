"""Tests de « je l'ai déjà vu » : l'agent ajoute le film à mes notes Pinecone."""

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seen_films  # noqa: E402
from memory import Memory  # noqa: E402
from ratings_store import RatingsStore  # noqa: E402


class FakeTMDB:
    def get_movie_details(self, tmdb_id):
        return {"title": "Le Daim", "year": 2019, "directors": ["Quentin Dupieux"],
                "genres": ["Comédie"], "cast": ["Jean Dujardin"], "overview": "Un blouson."}


class FakeIndex:
    def __init__(self, stored=None):
        self.upserts, self.stored = [], stored or {}

    def upsert_records(self, namespace, records):
        self.upserts += records

    def fetch(self, ids, namespace):
        return SimpleNamespace(vectors={i: SimpleNamespace(metadata=self.stored[i]) for i in ids if i in self.stored})


@pytest.fixture
def journal(tmp_path, monkeypatch):
    path = tmp_path / "ajouts_agent.csv"
    monkeypatch.setattr(seen_films, "JOURNAL_FILE", path)
    return path


def test_add_seen_film_goes_to_pinecone_journal_and_memory(tmp_path, journal):
    index, memory = FakeIndex(), Memory(tmp_path / "memoire.json")
    memory.set_feedback(42, "Le Daim", "plus_tard")
    result = seen_films.add_seen_film(FakeTMDB(), RatingsStore("k", "i", index=index), memory,
                                      42, 4.5, "Absurde et sec, j'ai adoré", 2026)
    record = index.upserts[0]
    assert record["_id"] == "tmdb-42"          # même identifiant que l'import CSV : pas de doublon
    assert record["source"] == "agent"         # l'import ne le supprimera pas
    assert record["note"] == 4.5 and "j'ai adoré" in record["chunk_text"]
    assert result["titre"] == "Le Daim"
    assert memory.status_of(42) == "vu_aime"   # passe de « Plus tard » à « Vu et aimé »
    assert result["statut"] == "vu_aime" and result["annee_visionnage"] == 2026
    rows = list(csv.reader(journal.open(encoding="utf-8")))
    assert rows == [seen_films.COLUMNS, ["Le Daim", "2019", "2026", "4.5", "Absurde et sec, j'ai adoré"]]


def test_invalid_note_is_refused(tmp_path, journal):
    with pytest.raises(ValueError):
        seen_films.add_seen_film(FakeTMDB(), RatingsStore("k", "i", index=FakeIndex()),
                                 Memory(tmp_path / "m.json"), 42, 7)
    assert not journal.exists()


def test_store_knows_which_records_come_from_the_agent():
    index = FakeIndex({"tmdb-1": {"note": 4.0}, "tmdb-2": {"note": 3.0, "source": "agent"}})
    assert RatingsStore("k", "i", index=index).added_by_agent(["tmdb-1", "tmdb-2", "tmdb-3"]) == {"tmdb-2"}


def test_status_follows_the_choice_or_the_note(tmp_path, journal):
    store, memory = RatingsStore("k", "i", index=FakeIndex()), Memory(tmp_path / "m.json")
    assert seen_films.add_seen_film(FakeTMDB(), store, memory, 1, 2)["statut"] == "vu_pas_aime"
    assert seen_films.add_seen_film(FakeTMDB(), store, memory, 2, 3.5)["statut"] == "vu_aime"
    # Choix explicite (bouton « Vu et pas aimé ») : il l'emporte sur la note.
    assert seen_films.add_seen_film(FakeTMDB(), store, memory, 3, 3, status="vu_pas_aime")["statut"] == "vu_pas_aime"


def test_impossible_viewing_year_is_refused(tmp_path, journal):
    with pytest.raises(ValueError, match="année"):
        seen_films.add_seen_film(FakeTMDB(), RatingsStore("k", "i", index=FakeIndex()),
                                 Memory(tmp_path / "m.json"), 1, 4, annee_visionnage=2999)
