"""Tests du client TMDB, SANS réseau.

On remplace le vrai transport HTTP par une fonction qui joue le rôle de TMDB.
Avantages : tests instantanés, gratuits, reproductibles, et on peut vérifier
exactement ce que notre code ENVOIE (paramètres, langue, région).
"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tmdb_client import BASE_URL, TMDBClient, TMDBError  # noqa: E402

FAKE_KEY = "cle-v3-secrete-123"

GENRES = {"genres": [{"id": 35, "name": "Comédie"}, {"id": 18, "name": "Drame"}]}
PROVIDERS_FR = {"results": [
    {"provider_id": 8, "provider_name": "Netflix"},
    {"provider_id": 1796, "provider_name": "Netflix Standard with Ads"},
    {"provider_id": 381, "provider_name": "Canal+"},
    {"provider_id": 337, "provider_name": "Disney Plus"},
]}
AMELIE = {
    "id": 194, "title": "Le Fabuleux Destin d'Amélie Poulain",
    "original_title": "Le Fabuleux Destin d'Amélie Poulain", "release_date": "2001-04-25",
    "original_language": "fr", "genre_ids": [35], "vote_average": 7.86, "vote_count": 11000,
    "overview": "Amélie, une jeune serveuse dans un bar de Montmartre…", "poster_path": "/amelie.jpg",
}


def make_client(routes: dict, calls: list | None = None) -> TMDBClient:
    """Construit un client dont « TMDB » répond selon le dictionnaire `routes`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        path = request.url.path.removeprefix("/3")
        if path not in routes:
            return httpx.Response(404)
        status, body = routes[path]
        return httpx.Response(status, json=body)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return TMDBClient(FAKE_KEY, http=http)


def test_v3_key_goes_in_url_and_v4_token_in_header():
    calls = []
    make_client({"/genre/movie/list": (200, GENRES)}, calls).genres()
    assert calls[0].url.params["api_key"] == FAKE_KEY

    calls = []
    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(
        lambda r: (calls.append(r), httpx.Response(200, json=GENRES))[1]))
    TMDBClient("eyJ-jeton-v4", http=http).genres()
    assert calls[0].headers["Authorization"] == "Bearer eyJ-jeton-v4"
    assert "api_key" not in calls[0].url.params


def test_search_sends_french_settings_and_returns_compact_summaries():
    calls = []
    client = make_client({"/genre/movie/list": (200, GENRES),
                          "/search/movie": (200, {"results": [AMELIE]})}, calls)
    results = client.search_movies("Amélie")

    search = next(c for c in calls if c.url.path.endswith("/search/movie"))
    assert search.url.params["language"] == "fr-FR"
    assert search.url.params["region"] == "FR"
    assert results == [{
        "tmdb_id": 194, "title": "Le Fabuleux Destin d'Amélie Poulain",
        "original_title": "Le Fabuleux Destin d'Amélie Poulain", "year": 2001,
        "original_language": "fr", "genres": ["Comédie"], "vote_average": 7.9,
        "vote_count": 11000, "overview": "Amélie, une jeune serveuse dans un bar de Montmartre…",
        "poster_url": "https://image.tmdb.org/t/p/w342/amelie.jpg",
    }]


def test_discover_on_my_subscriptions_filters_by_netflix_and_canal_plus_only():
    calls = []
    client = make_client({"/genre/movie/list": (200, GENRES),
                          "/watch/providers/movie": (200, PROVIDERS_FR),
                          "/discover/movie": (200, {"results": [AMELIE]})}, calls)
    client.discover_movies(genre_ids=[35, 18], year_from=2000, on_my_subscriptions=True)

    params = next(c for c in calls if c.url.path.endswith("/discover/movie")).url.params
    assert set(params["with_watch_providers"].split("|")) == {"8", "1796", "381"}  # pas Disney
    assert params["with_watch_monetization_types"] == "flatrate"
    assert params["watch_region"] == "FR"
    assert params["with_genres"] == "35,18"
    assert params["primary_release_date.gte"] == "2000-01-01"
    assert "primary_release_date.lte" not in params  # les critères absents ne sont pas envoyés


