"""Phase 2 : interroge mes notes dans Pinecone, comme le fera l'agent.

Lancement (depuis film-agent/) :
    python scripts/demo_rag.py                               # requêtes d'exemple
    python scripts/demo_rag.py "un film qui fait réfléchir"  # ta propre requête
    python scripts/demo_rag.py "comédie" --min-note 4        # seulement ce que j'ai aimé
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_settings  # noqa: E402
from ratings_store import RatingsStore  # noqa: E402

EXAMPLES = [
    ("quelque chose de léger et drôle", None),
    ("humour absurde et décalé", None),
    ("un film visuellement époustouflant", None),
    ("une actrice bouleversante dans un portrait de femme", None),
    ("grand spectacle épique", 4),
    ("film trop long ou prévisible", None),
]


def show(store: RatingsStore, query: str, min_note: float | None) -> None:
    label = f" (note ≥ {min_note:g})" if min_note else ""
    print(f"\n🔎 « {query} »{label}")
    for hit in store.search(query, top_k=4, min_note=min_note):
        print(f"   {hit['score']:.3f}  {hit['titre']} ({hit.get('annee_sortie', '?')}) "
              f"{hit['note']:g}/5 : {hit.get('commentaire', '')[:70]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?")
    parser.add_argument("--min-note", type=float)
    args = parser.parse_args()

    settings = get_settings()
    store = RatingsStore(settings.pinecone_api_key, settings.pinecone_index)
    print(f"{store.count()} films dans l'index « {settings.pinecone_index} »")

    for query, min_note in ([(args.query, args.min_note)] if args.query else EXAMPLES):
        show(store, query, min_note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
