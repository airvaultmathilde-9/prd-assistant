"""Client TMDB : les fonctions qui deviendront les outils de l'agent (phase 3).

Principes de conception d'un bon outil pour un LLM :
1. Une fonction = une intention claire (chercher, découvrir, détailler, savoir où voir).
2. Des réponses COMPACTES : on renvoie seulement les champs utiles pour décider.
   Chaque champ inutile coûte des tokens et dilue l'attention du modèle.
3. Des erreurs LISIBLES : le modèle doit pouvoir comprendre l'erreur et réagir
   (reformuler, élargir, abandonner). Et sans jamais exposer la clé.
4. Aucune donnée inventée : tout vient d'une réponse de l'API.
"""

from __future__ import annotations

import unicodedata
from typing import Any
from urllib.parse import quote_plus

import httpx

from config import (
    FREE_PLATFORMS,
    MY_SUBSCRIPTIONS,
    PLATFORM_SEARCH_URLS,
    TMDB_LANGUAGE,
    TMDB_REGION,
)

BASE_URL = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w342"
TIMEOUT = 15.0
OVERVIEW_MAX_CHARS = 280


class TMDBError(Exception):
    """Erreur TMDB dont le message est sûr à afficher (jamais de clé dedans)."""


def tmdb_auth(api_key: str) -> tuple[dict, dict]:
    """TMDB accepte deux formats de clé : on renvoie (headers, params) adaptés."""
    if api_key.startswith("eyJ"):  # jeton v4 (JWT) -> en-tête Authorization
        return {"Authorization": f"Bearer {api_key}"}, {}
    return {}, {"api_key": api_key}  # clé v3 -> paramètre d'URL


