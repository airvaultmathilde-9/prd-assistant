"""Phase 7 : passer les demandes types à l'agent et noter ses réponses.

Depuis film-agent/ :
  python scripts/eval.py                              # toutes les demandes, modèle de .env
  python scripts/eval.py --cas adele-2h,ambigu-thomas # seulement certaines
  python scripts/eval.py --modele claude-haiku-5-5    # essayer un autre modèle
  python scripts/eval.py --comparer data/evals/A.json data/evals/B.json

Garde-fous :
- plafond de dépense propre à l'évaluation (--budget, défaut EVAL_BUDGET_USD ou 1.50 $) :
  on s'arrête avant de le dépasser ; ton budget du jour dans l'app n'est pas touché ;
- l'agent travaille sur une COPIE de ta mémoire : l'évaluation ne la modifie jamais.

Résultats : data/evals/<date>-<modèle>.json et .md (privés, ignorés par git), et dans Langfuse
(scores eval_* rattachés à la trace de chaque demande).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import costs  # noqa: E402
import memory as memory_module  # noqa: E402
import evaluation as ev  # noqa: E402
from agent_tools import SessionRegistry  # noqa: E402
from config import PROJECT_DIR, ConfigError, get_settings  # noqa: E402
from ratings_store import RatingsStore  # noqa: E402
from recommend import recommend  # noqa: E402
from tracing import get_client  # noqa: E402

RESULTS_DIR = PROJECT_DIR / "data" / "evals"
# Si l'agent pose une question là où on ne l'attendait pas, on lui répond ceci, une fois.
DEFAULT_JUDGE = "claude-sonnet-5-5"
DEFAULT_REPLY = "Fais au mieux selon mes goûts, sans me reposer de question."


def isolate(tmp: Path) -> None:
    """Mémoire copiée et compteur de coûts à part : l'évaluation ne touche pas aux vrais fichiers."""
    if memory_module.MEMORY_FILE.exists():
        shutil.copy(memory_module.MEMORY_FILE, tmp / "memoire.json")
    memory_module.MEMORY_FILE = tmp / "memoire.json"
    costs.COSTS_FILE = tmp / "couts.json"


def send_scores(trace_id: str | None, result: ev.CaseResult, run: str) -> None:
    client = get_client()
    if not client or not trace_id:
        return
    try:
        for name, ok in result.checks.items():
            client.create_score(name=f"eval_{name}", value=float(ok), trace_id=trace_id, comment=run)
        for name, value in result.juge.items():
            if value:
                client.create_score(name=f"eval_juge_{name}", value=value, trace_id=trace_id,
                                    comment=result.commentaire or run)
        client.flush()
    except Exception:
        print("   (Langfuse : scores non envoyés)")


async def run_case(case, settings, my_ratings, seen_ids, judge_model, run) -> ev.CaseResult:
    registry, mem = SessionRegistry(), memory_module.Memory()
    answer = await recommend(case["demande"], settings, registry, memory=mem)
    cost, turns, asked = answer.cost_usd or 0.0, answer.turns, False
    if answer.kind == "question" and case.get("controles", {}).get("question") is not True:
        print(f"   question inattendue : « {answer.message} » → on répond « {DEFAULT_REPLY} »")
        question, asked = answer.message, True
        answer = await recommend(DEFAULT_REPLY, settings, registry, answer.session_id, memory=mem)
        cost, turns = cost + (answer.cost_usd or 0.0), turns + answer.turns
        answer.message = f"(après la question « {question} ») {answer.message}".strip()
    answer.cost_usd = cost  # pour le contrôle du plafond : les deux échanges comptent

    my_titles = [r["titre"] for r in my_ratings if r.get("titre")]
    checks = ev.run_checks(case, answer, seen_ids, my_titles, settings.max_budget_usd)
    if asked and "pas_de_question_inutile" in checks:
        checks["pas_de_question_inutile"] = False

    verdict = ev.Verdict(commentaire="pas de juge : l'agent a échoué")
    if answer.kind != "error":
        verdict = await ev.judge(case, answer, my_ratings, judge_model, settings.anthropic_api_key)
        costs.CostLog().add(verdict.cost_usd)

    result = ev.CaseResult(
        id=case["id"], demande=case["demande"], kind=answer.kind,
        films=[f"{f.role_label} : {f.details.get('title')} ({f.details.get('year')})" for f in answer.films],
        checks=checks, juge=verdict.scores, commentaire=verdict.commentaire,
        cost_usd=round(cost + verdict.cost_usd, 4), tours=turns, trace_id=answer.trace_id)
    send_scores(answer.trace_id, result, run)
    return result


