"""Tests de la page « Mes films » (AppTest de Streamlit, Pinecone et TMDB simulés)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import my_films  # noqa: E402

FILMS = [
    {"id": "tmdb-1", "titre": "Le Daim", "annee_sortie": 2019, "note": 4.0, "commentaire": "Absurde et sec",
     "realisation": ["Quentin Dupieux"], "tmdb_id": 1, "annee_visionnage": 2022},
    {"id": "tmdb-2", "titre": "Le Sens de la fête", "annee_sortie": 2017, "note": 2.0,
     "commentaire": "Trop long", "realisation": ["Éric Toledano"], "tmdb_id": 2},
]


class FakeStore:
    def __init__(self):
        self.saved, self.deleted = [], []

    def list_all(self):
        return [dict(f) for f in FILMS]


class FakeTMDB:
    def search_movies(self, query, limit=6):
        return [{"tmdb_id": 3, "title": "Mandibules", "original_title": "Mandibules", "year": 2020},
                {"tmdb_id": 1, "title": "Le Daim", "original_title": "Le Daim", "year": 2019}]


@pytest.fixture
def page(monkeypatch, tmp_path):
    testing = pytest.importorskip("streamlit.testing.v1")
    import memory
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "memoire.json")
    store = FakeStore()
    monkeypatch.setattr(my_films, "_clients", lambda: (FakeTMDB(), store))
    saved = []

    def fake_save(tmdb, store_, memory_, **kwargs):
        saved.append(kwargs)
        film = kwargs.get("existing") or {"id": f"tmdb-{kwargs['tmdb_id']}", "titre": "Mandibules",
                                          "tmdb_id": kwargs.get("tmdb_id")}
        return {**film, "note": kwargs["note"], "commentaire": kwargs["commentaire"]}

    monkeypatch.setattr(my_films, "save_rating", fake_save)

    def run_page():
        import my_films as page_module
        page_module.render()

    app = testing.AppTest.from_function(run_page, default_timeout=10)
    app.saved = saved
    return app


def titles(app):
    return [m.value for m in app.markdown if m.value.startswith('<div class="mf-title">')]


def test_lists_everything_with_filters(page):
    page.run()
    assert not page.exception
    assert len(titles(page)) == 2 and "Le Daim" in titles(page)[0]   # tri par note : 4 avant 2
    page.selectbox[0].set_value("👎 Pas aimés (2 et moins)").run()
    assert len(titles(page)) == 1 and "Le Sens de la fête" in titles(page)[0]
    page.selectbox[0].set_value("Toutes les notes").run()
    page.text_input[0].input("dupieux").run()                     # recherche dans la réalisation
    assert len(titles(page)) == 1 and "Le Daim" in titles(page)[0]


def test_edit_only_asks_for_note_comment_and_year(page):
    page.run()
    next(b for b in page.button if b.key == "mf-edit-btn-tmdb-1").click().run()
    assert [s.label for s in page.slider] == ["Ta note sur 5"] and page.slider[0].value == 4.0
    assert page.text_area[0].value == "Absurde et sec" and page.number_input[0].value == 2022
    page.slider[0].set_value(5.0)
    page.text_area[0].input("Revu : chef-d'œuvre d'absurde")
    next(b for b in page.button if b.label == "Enregistrer").click().run()
    assert not page.exception
    assert page.saved[-1]["existing"]["id"] == "tmdb-1" and page.saved[-1]["note"] == 5.0
    assert page.saved[-1]["commentaire"] == "Revu : chef-d'œuvre d'absurde"
    assert any("Revu : chef-d" in t for t in titles(page) + [m.value for m in page.markdown])


def test_add_searches_tmdb_and_refuses_duplicates(page):
    page.run()
    next(b for b in page.button if b.label == "➕ Ajouter un film").click().run()
    page.text_input[-1].input("mandi")
    next(b for b in page.button if b.label == "🔎 Chercher dans TMDB").click().run()
    radio = page.radio[0]
    assert "déjà dans tes notes" in radio.options[1]               # Le Daim y est déjà
    radio.set_value(radio.options[1]).run()
    assert any("déjà dans tes notes" in w.value for w in page.warning)
    page.radio[0].set_value(page.radio[0].options[0]).run()         # Mandibules
    page.slider[0].set_value(3.5)
    next(b for b in page.button if b.label == "Enregistrer dans mes notes").click().run()
    assert not page.exception
    assert page.saved[-1]["tmdb_id"] == 3 and page.saved[-1]["note"] == 3.5
    assert len(titles(page)) == 3
