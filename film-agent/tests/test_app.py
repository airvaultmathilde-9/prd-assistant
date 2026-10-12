"""Tests de l'interface (phase 6 anticipée) et du contrôle « aucun film inventé ».

L'interface est testée avec AppTest (fourni par Streamlit) et un faux agent :
pas de navigateur, pas de réseau, pas de LLM.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import recommend as recommend_module  # noqa: E402
from agent_tools import SessionRegistry  # noqa: E402
from recommend import Answer, Film, verify_and_enrich  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")


class FakeTMDB:
    def get_movie_details(self, tmdb_id):
        return {"title": "Mandibules", "year": 2020, "directors": ["Quentin Dupieux"],
                "runtime_min": 77, "original_language": "fr", "poster_url": None}

    def get_watch_providers(self, tmdb_id):
        return {"options": [{"platform": "Netflix", "access": "abonnement", "link": "https://netflix.com/x"},
                            {"platform": "Apple TV", "access": "location", "link": "https://tmdb/x"}]}


def test_feedback_buttons_and_memory_sidebar(app, monkeypatch, tmp_path):
    from memory import Memory
    Memory().add_preference("Préfère la VO sous-titrée")
    film = Film("choix_sur", 597298, "x", "y", FakeTMDB().get_movie_details(1), FakeTMDB().get_watch_providers(1))
    monkeypatch.setattr(recommend_module, "recommend",
                        fake_recommend(Answer("recommendations", "Voici", [film], "s1")))
    app.run()
    assert any("Préfère la VO sous-titrée" in m.value for m in app.sidebar.markdown)
    app.text_area[0].input("Un film")
    click_find(app)
    assert not app.exception
    pills = app.button_group[0]
    pills.set_value("plus_tard").run()
    assert Memory().films_with("plus_tard") == [(597298, "Mandibules")]
    assert any("Mandibules" in m.value for m in app.sidebar.markdown)


def test_invented_film_is_rejected_and_facts_come_from_tmdb():
    registry = SessionRegistry({597298: "Mandibules"})
    raw = [{"role": "choix_sur", "tmdb_id": 597298, "why": "Comme Fumer fait tousser", "vibe": "Absurde"},
           {"role": "decouverte", "tmdb_id": 597298, "why": "Doublon", "vibe": "Absurde"},
           {"role": "pari", "tmdb_id": 999999, "why": "Inventé", "vibe": "?"}]
    films, rejected = verify_and_enrich(raw, registry, FakeTMDB())
    assert [f.tmdb_id for f in films] == [597298] and rejected == [999999]
    assert films[0].details["runtime_min"] == 77 and films[0].language_label == "Français"
    assert films[0].role_label == "🎯 Le choix sûr"


@pytest.fixture
def app(monkeypatch, tmp_path):
    import memory
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "memoire.json")
    testing = pytest.importorskip("streamlit.testing.v1")
    for key in ("ANTHROPIC_API_KEY", "PINECONE_API_KEY", "TMDB_API_KEY", "CLAUDE_MODEL"):
        monkeypatch.setenv(key, "x")
    return testing.AppTest.from_file(APP, default_timeout=10)


def click_find(app):
    next(b for b in app.button if b.label == "Trouver 3 films").click().run()


def fake_recommend(answer):
    async def _recommend(prompt, settings, registry, session_id=None, on_tool=None, memory=None):
        on_tool("discover_movies", {"genres": ["Comédie"]})
        return answer
    return _recommend


def test_app_shows_three_cards(app, monkeypatch):
    films = [Film(role, tmdb_id, "Comme Fumer fait tousser", "Absurde et solaire",
                  FakeTMDB().get_movie_details(1), FakeTMDB().get_watch_providers(1))
             for role, tmdb_id in (("choix_sur", 1), ("decouverte", 2), ("pari", 3))]
    monkeypatch.setattr(recommend_module, "recommend",
                        fake_recommend(Answer("recommendations", "Voici mes idées", films, "s1")))
    app.run()
    app.text_area[0].input("Un film absurde")
    click_find(app)
    assert not app.exception
    assert [s.value for s in app.subheader] == ["Mandibules (2020)"] * 3
    assert any("Voici mes idées" in m.value for m in app.markdown)
    assert app.text_area[0].value == "Un film absurde"  # la demande reste visible


def test_app_relays_the_agent_question(app, monkeypatch):
    monkeypatch.setattr(recommend_module, "recommend",
                        fake_recommend(Answer("question", "Plutôt léger ou intense ?", [], "s1")))
    app.run()
    app.text_area[0].input("Un film")
    click_find(app)
    assert not app.exception
    assert "Plutôt léger ou intense ?" in app.info[0].value
    assert app.text_area[0].label == "Ta réponse" and app.text_area[0].value == ""
