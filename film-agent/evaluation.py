"""Phase 7 : évaluer l'agent sur des demandes types (evals).

Deux sortes de notes pour chaque demande :
- des CONTRÔLES automatiques, écrits en Python : vrais ou faux, sans ambiguïté
  (3 films ? déjà vus ? moins de 2 h ? disponibles chez moi ? justifications qui citent mes films ?) ;
- l'avis d'un JUGE : un second appel à Claude, qui note de 1 à 5 ce que le code ne sait pas
  juger (respect de l'envie, qualité des justifications, spoilers, variété des 3 films).

Le script scripts/eval.py lance les demandes, appelle ce module, et écrit un rapport.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from config import PROJECT_DIR

CASES_FILE = PROJECT_DIR / "evals" / "cas.json"
AT_HOME = ("abonnement", "gratuit", "location")  # « achat » n'est accepté que pour le pari
CRITERIA = ["respect_demande", "justifications", "variete", "sans_spoiler", "ecriture"]


def load_cases(ids: list[str] | None = None) -> list[dict]:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    if ids:
        unknown = set(ids) - {c["id"] for c in cases}
        if unknown:
            raise ValueError(f"cas inconnus : {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c["id"] in ids]
    return cases


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _mentions(text: str, title: str) -> bool:
    t = _norm(title)
    return len(t) >= 3 and f" {t} " in f" {_norm(text)} "


# ---------- Contrôles automatiques ----------

def run_checks(case: dict, answer, seen_ids: set[int], my_titles: list[str],
               max_cost: float) -> dict[str, bool]:
    """Chaque contrôle vaut True (réussi) ou False (raté). Absent = ne s'applique pas."""
    rules = case.get("controles", {})
    films = answer.films
    checks: dict[str, bool] = {"pas_d_echec": answer.kind != "error",
                               "cout_sous_le_plafond": (answer.cost_usd or 0) <= max_cost}
    if rules.get("question") is True:
        checks["pose_une_question"] = answer.kind == "question"
        return checks
    if rules.get("question") is False:
        checks["pas_de_question_inutile"] = answer.kind != "question"
    if answer.kind != "recommendations":
        return checks

    checks["assez_de_films"] = len(films) >= rules.get("min_films", 3)
    checks["aucun_film_invente"] = not answer.rejected
    checks["aucun_deja_vu"] = all(f.tmdb_id not in seen_ids for f in films)
    checks["roles_differents"] = len({f.role for f in films}) == len(films)

    def access(f) -> str | None:
        options = f.watch.get("options") or []
        return options[0]["access"] if options else None
    checks["dispo_chez_moi"] = all(access(f) in AT_HOME or (f.role == "pari" and access(f) == "achat")
                                   for f in films)
    checks["justif_cite_mes_films"] = all(any(_mentions(f.why, t) for t in my_titles) for f in films)

    if "duree_max" in rules:
        checks["duree_respectee"] = all((f.details.get("runtime_min") or 999) <= rules["duree_max"] for f in films)
    if "personne" in rules:
        who = _norm(rules["personne"])
        checks["bonne_personne"] = all(
            who in {_norm(p) for p in (f.details.get("cast") or []) + (f.details.get("directors") or [])}
            for f in films)
    if "langue" in rules:
        checks["bonne_langue"] = all(f.details.get("original_language") == rules["langue"] for f in films)
    if "annees" in rules:
        low, high = rules["annees"]
        checks["bonnes_annees"] = all(low <= (f.details.get("year") or 0) <= high for f in films)
    if "plateforme" in rules:
        wanted = _norm(rules["plateforme"])
        checks["bonne_plateforme"] = all(
            any(_norm(o["platform"]).startswith(wanted) and o["access"] == "abonnement"
                for o in f.watch.get("options") or [])
            for f in films)
    return checks


# ---------- Le juge (un second appel à Claude) ----------

