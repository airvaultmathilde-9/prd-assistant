"""Phase 1 : essaie les outils TMDB en vrai, sans LLM.

Lancement (depuis film-agent/) :
    python scripts/demo_tmdb.py                  # scénario de démonstration
    python scripts/demo_tmdb.py "Drive"          # avec un titre de ton choix

Tu vois exactement ce que l'agent verra quand il appellera ces outils.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_settings  # noqa: E402
from tmdb_client import TMDBClient, TMDBError  # noqa: E402


def show(title: str, data) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "Le Fabuleux Destin d'Amélie Poulain"
    client = TMDBClient(get_settings().tmdb_api_key)
    try:
        results = client.search_movies(query, limit=3)
        show(f"search_movies({query!r})", results)
        if not results:
            return 0
        movie_id = results[0]["tmdb_id"]
        show(f"get_movie_details({movie_id})", client.get_movie_details(movie_id))
        show(f"get_watch_providers({movie_id})", client.get_watch_providers(movie_id))
        show("Mes plateformes trouvées par TMDB", client.subscription_provider_ids())
        show("discover_movies : comédies françaises 2015+ bien notées, sur mes abonnements",
             client.discover_movies(genre_ids=[35], original_language="fr", year_from=2015,
                                    min_vote_average=7, on_my_subscriptions=True, limit=5))
        show("search_person('Céline Sciamma')", client.search_person("Céline Sciamma", limit=2))
    except TMDBError as exc:
        print(f"❌ {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
