"""Tests de la phase 2 (CSV -> TMDB -> Pinecone), sans réseau."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ratings_csv import Rating, build_record, match_rating, read_ratings, record_id  # noqa: E402
from ratings_store import RatingsStore  # noqa: E402

HEADER = "titre\tannee_sortie\tannee_visionnage\tnote_sur_5\tcommentaire\n"


def write_csv(tmp_path, content: str) -> Path:
    path = tmp_path / "notes.csv"
    path.write_text(content, encoding="utf-8")
    return path


def rating(titre="Mandibules", annee=2020, note=4.0, commentaire="Absurde et drôle."):
    return Rating(titre, annee, 2022, note, commentaire, line=2)


# ---------- Lecture du CSV ----------

def test_reads_tab_separated_csv(tmp_path):
    path = write_csv(tmp_path, HEADER + "Mandibules\t2020\t2022\t4\tComplètement absurde.\n")
    ratings, errors = read_ratings(path)
    assert errors == []
    assert ratings == [Rating("Mandibules", 2020, 2022, 4.0, "Complètement absurde.", 2)]


def test_reads_semicolon_csv_with_excel_bom_and_decimal_comma(tmp_path):
    path = tmp_path / "notes.csv"
    path.write_text("titre;annee_sortie;note_sur_5\nLa Haine;1995;4,5\n", encoding="utf-8-sig")
    ratings, _ = read_ratings(path)
    assert ratings[0].titre == "La Haine" and ratings[0].note == 4.5


def test_bad_lines_are_reported_not_fatal(tmp_path):
    path = write_csv(tmp_path, HEADER + "Bon film\t2020\t2021\t4\tok\n"
                                        "Note bizarre\t2020\t2021\tbof\t\n"
                                        "Trop haut\t2020\t2021\t7\t\n"
                                        "\t2020\t2021\t3\t\n")
    ratings, errors = read_ratings(path)
    assert [r.titre for r in ratings] == ["Bon film"]
    assert len(errors) == 3 and "ligne 3" in errors[0]


def test_missing_required_column(tmp_path):
    _, errors = read_ratings(write_csv(tmp_path, "titre;annee\nX;2020\n"))
    assert "note_sur_5" in errors[0]


# ---------- Correspondance avec TMDB ----------

class FakeTMDB:
    """Un faux TMDB : `catalogue` associe une requête à ses résultats."""

    def __init__(self, catalogue: dict):
        self.catalogue = catalogue
        self.queries = []

    def search_movies(self, query, year=None, limit=8):
        self.queries.append((query, year))
        return [m for m in self.catalogue.get(query, []) if year is None or m["year"] == year]


def movie(tmdb_id, title, year, votes=1000, original_title=None):
    return {"tmdb_id": tmdb_id, "title": title, "original_title": original_title or title,
            "year": year, "vote_count": votes}


def test_year_disambiguates_homonyms():
    tmdb = FakeTMDB({"L'Odyssée": [movie(1, "L'Odyssée", 2016, votes=900),
                                   movie(2, "L'Odyssée", 2026, votes=300)]})
    match = match_rating(tmdb, rating("L'Odyssée", 2026))
    assert (match.tmdb_id, match.confidence) == (2, "sûr")


def test_typographic_differences_still_match():
    tmdb = FakeTMDB({"La Vie d'Adèle – Chapitres 1 et 2": [
        movie(152584, "La Vie d'Adèle - Chapitres 1 & 2", 2013)]})
    match = match_rating(tmdb, rating("La Vie d'Adèle – Chapitres 1 et 2", 2013))
    assert (match.tmdb_id, match.confidence) == (152584, "sûr")


def test_falls_back_to_short_title_before_the_dash():
    tmdb = FakeTMDB({"La Bataille de Gaulle": [movie(9, "La Bataille de Gaulle : L'Âge de fer", 2026)]})
    match = match_rating(tmdb, rating("La Bataille de Gaulle – Partie 1 : L'Âge de fer", 2026))
    assert match.tmdb_id == 9 and match.confidence in ("sûr", "probable")
    assert tmdb.queries[0][0] == "La Bataille de Gaulle – Partie 1 : L'Âge de fer"  # titre complet d'abord


def test_doubtful_match_gives_no_id_but_lists_candidates():
    tmdb = FakeTMDB({"Five": [movie(5, "Five Feet Apart", 2019)]})
    match = match_rating(tmdb, rating("Five", 2016))
    assert match.tmdb_id is None and match.confidence == "à vérifier"
    assert match.candidates == ("Five Feet Apart (2019) -> 5",)


def test_not_found():
    assert match_rating(FakeTMDB({}), rating("Film imaginaire", 2020)).confidence == "introuvable"


# ---------- Enregistrement Pinecone ----------

def test_record_text_mixes_facts_and_my_opinion_and_has_no_nulls():
    details = {"directors": ["Quentin Dupieux"], "genres": ["Comédie"],
               "cast": ["Grégoire Ludig", "David Marsais"], "original_language": "fr", "year": 2020}
    record = build_record(rating(), 597298, details)
    assert record["_id"] == "tmdb-597298"
    assert record["chunk_text"] == (
        "Mandibules (2020). Réalisation : Quentin Dupieux. Genres : Comédie. "
        "Avec : Grégoire Ludig, David Marsais. Ma note : 4/5, j'ai aimé. Mon avis : Absurde et drôle.")
    assert record["note"] == 4.0 and record["realisation"] == ["Quentin Dupieux"]
    assert None not in record.values()


def test_record_id_is_stable_and_ascii_without_tmdb():
    assert record_id(rating("L'Été dernier", 2023), None) == "csv-l-ete-dernier-2023"
    record = build_record(rating("Inconnu", None, commentaire=""), None, None)
    assert "tmdb_id" not in record and "commentaire" not in record


# ---------- Pinecone (faux index) ----------

class FakeIndex:
    def __init__(self):
        self.upserts, self.searches = [], []

    def upsert_records(self, namespace, records):
        self.upserts.append((namespace, records))

    def search(self, **kwargs):
        self.searches.append(kwargs)
        hit = SimpleNamespace(score=0.8123, fields={"titre": "Mandibules", "note": 4.0})
        return SimpleNamespace(result=SimpleNamespace(hits=[hit]))

    def list(self, namespace):
        yield SimpleNamespace(vectors=[SimpleNamespace(id="tmdb-1"), SimpleNamespace(id="tmdb-2")])

    def delete(self, ids, namespace):
        self.deleted = (ids, namespace)

    def fetch(self, ids, namespace):
        stored = {"tmdb-597298": SimpleNamespace(metadata={"note": 4.0})}
        return SimpleNamespace(vectors={i: stored[i] for i in ids if i in stored})


def test_upsert_sends_batches_of_at_most_90():
    index = FakeIndex()
    RatingsStore("k", "mes-films", index=index).upsert([{"_id": str(i)} for i in range(200)])
    assert [len(r) for _, r in index.upserts] == [90, 90, 20]
    assert {ns for ns, _ in index.upserts} == {"notes"}


def test_search_builds_note_filter_and_compact_results():
    index = FakeIndex()
    results = RatingsStore("k", "mes-films", index=index).search("absurde", top_k=3, min_note=4)
    call = index.searches[0]
    assert call["inputs"] == {"text": "absurde"} and call["top_k"] == 3
    assert call["filter"] == {"note": {"$gte": 4}}
    assert results == [{"score": 0.812, "titre": "Mandibules", "note": 4.0}]


def test_already_seen_returns_my_note_or_none():
    store = RatingsStore("k", "mes-films", index=FakeIndex())
    assert store.already_seen([597298, 123]) == {597298: 4.0, 123: None}


def test_all_ids_and_delete():
    index = FakeIndex()
    store = RatingsStore("k", "mes-films", index=index)
    assert store.all_ids() == {"tmdb-1", "tmdb-2"}
    store.delete(["tmdb-2"])
    assert index.deleted == (["tmdb-2"], "notes")
