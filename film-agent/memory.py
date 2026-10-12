"""Phase 4 : la mémoire de l'agent (préférences durables + retours sur les films).

Stockée dans data/memory/memoire.json : un simple fichier lisible, sur ta machine,
ignoré par git. Deux sortes de souvenirs :
- les PRÉFÉRENCES : des phrases durables (« je préfère la VO sous-titrée ») ;
- les RETOURS sur des films : vu et aimé / pas envie / plus tard.

Comment l'agent s'en sert : la mémoire est ajoutée au prompt système au début
de chaque demande (il la « connaît » donc sans avoir à la chercher), et des outils
lui permettent de la compléter quand tu exprimes une préférence dans la conversation.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config import PROJECT_DIR

MEMORY_FILE = PROJECT_DIR / "data" / "memory" / "memoire.json"

STATUSES = {
    "vu_aime": "✅ Vu et aimé",
    "pas_envie": "🙅 Pas envie",
    "plus_tard": "🕒 Plus tard",
}


class Memory:
    def __init__(self, path: Path | None = None):
        self.path = path or MEMORY_FILE  # lu à l'appel : les tests peuvent le rediriger
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.preferences: list[dict] = data.get("preferences", [])
        # Clés en texte : JSON n'accepte pas les nombres comme clés.
        self.feedback: dict[str, dict] = data.get("retours", {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")  # écrire à côté puis remplacer : jamais de fichier à moitié écrit
        tmp.write_text(json.dumps({"preferences": self.preferences, "retours": self.feedback},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- Préférences ----------

    def add_preference(self, text: str) -> dict:
        text = text.strip()
        for pref in self.preferences:  # pas de doublon exact
            if pref["texte"].lower() == text.lower():
                return pref
        pref = {"id": max((p["id"] for p in self.preferences), default=0) + 1,
                "texte": text, "date": date.today().isoformat()}
        self.preferences.append(pref)
        self.save()
        return pref

    def remove_preference(self, pref_id: int) -> bool:
        before = len(self.preferences)
        self.preferences = [p for p in self.preferences if p["id"] != pref_id]
        self.save()
        return len(self.preferences) < before

    # ---------- Retours sur les films ----------

    def set_feedback(self, tmdb_id: int, title: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"statut inconnu : {status} (attendus : {', '.join(STATUSES)})")
        self.feedback[str(tmdb_id)] = {"titre": title, "statut": status, "date": date.today().isoformat()}
        self.save()

    def clear_feedback(self, tmdb_id: int) -> None:
        self.feedback.pop(str(tmdb_id), None)
        self.save()

    def status_of(self, tmdb_id: int) -> str | None:
        entry = self.feedback.get(str(tmdb_id))
        return entry["statut"] if entry else None

    def films_with(self, status: str) -> list[tuple[int, str]]:
        return [(int(i), e["titre"]) for i, e in self.feedback.items() if e["statut"] == status]

    # ---------- Pour le prompt système ----------

    def as_prompt(self) -> str:
        lines = ["# Mémoire : ce que Mathilde t'a appris", ""]
        lines.append("## Préférences durables")
        if self.preferences:
            lines += [f"- [{p['id']}] {p['texte']}" for p in self.preferences]
        else:
            lines.append("- (aucune pour l'instant)")
        for status, label in STATUSES.items():
            films = self.films_with(status)
            if films:
                lines += ["", f"## {label}"]
                lines += [f"- {title} (tmdb_id {tmdb_id})" for tmdb_id, title in films]
        lines += ["", "Règles : ne recommande JAMAIS un film « Vu et aimé » ni « Pas envie ». "
                  "Un film « Plus tard » peut être reproposé s'il correspond à la demande : "
                  "dis-lui qu'elle l'avait mis de côté. Respecte toujours les préférences durables."]
        return "\n".join(lines)