def test_watch_providers_separates_my_subscriptions_from_the_rest():
    client = make_client({
        "/watch/providers/movie": (200, PROVIDERS_FR),
        "/movie/194/watch/providers": (200, {"results": {"FR": {
            "link": "https://www.themoviedb.org/movie/194/watch?locale=FR",
            "flatrate": [{"provider_id": 381, "provider_name": "Canal+"},
                         {"provider_id": 337, "provider_name": "Disney Plus"}],
            "rent": [{"provider_id": 2, "provider_name": "Apple TV"}],
        }}}),
    })
    result = client.get_watch_providers(194)
    assert result["on_my_subscriptions"] == ["Canal+"]
    assert result["other_streaming"] == ["Disney Plus"]
    assert result["rent"] == ["Apple TV"]
    assert result["source"] == "JustWatch"


def test_watch_providers_when_not_available_in_france():
    client = make_client({"/movie/194/watch/providers": (200, {"results": {"US": {}}})})
    assert client.get_watch_providers(194)["available_in_france"] is False


def test_details_extracts_directors_and_top_cast():
    client = make_client({"/movie/194": (200, {
        **AMELIE, "runtime": 122, "genres": [{"id": 35, "name": "Comédie"}],
        "spoken_languages": [{"iso_639_1": "fr"}],
        "credits": {"crew": [{"name": "Jean-Pierre Jeunet", "job": "Director"},
                             {"name": "Yann Tiersen", "job": "Original Music Composer"}],
                    "cast": [{"name": f"Acteur {i}"} for i in range(10)]},
        "keywords": {"keywords": [{"id": 1, "name": "paris"}]},
    })})
    details = client.get_movie_details(194)
    assert details["directors"] == ["Jean-Pierre Jeunet"]
    assert len(details["cast"]) == 5
    assert details["runtime_min"] == 122
    assert details["keywords"] == ["paris"]


@pytest.mark.parametrize("status, expected", [
    (401, "clé TMDB refusée"), (429, "trop de requêtes"), (500, "HTTP 500"),
])
def test_errors_are_readable_and_never_leak_the_key(status, expected):
    client = make_client({"/search/movie": (status, {})})
    with pytest.raises(TMDBError) as info:
        client.search_movies("x")
    assert expected in str(info.value)
    assert FAKE_KEY not in str(info.value)


def test_network_error_does_not_chain_the_url_containing_the_key():
    def boom(request):
        raise httpx.ConnectError(f"impossible de joindre {request.url}")
    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(boom))
    with pytest.raises(TMDBError) as info:
        TMDBClient(FAKE_KEY, http=http).search_movies("x")
    assert FAKE_KEY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


FILMO = {
    "cast": [
        {"id": 1, "title": "La Vie d'Adèle", "release_date": "2013-10-09", "order": 0,
         "character": "Adèle", "genre_ids": [18], "vote_average": 7.6, "vote_count": 3000},
        {"id": 2, "title": "Petit rôle", "release_date": "2016-01-01", "order": 12,
         "character": "Serveuse", "genre_ids": [35]},
        {"id": 3, "title": "Making-of", "release_date": "2014-01-01", "order": 0,
         "character": "Herself", "genre_ids": [99]},
        {"id": 4, "title": "Pas encore sorti", "release_date": "", "order": 0, "character": "X"},
        {"id": 5, "title": "Rien à foutre", "release_date": "2022-03-02", "order": 0,
         "character": "Cassandre", "genre_ids": [18]},
    ],
    "crew": [
        {"id": 6, "title": "Réalisé", "release_date": "2019-06-19", "job": "Director", "genre_ids": [35]},
        {"id": 7, "title": "Seulement produit", "release_date": "2020-01-01", "job": "Producer"},
    ],
}


def test_filmography_main_roles_only_most_recent_first():
    client = make_client({"/genre/movie/list": (200, GENRES),
                          "/person/42/movie_credits": (200, FILMO)})
    films = client.get_person_filmography(42, role="acting", max_billing=3)
    assert [f["title"] for f in films] == ["Rien à foutre", "La Vie d'Adèle"]
    assert films[1]["genres"] == ["Drame"] and films[1]["billing_order"] == 0


def test_filmography_directing_ignores_other_crew_jobs():
    client = make_client({"/genre/movie/list": (200, GENRES),
                          "/person/42/movie_credits": (200, FILMO)})
    assert [f["title"] for f in client.get_person_filmography(42, role="directing")] == ["Réalisé"]


def test_discover_by_origin_country():
    calls = []
    client = make_client({"/genre/movie/list": (200, GENRES),
                          "/discover/movie": (200, {"results": []})}, calls)
    client.discover_movies(origin_country="AR", genre_ids=[35])
    assert calls[-1].url.params["with_origin_country"] == "AR"