JUDGE_PROMPT = """Tu es un évaluateur exigeant et impartial d'un agent qui recommande des films à Mathilde.
On te donne : sa demande, ce qui était attendu, la liste des films qu'elle a notés (sur 5), et la réponse
de l'agent (3 films, chacun avec un rôle « choix sûr / découverte / pari », un « pourquoi » et une
« ambiance »). Le résumé TMDB de chaque film t'est fourni uniquement pour repérer les spoilers.

Note chaque critère de 1 (très mauvais) à 5 (excellent) :
- respect_demande : les films correspondent-ils vraiment à l'envie exprimée ?
- justifications : le « pourquoi » s'appuie-t-il sur des films qu'elle a VRAIMENT notés, de façon
  précise et convaincante (pas une liste plaquée) ?
- variete : les 3 rôles sont-ils tenus (un choix sûr, une vraie découverte, un vrai pari) ?
- sans_spoiler : 5 = aucune révélation d'intrigue au-delà du point de départ ; 1 = fin ou rebondissement révélé.
- ecriture : textes courts, vivants, en bon français.
Si l'agent a posé une question au lieu de recommander, note seulement respect_demande (la question
est-elle pertinente et utile ?) et mets 0 aux autres critères.
Commentaire : 2 phrases maximum, le défaut principal d'abord."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {**{c: {"type": "integer", "minimum": 0, "maximum": 5} for c in CRITERIA},
                   "commentaire": {"type": "string"}},
    "required": [*CRITERIA, "commentaire"],
}


def judge_input(case: dict, answer, my_ratings: list[dict]) -> str:
    notes = "\n".join(f"- {r['titre']} : {r['note']:g}/5" for r in my_ratings)
    if answer.kind == "question":
        reply = f"QUESTION posée par l'agent : {answer.message}"
    else:
        reply = "\n\n".join(
            f"[{f.role_label}] {f.details.get('title')} ({f.details.get('year')}), "
            f"{f.details.get('runtime_min')} min\nPourquoi : {f.why}\nAmbiance : {f.vibe}\n"
            f"(Résumé TMDB, pour les spoilers : {(f.details.get('overview') or '')[:500]})"
            for f in answer.films) or f"Aucun film. Message : {answer.message}"
    return (f"# Demande\n{case['demande']}\n\n# Attendu\n{case['attendu']}\n\n"
            f"# Films notés par Mathilde\n{notes}\n\n# Réponse de l'agent\n{reply}")


@dataclass
class Verdict:
    scores: dict[str, int] = field(default_factory=dict)
    commentaire: str = ""
    cost_usd: float = 0.0


async def judge(case: dict, answer, my_ratings: list[dict], model: str, api_key: str) -> Verdict:
    options = ClaudeAgentOptions(
        model=model, system_prompt=JUDGE_PROMPT, tools=[], setting_sources=[],
        max_turns=3, max_budget_usd=0.10,
        output_format={"type": "json_schema", "schema": JUDGE_SCHEMA},
        env={"ANTHROPIC_API_KEY": api_key})
    verdict = Verdict()
    async for message in query(prompt=judge_input(case, answer, my_ratings), options=options):
        if isinstance(message, ResultMessage):
            verdict.cost_usd = message.total_cost_usd or 0.0
            out = message.structured_output
            if isinstance(out, dict):
                verdict.scores = {c: int(out.get(c, 0)) for c in CRITERIA}
                verdict.commentaire = out.get("commentaire", "")
            else:
                verdict.commentaire = "juge indisponible (pas de réponse structurée)"
    return verdict


# ---------- Résultats et rapport ----------

@dataclass
class CaseResult:
    id: str
    demande: str
    kind: str
    films: list[str]
    checks: dict[str, bool]
    juge: dict[str, int]
    commentaire: str
    cost_usd: float
    tours: int
    trace_id: str | None = None

    @property
    def checks_ok(self) -> int:
        return sum(self.checks.values())

    @property
    def judge_mean(self) -> float | None:
        values = [v for v in self.juge.values() if v]
        return sum(values) / len(values) if values else None


def summary(results: list[CaseResult]) -> dict:
    checks = [ok for r in results for ok in r.checks.values()]
    means = [r.judge_mean for r in results if r.judge_mean is not None]
    per_criterion = {c: [r.juge[c] for r in results if r.juge.get(c)] for c in CRITERIA}
    return {
        "cas": len(results),
        "controles_reussis": f"{sum(checks)}/{len(checks)}",
        "taux_controles": round(sum(checks) / len(checks), 3) if checks else None,
        "note_juge_moyenne": round(sum(means) / len(means), 2) if means else None,
        "par_critere": {c: round(sum(v) / len(v), 2) for c, v in per_criterion.items() if v},
        "cout_total_usd": round(sum(r.cost_usd for r in results), 3),
        "tours_moyens": round(sum(r.tours for r in results) / len(results), 1) if results else None,
    }


def to_json(results: list[CaseResult], meta: dict) -> dict:
    return {"meta": meta, "resume": summary(results), "cas": [asdict(r) for r in results]}


def markdown_report(data: dict) -> str:
    meta, s = data["meta"], data["resume"]
    lines = [f"# Évaluation du {meta['date']} : {meta['modele']}", "",
             f"- Contrôles automatiques réussis : **{s['controles_reussis']}**",
             f"- Note moyenne du juge : **{s['note_juge_moyenne']}/5** ({meta['juge']})",
             f"- Coût total : {s['cout_total_usd']} $ · tours moyens : {s['tours_moyens']}", "",
             "| Cas | Contrôles | Juge | Coût | Tours | Contrôles ratés | Commentaire du juge |",
             "|---|---|---|---|---|---|---|"]
    for r in data["cas"]:
        failed = ", ".join(k for k, ok in r["checks"].items() if not ok) or "—"
        values = [v for v in r["juge"].values() if v]
        mean = f"{sum(values) / len(values):.1f}" if values else "—"
        lines.append(f"| {r['id']} | {sum(r['checks'].values())}/{len(r['checks'])} | {mean} | "
                     f"{r['cost_usd']:.3f} $ | {r['tours']} | {failed} | {r['commentaire'].replace('|', '/')} |")
    if s["par_critere"]:
        lines += ["", "Par critère du juge : " + " · ".join(f"{c} {v}" for c, v in s["par_critere"].items())]
    return "\n".join(lines) + "\n"


def compare(a: dict, b: dict) -> str:
    """Deux rapports côte à côte : qu'est-ce qui s'est amélioré ou dégradé ?"""
    sa, sb = a["resume"], b["resume"]
    lines = [f"| | {a['meta']['modele']} ({a['meta']['date']}) | {b['meta']['modele']} ({b['meta']['date']}) |",
             "|---|---|---|"]
    for key, label in (("controles_reussis", "Contrôles réussis"), ("note_juge_moyenne", "Note du juge"),
                       ("cout_total_usd", "Coût total ($)"), ("tours_moyens", "Tours moyens")):
        lines.append(f"| {label} | {sa[key]} | {sb[key]} |")
    for c in CRITERIA:
        lines.append(f"| juge : {c} | {sa['par_critere'].get(c, '—')} | {sb['par_critere'].get(c, '—')} |")
    by_id = {r["id"]: r for r in b["cas"]}
    lines += ["", "| Cas | Juge avant → après | Contrôles avant → après |", "|---|---|---|"]
    for r in a["cas"]:
        other = by_id.get(r["id"])
        if not other:
            continue

        def mean(x):
            v = [n for n in x["juge"].values() if n]
            return f"{sum(v) / len(v):.1f}" if v else "—"
        lines.append(f"| {r['id']} | {mean(r)} → {mean(other)} | "
                     f"{sum(r['checks'].values())}/{len(r['checks'])} → "
                     f"{sum(other['checks'].values())}/{len(other['checks'])} |")
    return "\n".join(lines) + "\n"
