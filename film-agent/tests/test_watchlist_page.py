"""Tests de la page « À voir » (AppTest de Streamlit, TMDB et Pinecone simulés)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import my_films  # noqa: E402


class FakeTMDB:
    def get_movie_details(self, tmdb_id):
        return {"title": "Mandibules", "year": 2020, "runtime_min": 77, "directors": ["Quentin Dupieux"],
                "genres": ["Comédie"], "poster_url": None}

    def get_watch_providers(self, tmdb_id):
        return {"options": [{"platform": "Netflix", "access": "abonnement", "link": "https://netflix.com/x"}]}

    def search_movies(self, query, limit=6):
        return [{"tmdb_id": 7, "title": "Le Daim", "year": 2019}]


@pytest.fixture
def page(monkeypatch, tmp_path):
    testing = pytest.importorskip("streamlit.testing.v1")
    import memory
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "memoire.json")
    monkeypatch.setattr(my_films, "_clients", lambda: (FakeTMDB(), None))
    saved = []

    def fake_save(**kwargs):  # remplace my_films._save : Pinecone n'est pas appelé
        saved.append(kwargs)
        memory.Memory().set_feedback(kwargs["tmdb_id"], "Mandibules", "vu_aime" if kwargs["note"] >= 3 else "vu_pas_aime")
        return True

    monkeypatch.setattr(my_films, "_save", fake_save)

    def run_page():
        import watchlist
        watchlist.render()

    app = testing.AppTest.from_function(run_page, default_timeout=10)
    app.saved = saved
    return app


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_lists_films_set_aside_with_where_to_watch(page):
    from memory import Memory
    Memory().set_feedback(597298, "Mandibules", "plus_tard")
    page.run()
    assert not page.exception
    assert any("Mandibules" in m.value and "1 h 17" in m.value and "Netflix · inclus" in m.value
               for m in page.markdown)
    assert {el.proto.label for el in page.get("link_button")} == {"▶️ Netflix"}


def test_seen_moves_the_film_to_my_films(page):
    from memory import Memory
    Memory().set_feedback(597298, "Mandibules", "plus_tard")
    page.run()
    button(page, "✅ Je l'ai vu").click().run()
    page.slider[0].set_value(4.5)
    page.text_area[0].input("Absurde et drôle")
    button(page, "Ranger dans mes films").click().run()
    assert not page.exception
    assert page.saved[0]["tmdb_id"] == 597298 and page.saved[0]["note"] == 4.5
    assert Memory().films_with("plus_tard") == [] and Memory().status_of(597298) == "vu_aime"


def test_add_and_remove(page):
    from memory import Memory
    page.run()
    button(page, "➕ Mettre un film de côté").click().run()
    page.text_input[0].input("daim")
    button(page, "🔎 Chercher dans TMDB").click().run()
    button(page, "🕒 Mettre de côté").click().run()
    assert not page.exception
    assert Memory().films_with("plus_tard") == [(7, "Le Daim")]
    button(page, "Retirer").click().run()
    assert Memory().films_with("plus_tard") == []
