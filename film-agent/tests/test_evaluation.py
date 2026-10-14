"""Tests de l'évaluation (phase 7) : contrôles, juge simulé, rapport. Aucun appel payant."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import evaluation as ev  # noqa: E402
from claude_agent_sdk import ResultMessage  # noqa: E402
from recommend import Answer, Film  # noqa: E402


def film(role, tmdb_id, why="Comme Mandibules, que tu as adoré.", runtime=95, cast=("Adèle Exarchopoulos",),
         lang="fr", year=2020, access="abonnement", platform="Netflix"):
    return Film(role, tmdb_id, why, "Absurde",
                {"title": f"Film {tmdb_id}", "year": year, "runtime_min": runtime, "cast": list(cast),
                 "directors": ["Quentin Dupieux"], "original_language": lang, "overview": "Résumé."},
                {"options": [{"platform": platform, "access": access, "link": "https://x"}]})


def three(**kwargs):
    return [film("choix_sur", 1, **kwargs), film("decouverte", 2, **kwargs), film("pari", 3, **kwargs)]


CASE = {"id": "adele", "demande": "Adèle en moins de 2 h", "attendu": "…",
        "controles": {"question": False, "personne": "Adele Exarchopoulos", "duree_max": 120}}


def test_cases_file_is_valid_and_ids_are_unique():
    cases = ev.load_cases()
    assert len(cases) >= 10 and len({c["id"] for c in cases}) == len(cases)
    assert any(c["controles"].get("question") is True for c in cases)  # au moins une demande ambiguë
    with pytest.raises(ValueError):
        ev.load_cases(["n-existe-pas"])


def test_all_checks_pass_on_a_good_answer():
    answer = Answer("recommendations", "", three(), "s", cost_usd=0.08)
    checks = ev.run_checks(CASE, answer, seen_ids={99}, my_titles=["Mandibules"], max_cost=0.15)
    assert all(checks.values()), checks
    assert {"bonne_personne", "duree_respectee", "justif_cite_mes_films", "dispo_chez_moi"} <= set(checks)


def test_checks_catch_the_usual_mistakes():
    films = three(runtime=130, why="Un beau film.", access="autre_abonnement")
    answer = Answer("recommendations", "", films, "s", rejected=[42], cost_usd=0.2)
    checks = ev.run_checks(CASE, answer, seen_ids={2}, my_titles=["Mandibules"], max_cost=0.15)
    failed = {k for k, ok in checks.items() if not ok}
    assert failed == {"duree_respectee", "justif_cite_mes_films", "dispo_chez_moi", "aucun_deja_vu",
                      "aucun_film_invente", "cout_sous_le_plafond"}


def test_purchase_is_only_ok_for_the_bet():
    films = three()
    films[2].watch = {"options": [{"platform": "Apple TV", "access": "achat"}]}
    ok = ev.run_checks(CASE, Answer("recommendations", "", films, "s"), set(), ["Mandibules"], 1)
    films[0].watch = films[2].watch
    ko = ev.run_checks(CASE, Answer("recommendations", "", films, "s"), set(), ["Mandibules"], 1)
    assert ok["dispo_chez_moi"] and not ko["dispo_chez_moi"]


def test_expected_question():
    case = {"id": "q", "controles": {"question": True}}
    assert ev.run_checks(case, Answer("question", "Quel Thomas ?", [], "s"), set(), [], 1)["pose_une_question"]
    assert not ev.run_checks(case, Answer("recommendations", "", three(), "s"), set(), [], 1)["pose_une_question"]


def test_title_must_be_a_whole_word_match():
    assert ev._mentions("Comme « Le Daim », absurde", "Le Daim")
    assert not ev._mentions("Un daimyo japonais", "Daim")


def test_judge_reads_the_structured_verdict(monkeypatch):
    seen = {}

    async def fake_query(prompt, options):
        seen["prompt"], seen["options"] = prompt, options
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1,
                            session_id="j", total_cost_usd=0.01,
                            structured_output={"respect_demande": 5, "justifications": 4, "variete": 4,
                                               "sans_spoiler": 5, "ecriture": 3, "commentaire": "Bien."})
    monkeypatch.setattr(ev, "query", fake_query)
    answer = Answer("recommendations", "", three(), "s")
    verdict = asyncio.run(ev.judge(CASE, answer, [{"titre": "Mandibules", "note": 4.5}], "m", "k"))
    assert verdict.scores["respect_demande"] == 5 and verdict.cost_usd == 0.01
    assert "Mandibules : 4.5/5" in seen["prompt"] and "Résumé" in seen["prompt"]
    assert seen["options"].tools == []  # le juge n'a aucun outil


def result(id_, ok, mean):
    return ev.CaseResult(id_, "d", "recommendations", ["Film"], {"a": ok, "b": True},
                         {c: mean for c in ev.CRITERIA}, "RAS", 0.1, 8)


def test_report_and_comparison():
    before = ev.to_json([result("x", False, 3), result("y", True, 4)], {"date": "J1", "modele": "sonnet", "juge": "s"})
    after = ev.to_json([result("x", True, 4), result("y", True, 4)], {"date": "J2", "modele": "haiku", "juge": "s"})
    assert before["resume"]["controles_reussis"] == "3/4" and before["resume"]["note_juge_moyenne"] == 3.5
    assert "| x | 1/2 | 3.0 |" in ev.markdown_report(before)
    table = ev.compare(before, after)
    assert "| x | 3.0 → 4.0 | 1/2 → 2/2 |" in table and "| Note du juge | 3.5 | 4.0 |" in table


def load_script():
    spec = importlib.util.spec_from_file_location("eval_script", ROOT / "scripts" / "eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unexpected_question_is_answered_once_and_counted(monkeypatch, tmp_path):
    script = load_script()
    import costs
    import memory
    monkeypatch.setattr(memory, "MEMORY_FILE", memory.MEMORY_FILE)  # remis en place après le test
    monkeypatch.setattr(costs, "COSTS_FILE", costs.COSTS_FILE)
    script.isolate(tmp_path)
    prompts = []

    async def fake_recommend(prompt, settings, registry, session_id=None, memory=None, **_):
        prompts.append((prompt, session_id))
        if session_id is None:
            return Answer("question", "Plutôt drôle ou triste ?", [], "s1", cost_usd=0.02, turns=2, trace_id="t")
        return Answer("recommendations", "", three(), "s1", cost_usd=0.05, turns=5, trace_id="t")

    async def fake_judge(*args):
        return ev.Verdict({c: 4 for c in ev.CRITERIA}, "ok", 0.01)

    monkeypatch.setattr(script, "recommend", fake_recommend)
    monkeypatch.setattr(script.ev, "judge", fake_judge)
    monkeypatch.setattr(script, "get_client", lambda: None)
    from config import Settings
    settings = Settings("a", "p", "t", "m", "i")
    res = asyncio.run(script.run_case(CASE, settings, [{"titre": "Mandibules", "note": 4}], set(), "j", "run"))
    assert prompts == [(CASE["demande"], None), (script.DEFAULT_REPLY, "s1")]
    assert res.checks["pas_de_question_inutile"] is False and res.checks["assez_de_films"]
    assert res.tours == 7 and res.cost_usd == 0.08
    assert json.loads((tmp_path / "couts.json").read_text())  # le coût du juge est compté à part
