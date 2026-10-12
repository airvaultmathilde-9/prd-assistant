"""Tests de la mémoire (phase 4)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from memory import Memory  # noqa: E402


@pytest.fixture
def memory(tmp_path):
    return Memory(tmp_path / "memoire.json")


def test_memory_survives_a_restart(memory):
    memory.add_preference("Préfère la VO sous-titrée")
    memory.set_feedback(597298, "Mandibules", "vu_aime")
    reloaded = Memory(memory.path)
    assert reloaded.preferences[0]["texte"] == "Préfère la VO sous-titrée"
    assert reloaded.status_of(597298) == "vu_aime"


def test_no_duplicate_preference_and_ids_increase(memory):
    first = memory.add_preference("Pas de films d'horreur")
    assert memory.add_preference("pas de films d'horreur") == first
    assert memory.add_preference("Moins de 2h30")["id"] == first["id"] + 1


def test_feedback_can_change_and_be_cleared(memory):
    memory.set_feedback(1, "Le Daim", "plus_tard")
    memory.set_feedback(1, "Le Daim", "vu_aime")
    assert memory.films_with("plus_tard") == [] and memory.status_of(1) == "vu_aime"
    memory.clear_feedback(1)
    assert memory.status_of(1) is None
    with pytest.raises(ValueError):
        memory.set_feedback(1, "Le Daim", "adore")


def test_prompt_section_lists_everything_the_agent_must_respect(memory):
    assert "(aucune pour l'instant)" in memory.as_prompt()
    memory.add_preference("Préfère la VO sous-titrée")
    memory.set_feedback(42, "Le Daim", "pas_envie")
    prompt = memory.as_prompt()
    assert "- [1] Préfère la VO sous-titrée" in prompt
    assert "## 🙅 Pas envie\n- Le Daim (tmdb_id 42)" in prompt
    assert "ne recommande JAMAIS" in prompt