async def main_run(args) -> None:
    settings = get_settings()
    if args.modele:
        settings = replace(settings, claude_model=args.modele)
    budget = args.budget or float(os.getenv("EVAL_BUDGET_USD", "1.50").replace(",", "."))
    # Toujours le même juge, quel que soit le modèle testé : sinon les notes ne sont pas comparables.
    judge_model = args.juge or os.getenv("EVAL_JUDGE_MODEL") or DEFAULT_JUDGE
    # Dans recommend(), le « budget du jour » sert ici de plafond de l'évaluation (compteur isolé).
    settings = replace(settings, daily_budget_usd=budget)
    cases = ev.load_cases(args.cas.split(",") if args.cas else None)

    store = RatingsStore(settings.pinecone_api_key, settings.pinecone_index)
    my_ratings = store.list_all()
    seen_ids = {r["tmdb_id"] for r in my_ratings if r.get("tmdb_id")} | {
        int(r["id"].split("-", 1)[1]) for r in my_ratings if r["id"].startswith("tmdb-")}

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    run = f"eval {stamp} {settings.claude_model}"
    print(f"🎬 {len(cases)} demandes · modèle {settings.claude_model} · juge {judge_model} · "
          f"plafond {budget:.2f} $\n")

    with tempfile.TemporaryDirectory() as tmp:
        isolate(Path(tmp))
        mem = memory_module.Memory()
        for status in (*memory_module.SEEN_STATUSES, "pas_envie"):
            seen_ids |= {tmdb_id for tmdb_id, _ in mem.films_with(status)}

        results: list[ev.CaseResult] = []
        for i, case in enumerate(cases, 1):
            spent = costs.CostLog().today()
            if spent >= budget:
                print(f"💶 Plafond atteint ({spent:.2f} $) : arrêt avant « {case['id']} ».")
                break
            print(f"[{i}/{len(cases)}] {case['id']} : {case['demande']}")
            result = await run_case(case, settings, my_ratings, seen_ids, judge_model, run)
            results.append(result)
            failed = [k for k, ok in result.checks.items() if not ok]
            mean = f"{result.judge_mean:.1f}/5" if result.judge_mean is not None else "—"
            print(f"   {result.checks_ok}/{len(result.checks)} contrôles · juge {mean} · "
                  f"{result.cost_usd:.3f} $ · {result.tours} tours" + (f" · raté : {', '.join(failed)}" if failed else ""))

    if not results:
        print("Aucune demande évaluée.")
        return
    data = ev.to_json(results, {"date": stamp, "modele": settings.claude_model, "juge": judge_model,
                                "cas": [r.id for r in results]})
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    base = RESULTS_DIR / f"{stamp}_{settings.claude_model}"
    base.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ev.markdown_report(data)
    base.with_suffix(".md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Rapport : {base.with_suffix('.md').relative_to(PROJECT_DIR)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Évaluer l'agent sur des demandes types.")
    parser.add_argument("--cas", help="identifiants séparés par des virgules (voir evals/cas.json)")
    parser.add_argument("--modele", help="modèle de l'agent (défaut : CLAUDE_MODEL de .env)")
    parser.add_argument("--juge", help="modèle du juge (défaut : EVAL_JUDGE_MODEL ou claude-sonnet-5-5)")
    parser.add_argument("--budget", type=float, help="plafond de dépense en $ (défaut : EVAL_BUDGET_USD ou 1.50)")
    parser.add_argument("--comparer", nargs=2, metavar=("AVANT.json", "APRES.json"),
                        help="comparer deux rapports, sans rien relancer (gratuit)")
    args = parser.parse_args()
    if args.comparer:
        a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.comparer)
        print(ev.compare(a, b))
        return
    try:
        asyncio.run(main_run(args))
    except (ConfigError, ValueError) as exc:
        sys.exit(f"❌ {exc}")


if __name__ == "__main__":
    main()
