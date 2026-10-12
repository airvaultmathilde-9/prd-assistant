"""Phase 0 : vérifie que les trois services répondent avec tes clés.

Lancement (depuis film-agent/) :  python scripts/check_setup.py

Chaque test est gratuit ou quasi gratuit :
- Anthropic : on demande la fiche du modèle (aucun token consommé).
- Pinecone  : on liste les index existants.
- TMDB      : on cherche un film, en français, pour la France.

Règle de sécurité : on n'affiche JAMAIS le message brut d'une exception HTTP,
car pour TMDB v3 la clé fait partie de l'URL, et l'URL apparaît dans l'erreur.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import TMDB_LANGUAGE, TMDB_REGION, ConfigError, get_settings, mask  # noqa: E402
from tmdb_client import tmdb_auth  # noqa: E402

TIMEOUT = 15.0


class CheckFailed(Exception):
    """Échec dont NOUS écrivons le message : on peut l'afficher sans risque."""


def check_anthropic(api_key: str, model: str) -> str:
    response = httpx.get(
        f"https://api.anthropic.com/v1/models/{model}",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        timeout=TIMEOUT,
    )
    if response.status_code == 401:
        raise CheckFailed("clé refusée (401)")
    if response.status_code == 404:
        raise CheckFailed(f"modèle « {model} » inconnu : vérifie CLAUDE_MODEL")
    response.raise_for_status()
    return f"modèle {response.json().get('display_name', model)} accessible"


def check_pinecone(api_key: str, index_name: str) -> str:
    from pinecone import Pinecone

    names = [idx.name for idx in Pinecone(api_key=api_key).list_indexes()]
    status = "existe déjà" if index_name in names else "sera créé en phase 2"
    return f"{len(names)} index trouvé(s) ; l'index « {index_name} » {status}"


def check_tmdb(api_key: str) -> str:
    headers, params = tmdb_auth(api_key)
    params |= {"query": "Le Fabuleux Destin d'Amélie Poulain",
               "language": TMDB_LANGUAGE, "region": TMDB_REGION}
    response = httpx.get("https://api.themoviedb.org/3/search/movie",
                         headers=headers, params=params, timeout=TIMEOUT)
    if response.status_code == 401:
        raise CheckFailed("clé refusée (401)")
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return "API joignable, mais aucun résultat pour le film test"
    first = results[0]
    return f"OK, 1er résultat : « {first['title']} » ({first.get('release_date', '?')[:4]})"


def main() -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"❌ Configuration : {exc}")
        return 1

    print("Clés chargées :",
          f"Anthropic {mask(settings.anthropic_api_key)},",
          f"Pinecone {mask(settings.pinecone_api_key)},",
          f"TMDB {mask(settings.tmdb_api_key)}\n")

    checks = [
        ("Anthropic", lambda: check_anthropic(settings.anthropic_api_key, settings.claude_model)),
        ("Pinecone", lambda: check_pinecone(settings.pinecone_api_key, settings.pinecone_index)),
        ("TMDB", lambda: check_tmdb(settings.tmdb_api_key)),
    ]
    failures = 0
    for name, check in checks:
        try:
            print(f"✅ {name} : {check()}")
        except httpx.HTTPStatusError as exc:
            failures += 1
            print(f"❌ {name} : erreur HTTP {exc.response.status_code}")
        except httpx.HTTPError as exc:
            failures += 1
            print(f"❌ {name} : problème réseau ({type(exc).__name__})")
        except Exception as exc:  # on n'affiche que nos propres messages
            failures += 1
            detail = str(exc) if isinstance(exc, CheckFailed) else type(exc).__name__
            print(f"❌ {name} : {detail}")

    print("\nTout est prêt pour la phase 1." if not failures else f"\n{failures} service(s) à corriger.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
