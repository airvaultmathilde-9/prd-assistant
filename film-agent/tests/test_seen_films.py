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


def test_store_knows_which_records_are_managed_in_the_app():
    index = FakeIndex({"tmdb-1": {"note": 4.0}, "tmdb-2": {"note": 3.0, "source": "agent"},
                       "tmdb-4": {"note": 2.0, "source": "app"}})
    store = RatingsStore("k", "i", index=index)
    assert store.managed_in_app(["tmdb-1", "tmdb-2", "tmdb-3", "tmdb-4"]) == {"tmdb-2", "tmdb-4"}


def test_csv_import_never_overwrites_nor_deletes_films_managed_in_the_app():
    from ratings_store import plan_sync
    existing = {"tmdb-1", "tmdb-2", "tmdb-3", "csv-vieux"}
    csv_ids = {"tmdb-1", "tmdb-2", "tmdb-9"}
    managed = {"tmdb-2", "tmdb-3"}            # modifié dans l'app / ajouté dans l'app
    to_upsert, stale = plan_sync(existing, csv_ids, managed)
    assert to_upsert == {"tmdb-1", "tmdb-9"}  # tmdb-2 n'est pas écrasé par le CSV
    assert stale == ["csv-vieux"]             # tmdb-3 n'est pas supprimé


class ListIndex(FakeIndex):
    def list(self, namespace):
        yield SimpleNamespace(vectors=[SimpleNamespace(id=i) for i in self.stored])


def test_list_all_returns_clean_fields():
    index = ListIndex({"tmdb-1": {"titre": "Le Daim", "note": 4.0, "annee_sortie": 2019.0,
                                  "tmdb_id": 1.0, "chunk_text": "…"}})
    assert RatingsStore("k", "i", index=index).list_all() == [
        {"id": "tmdb-1", "titre": "Le Daim", "note": 4.0, "annee_sortie": 2019, "tmdb_id": 1}]


def test_editing_keeps_the_id_and_recomputes_the_searchable_text(tmp_path, journal):
    index, memory = FakeIndex(), Memory(tmp_path / "m.json")
    existing = {"id": "tmdb-42", "titre": "Le Daim", "tmdb_id": 42, "note": 2.0,
                "commentaire": "Ennuyeux", "annee_visionnage": 2020, "annee_sortie": 2019}
    stored = seen_films.save_rating(FakeTMDB(), RatingsStore("k", "i", index=index), memory,
                                    existing=existing, note=4.5, commentaire="Revu : génial")
    record = index.upserts[0]
    assert record["_id"] == "tmdb-42" and record["source"] == "app"
    assert "Revu : génial" in record["chunk_text"] and "Ennuyeux" not in record["chunk_text"]
    assert record["annee_visionnage"] == 2020           # gardée si je ne la change pas
    assert stored["note"] == 4.5 and memory.status_of(42) == "vu_aime"
    assert not journal.exists()                         # le journal ne concerne que les ajouts


def test_editing_a_csv_film_unknown_to_tmdb(tmp_path, journal):
    index = FakeIndex()
    existing = {"id": "csv-film-perso-2010", "titre": "Film perso", "annee_sortie": 2010, "note": 3.0,
                "genres": ["Drame"]}
    seen_films.save_rating(FakeTMDB(), RatingsStore("k", "i", index=index), Memory(tmp_path / "m.json"),
                           existing=existing, note=3.5, commentaire="Touchant")
    record = index.upserts[0]
    assert record["_id"] == "csv-film-perso-2010" and record["titre"] == "Film perso"
    assert "Genres : Drame." in record["chunk_text"] and "tmdb_id" not in record


def test_delete_and_export(tmp_path):
    class DeleteIndex(FakeIndex):
        def delete(self, ids, namespace):
            self.deleted = ids
    index, memory = DeleteIndex(), Memory(tmp_path / "m.json")
    memory.set_feedback(42, "Le Daim", "vu_aime")
    seen_films.delete_rating(RatingsStore("k", "i", index=index), memory, {"id": "tmdb-42", "tmdb_id": 42})
    assert index.deleted == ["tmdb-42"] and memory.status_of(42) is None
    csv_text = seen_films.to_csv([{"titre": "Le Daim", "annee_sortie": 2019, "annee_visionnage": 2026,
                                   "note": 4.5, "commentaire": "Sec", "tmdb_id": 42}])
    assert csv_text.splitlines() == ["titre,annee_sortie,annee_visionnage,note_sur_5,commentaire,tmdb_id",
                                     "Le Daim,2019,2026,4.5,Sec,42"]


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
