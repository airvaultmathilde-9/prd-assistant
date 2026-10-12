"""Phase 2 : importe mon CSV de notes dans Pinecone.

Lancement (depuis film-agent/) :
    python scripts/import_notes.py data/mes_notes.csv --dry-run   # essai : rien n'est envoyé
    python scripts/import_notes.py data/mes_notes.csv             # import réel

Le script crée/maintient data/correspondances_tmdb.json : pour chaque film du CSV,
l'identifiant TMDB retenu. Tu peux le corriger à la main :
    - remplacer "tmdb_id": null par le bon identifiant (lu dans l'adresse themoviedb.org/movie/12345) ;
    - supprimer une entrée pour que le script la recherche à nouveau.
Les entrées existantes sont réutilisées telles quelles : relancer l'import est rapide.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import PROJECT_DIR, get_settings  # noqa: E402
from ratings_csv import Match, build_record, match_rating, read_ratings  # noqa: E402
from ratings_store import RatingsStore  # noqa: E402
from tmdb_client import TMDBClient, TMDBError  # noqa: E402

MATCHES_FILE = PROJECT_DIR / "data" / "correspondances_tmdb.json"
ICONS = {"sûr": "✅", "probable": "🟡", "à vérifier": "⚠️ ", "introuvable": "❌", "manuel": "✏️ "}


def load_matches() -> dict:
    return json.loads(MATCHES_FILE.read_text(encoding="utf-8")) if MATCHES_FILE.exists() else {}


def save_matches(matches: dict) -> None:
    MATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MATCHES_FILE.write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Importe mes notes de films dans Pinecone.")
    parser.add_argument("csv", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="tout préparer sans rien envoyer à Pinecone")
    args = parser.parse_args()

    settings = get_settings()
    ratings, errors = read_ratings(args.csv)
    for error in errors:
        print(f"⚠️  {error}")
    if not ratings:
        print("Aucune note lisible : rien à importer.")
        return 1
    print(f"{len(ratings)} films lus dans {args.csv.name}\n")

    tmdb = TMDBClient(settings.tmdb_api_key)
    matches = load_matches()
    records: dict[str, dict] = {}
    counts: dict[str, int] = {}

    for rating in ratings:
        saved = matches.get(rating.key)
        if saved is not None:
            # Entrée existante : on respecte l'identifiant enregistré (éventuellement corrigé à la main).
            tmdb_id = saved.get("tmdb_id")
            confidence = saved.get("confiance", "manuel")
            if tmdb_id and confidence in ("à vérifier", "introuvable"):
                confidence = "manuel"  # identifiant ajouté à la main
        else:
            try:
                match = match_rating(tmdb, rating)
            except TMDBError as exc:
                print(f"❌ {rating.key} : {exc}")
                continue
            tmdb_id, confidence = match.tmdb_id, match.confidence
            matches[rating.key] = _match_entry(match)

        details = None
        if tmdb_id:
            try:
                details = tmdb.get_movie_details(tmdb_id)
            except TMDBError as exc:
                print(f"⚠️  {rating.key} : détails TMDB indisponibles ({exc})")

        counts[confidence] = counts.get(confidence, 0) + 1
        tmdb_label = f"-> {details['title']} ({details['year']})" if details else ""
        print(f"{ICONS.get(confidence, '•')} {rating.key} {tmdb_label}")

        record = build_record(rating, tmdb_id, details)
        if record["_id"] in records:
            print(f"   ↳ doublon de « {records[record['_id']]['titre']} » : la dernière ligne l'emporte")
        records[record["_id"]] = record

    save_matches(matches)
    to_check = {k: v for k, v in matches.items() if not v.get("tmdb_id")}
    print("\nBilan :", ", ".join(f"{ICONS.get(k, '')} {k} : {v}" for k, v in counts.items()))
    if to_check:
        print(f"\n{len(to_check)} film(s) sans identifiant TMDB : ils seront importés quand même,")
        print(f"mais l'agent ne pourra pas les relier au catalogue. À corriger dans {MATCHES_FILE.name} :")
        for key, entry in to_check.items():
            print(f"  - {key}  candidats : {'; '.join(entry.get('candidats', [])) or 'aucun'}")

    if args.dry_run:
        print("\n--dry-run : rien n'a été envoyé. Exemple de texte qui sera vectorisé :\n")
        print(next(iter(records.values()))["chunk_text"])
        return 0

    store = RatingsStore(settings.pinecone_api_key, settings.pinecone_index)
    if store.ensure_index():
        print(f"\nIndex « {settings.pinecone_index} » créé (AWS us-east-1, multilingual-e5-large).")
    sent = store.upsert(list(records.values()))
    print(f"\n✅ {sent} films envoyés à Pinecone (index « {settings.pinecone_index} »).")
    print("Ils deviennent interrogeables après quelques secondes : python scripts/demo_rag.py")
    return 0


def _match_entry(match: Match) -> dict:
    return {
        "tmdb_id": match.tmdb_id,
        "confiance": match.confidence,
        "titre_tmdb": match.tmdb_title,
        "annee_tmdb": match.tmdb_year,
        "candidats": list(match.candidates),
    }


if __name__ == "__main__":
    sys.exit(main())