def _normalize(name: str) -> str:
    """'Canal +' -> 'canal+', 'Séries' -> 'series' : pour comparer des noms de plateformes."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return ascii_name.lower().replace(" ", "")


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and date[:4].isdigit() else None


def _truncate(text: str, limit: int = OVERVIEW_MAX_CHARS) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


class TMDBClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        # `http` est injectable : les tests passent un faux transport, sans réseau.
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)
        self._auth_headers, self._auth_params = tmdb_auth(api_key)
        self._genres: dict[int, str] | None = None
        self._subscription_ids: dict[int, str] | None = None

    # ---------- Plomberie ----------

    def _get(self, path: str, **params: Any) -> dict:
        query = {"language": TMDB_LANGUAGE, **params, **self._auth_params}
        query = {k: v for k, v in query.items() if v is not None}
        try:
            response = self._http.get(path, params=query, headers=self._auth_headers)
        except httpx.HTTPError as exc:
            # « from None » : on coupe le lien avec l'exception d'origine,
            # dont le texte contient l'URL… donc la clé v3.
            raise TMDBError(f"TMDB injoignable ({type(exc).__name__})") from None
        if response.status_code == 401:
            raise TMDBError("clé TMDB refusée (401)")
        if response.status_code == 404:
            raise TMDBError(f"ressource TMDB introuvable : {path}")
        if response.status_code == 429:
            raise TMDBError("trop de requêtes vers TMDB, réessayer dans quelques secondes")
        if response.status_code >= 400:
            raise TMDBError(f"erreur TMDB HTTP {response.status_code} sur {path}")
        return response.json()

    def genres(self) -> dict[int, str]:
        """Table id -> nom des genres, en français. Mise en cache : elle ne change pas."""
        if self._genres is None:
            data = self._get("/genre/movie/list")
            self._genres = {g["id"]: g["name"] for g in data.get("genres", [])}
        return self._genres

    def subscription_provider_ids(self) -> dict[int, str]:
        """Identifiants TMDB des plateformes de MY_SUBSCRIPTIONS disponibles en France.

        On les cherche dans la liste officielle plutôt que de les coder en dur :
        si TMDB ajoute « Netflix avec pub » ou renomme une offre, ça suit tout seul.
        """
        if self._subscription_ids is None:
            data = self._get("/watch/providers/movie", watch_region=TMDB_REGION)
            wanted = [_normalize(s) for s in MY_SUBSCRIPTIONS]
            self._subscription_ids = {
                p["provider_id"]: p["provider_name"]
                for p in data.get("results", [])
                if any(_normalize(p["provider_name"]).startswith(w) for w in wanted)
            }
        return self._subscription_ids

    def _summary(self, movie: dict) -> dict:
        """Version compacte d'un film, pour les listes de résultats."""
        genre_names = self.genres()
        poster = movie.get("poster_path")
        return {
            "tmdb_id": movie["id"],
            "title": movie.get("title"),
            "original_title": movie.get("original_title"),
            "year": _year(movie.get("release_date")),
            "original_language": movie.get("original_language"),
            "genres": [genre_names.get(g, str(g)) for g in movie.get("genre_ids", [])],
            "vote_average": round(movie.get("vote_average", 0), 1),
            "vote_count": movie.get("vote_count", 0),
            "overview": _truncate(movie.get("overview") or ""),
            "poster_url": f"{POSTER_BASE}{poster}" if poster else None,
        }

    # ---------- Les futurs outils de l'agent ----------

    def search_movies(self, query: str, year: int | None = None, limit: int = 8) -> list[dict]:
        """Recherche par titre (français ou original)."""
        data = self._get("/search/movie", query=query, primary_release_year=year,
                         region=TMDB_REGION, include_adult="false")
        return [self._summary(m) for m in data.get("results", [])[:limit]]

    def discover_movies(
        self,
        genre_ids: list[int] | None = None,
        exclude_genre_ids: list[int] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        min_vote_average: float | None = None,
        min_vote_count: int = 100,
        original_language: str | None = None,
        origin_country: str | None = None,
        person_ids: list[int] | None = None,
        keyword_ids: list[int] | None = None,
        max_runtime: int | None = None,
        on_my_subscriptions: bool = False,
        sort_by: str = "popularity.desc",
        page: int = 1,
        limit: int = 10,
    ) -> list[dict]:
        """Découverte par critères : c'est l'outil principal pour trouver des idées.

        - Plusieurs genres = ET (le film doit les avoir tous).
        - on_my_subscriptions=True : seulement les films inclus dans mes abonnements
          (offre « flatrate » = sans supplément), en France.
        - min_vote_count évite les films notés par 3 personnes avec une moyenne de 10.
        - origin_country : code pays ISO (« AR » = Argentine), pour « un film argentin ».
        """
        params: dict[str, Any] = {
            "with_genres": ",".join(map(str, genre_ids)) if genre_ids else None,
            "without_genres": ",".join(map(str, exclude_genre_ids)) if exclude_genre_ids else None,
            "primary_release_date.gte": f"{year_from}-01-01" if year_from else None,
            "primary_release_date.lte": f"{year_to}-12-31" if year_to else None,
            "vote_average.gte": min_vote_average,
            "vote_count.gte": min_vote_count,
            "with_original_language": original_language,
            "with_origin_country": origin_country,
            # « | » = OU : un film avec l'une OU l'autre de ces personnes / de ces mots-clés.
            "with_people": "|".join(map(str, person_ids)) if person_ids else None,
            "with_keywords": "|".join(map(str, keyword_ids)) if keyword_ids else None,
            "with_runtime.lte": max_runtime,
            "sort_by": sort_by,
            "page": page,
            "region": TMDB_REGION,
            "include_adult": "false",
        }
        if on_my_subscriptions:
            provider_ids = self.subscription_provider_ids()
            if not provider_ids:
                raise TMDBError("aucune de mes plateformes trouvée dans la liste TMDB pour la France")
            params |= {
                "with_watch_providers": "|".join(map(str, provider_ids)),
                "watch_region": TMDB_REGION,
                "with_watch_monetization_types": "flatrate",
            }
        data = self._get("/discover/movie", **params)
        return [self._summary(m) for m in data.get("results", [])[:limit]]

    def get_movie_details(self, tmdb_id: int) -> dict:
        """Fiche détaillée : réalisation, casting, durée, langues, mots-clés."""
        m = self._get(f"/movie/{tmdb_id}", append_to_response="credits,keywords")
        credits = m.get("credits", {})
        poster = m.get("poster_path")
        return {
            "tmdb_id": m["id"],
            "title": m.get("title"),
            "original_title": m.get("original_title"),
            "year": _year(m.get("release_date")),
            "runtime_min": m.get("runtime"),
            "genres": [g["name"] for g in m.get("genres", [])],
            "directors": [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"],
            "cast": [c["name"] for c in credits.get("cast", [])[:5]],
            "original_language": m.get("original_language"),
            "spoken_languages": [l.get("iso_639_1") for l in m.get("spoken_languages", [])],
            "origin_countries": m.get("origin_country", []),
            "keywords": [k["name"] for k in m.get("keywords", {}).get("keywords", [])[:10]],
            "vote_average": round(m.get("vote_average", 0), 1),
            "vote_count": m.get("vote_count", 0),
            "tagline": m.get("tagline") or None,
            "overview": m.get("overview") or "",
            "poster_url": f"{POSTER_BASE}{poster}" if poster else None,
            "tmdb_url": f"https://www.themoviedb.org/movie/{m['id']}",
        }

    def get_watch_providers(self, tmdb_id: int) -> dict:
        """Où voir le film CHEZ MOI en France, avec un lien pour chaque option.

        Les options sont triées selon ma priorité :
          1. « abonnement »       inclus dans Netflix / Canal+ (rien à payer)
          2. « gratuit »          Arte, france.tv… (rien à payer non plus)
          3. « location »         à l'unité, quelques euros (prix non fourni par TMDB)
          4. « achat »            achat numérique
          5. « autre_abonnement » plateforme payante que je n'ai pas (pour info)
        """
        # Un seul appel : la fiche du film (pour le titre) + ses plateformes.
        movie = self._get(f"/movie/{tmdb_id}", append_to_response="watch/providers")
        title = movie.get("title") or movie.get("original_title") or ""
        fr = movie.get("watch/providers", {}).get("results", {}).get(TMDB_REGION)
        result = {"tmdb_id": tmdb_id, "title": title,
                  "available_at_home_in_france": bool(fr), "options": [],
                  # Les données de disponibilité viennent de JustWatch : TMDB demande de le citer.
                  "source": "JustWatch"}
        if not fr:
            return result

        # Page TMDB « Où regarder » : toujours valide, elle liste toutes les offres.
        watch_page = fr.get("link") or f"https://www.themoviedb.org/movie/{tmdb_id}/watch?locale=FR"
        result["watch_page"] = watch_page
        my_ids = self.subscription_provider_ids()
        free_names = [_normalize(n) for n in FREE_PLATFORMS]

        def access_for(provider: dict, kind: str) -> str:
            if kind in ("rent", "buy"):
                return {"rent": "location", "buy": "achat"}[kind]
            if provider["provider_id"] in my_ids:
                return "abonnement"
            is_free = kind in ("free", "ads") or any(
                _normalize(provider["provider_name"]).startswith(f) for f in free_names)
            return "gratuit" if is_free else "autre_abonnement"

        def link_for(provider_name: str) -> tuple[str, str]:
            for platform, pattern in PLATFORM_SEARCH_URLS.items():
                if _normalize(provider_name).startswith(_normalize(platform)):
                    return pattern.format(q=quote_plus(title)), "recherche sur la plateforme"
            return watch_page, "page TMDB « Où regarder »"

        priority = ["abonnement", "gratuit", "location", "achat", "autre_abonnement"]
        seen = set()
        for kind in ("flatrate", "free", "ads", "rent", "buy"):
            for provider in fr.get(kind, []):
                access = access_for(provider, kind)
                if (provider["provider_name"], access) in seen:
                    continue
                seen.add((provider["provider_name"], access))
                link, link_type = link_for(provider["provider_name"])
                result["options"].append({"platform": provider["provider_name"], "access": access,
                                          "link": link, "link_type": link_type})
        result["options"].sort(key=lambda o: priority.index(o["access"]))
        result["best_access"] = result["options"][0]["access"] if result["options"] else None
        return result

    def get_person_filmography(self, person_id: int, role: str = "acting",
                               max_billing: int | None = None, limit: int = 40) -> list[dict]:
        """Filmographie d'une personne, du plus récent au plus ancien.

        role = "acting" (films où elle joue) ou "directing" (films qu'elle a réalisés).
        max_billing (pour "acting") : ne garder que les rôles importants.
        TMDB classe le casting par ordre d'importance au générique : 0 = tête d'affiche.
        max_billing=3 garde donc les 4 premiers noms, soit en pratique les rôles principaux.

        Pourquoi pas discover_movies(person_ids=…) ? Parce qu'il mélange tout :
        un caméo, un film seulement produit ou coscénarisé… Ici on sait QUEL rôle.
        """
        if role not in ("acting", "directing"):
            raise TMDBError("role doit valoir « acting » ou « directing »")
        data = self._get(f"/person/{person_id}/movie_credits")
        genre_names = self.genres()

        if role == "acting":
            credits = [
                c for c in data.get("cast", [])
                # On écarte les apparitions « dans son propre rôle » (documentaires, making-of).
                if not any(w in (c.get("character") or "").lower() for w in ("self", "même"))
                and (max_billing is None or c.get("order", 99) <= max_billing)
            ]
        else:
            credits = [c for c in data.get("crew", []) if c.get("job") == "Director"]

        films, seen = [], set()
        for c in credits:
            if c["id"] in seen or not c.get("release_date"):  # pas de date = pas encore sorti
                continue
            seen.add(c["id"])
            films.append({
                "tmdb_id": c["id"],
                "title": c.get("title"),
                "year": _year(c.get("release_date")),
                "genres": [genre_names.get(g, str(g)) for g in c.get("genre_ids", [])],
                "vote_average": round(c.get("vote_average", 0), 1),
                "vote_count": c.get("vote_count", 0),
                **({"character": c.get("character"), "billing_order": c.get("order")}
                   if role == "acting" else {}),
            })
        films.sort(key=lambda f: f["year"] or 0, reverse=True)
        return films[:limit]

    def search_person(self, name: str, limit: int = 5) -> list[dict]:
        """Trouver l'identifiant d'un·e cinéaste ou d'un·e acteur·rice (pour discover_movies)."""
        data = self._get("/search/person", query=name, include_adult="false")
        return [
            {
                "person_id": p["id"],
                "name": p.get("name"),
                "known_for_department": p.get("known_for_department"),
                "known_for": [k.get("title") or k.get("name") for k in p.get("known_for", [])][:3],
            }
            for p in data.get("results", [])[:limit]
        ]

    def search_keyword(self, query: str, limit: int = 10) -> list[dict]:
        """Trouver l'identifiant d'un thème (ex. « time travel »). Mots-clés surtout en anglais."""
        data = self._get("/search/keyword", query=query)
        return [{"keyword_id": k["id"], "name": k["name"]} for k in data.get("results", [])[:limit]]
