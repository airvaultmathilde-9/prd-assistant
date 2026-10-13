"""Phase 2 : mes notes dans Pinecone, et la recherche sémantique dessus.

Index avec « embeddings intégrés » : on envoie du TEXTE, Pinecone calcule lui-même
les vecteurs avec multilingual-e5-large (à l'import ET à la recherche).
Pas besoin d'appeler un modèle d'embeddings nous-mêmes.
"""

from __future__ import annotations

from typing import Any

EMBED_MODEL = "multilingual-e5-large"
CLOUD, REGION = "aws", "us-east-1"  # seule région du plan gratuit
NAMESPACE = "notes"
BATCH_SIZE = 90  # Pinecone accepte au plus 96 enregistrements par envoi avec embeddings intégrés

# Champs renvoyés à l'agent : on laisse de côté chunk_text, qui répète tout le reste.
RESULT_FIELDS = ["titre", "annee_sortie", "note", "avis", "commentaire", "tmdb_id",
                 "genres", "realisation", "casting", "annee_visionnage"]
# Pinecone stocke tous les nombres en décimal (2026.0) : on remet ceux-ci en entiers.
INTEGER_FIELDS = ("annee_sortie", "annee_visionnage", "tmdb_id")

# Reranking : un 2e modèle, plus lent mais plus fin, relit les candidats trouvés
# par la recherche vectorielle et les reclasse en lisant requête et texte ENSEMBLE.
RERANK_MODEL = "bge-reranker-v2-m3"  # multilingue, hébergé par Pinecone
RERANK_CANDIDATES = 20  # on ratisse large, puis le reranker garde les meilleurs


# Sources d'un film dans Pinecone : (absente) = import du CSV ; "agent" = ajouté dans la
# conversation ; "app" = ajouté ou modifié dans la page « Mes films ».
MANAGED_SOURCES = ("agent", "app")


def _clean_fields(fields: dict) -> dict:
    """Retire le texte vectorisé et remet en entiers les nombres que Pinecone stocke en décimal."""
    cleaned = {k: v for k, v in fields.items() if k != "chunk_text"}
    for key in INTEGER_FIELDS:
        if isinstance(cleaned.get(key), float):
            cleaned[key] = int(cleaned[key])
    return cleaned


def plan_sync(existing: set[str], csv_ids: set[str], managed: set[str]) -> tuple[set[str], list[str]]:
    """Import du CSV : (identifiants du CSV à envoyer, identifiants à supprimer de Pinecone).

    Les films gérés dans l'app ne sont ni écrasés par le CSV, ni supprimés.
    """
    to_upsert = csv_ids - managed
    stale = sorted(existing - csv_ids - managed)
    return to_upsert, stale


class RatingsStoreError(Exception):
    """Erreur Pinecone dont le message est sûr à afficher."""


class RatingsStore:
    def __init__(self, api_key: str, index_name: str, index: Any | None = None):
        # `index` est injectable : les tests passent un faux index, sans réseau.
        self._api_key = api_key
        self._index_name = index_name
        self._index = index
        self.rerank_enabled = True  # désactivé tout seul si Pinecone le refuse (quota, plan)

    def _pc(self):
        from pinecone import Pinecone
        return Pinecone(api_key=self._api_key)

    @property
    def index(self):
        if self._index is None:
            pc = self._pc()
            if not pc.has_index(self._index_name):
                raise RatingsStoreError(
                    f"l'index « {self._index_name} » n'existe pas : lance d'abord scripts/import_notes.py")
            self._index = pc.index(self._index_name)
        return self._index

    def ensure_index(self) -> bool:
        """Crée l'index s'il n'existe pas. Renvoie True s'il vient d'être créé."""
        pc = self._pc()
        if pc.has_index(self._index_name):
            return False
        pc.create_index_for_model(
            name=self._index_name,
            cloud=CLOUD,
            region=REGION,
            # field_map : « le texte à vectoriser se trouve dans le champ chunk_text ».
            embed={"model": EMBED_MODEL, "field_map": {"text": "chunk_text"}},
            timeout=120,  # attend que l'index soit prêt
        )
        return True

    def upsert(self, records: list[dict]) -> int:
        """« Upsert » = insère ou remplace (même _id -> mise à jour, pas de doublon)."""
        for start in range(0, len(records), BATCH_SIZE):
            self.index.upsert_records(namespace=NAMESPACE, records=records[start:start + BATCH_SIZE])
        return len(records)

    def all_ids(self) -> set[str]:
        """Identifiants de tous les films actuellement dans Pinecone."""
        return {item.id for page in self.index.list(namespace=NAMESPACE) for item in page.vectors}

    def _fetch_metadata(self, ids: list[str]) -> dict[str, dict]:
        """Métadonnées (titre, note, commentaire…) des films demandés, par paquets de 100."""
        found: dict[str, dict] = {}
        for start in range(0, len(ids), 100):
            response = self.index.fetch(ids=ids[start:start + 100], namespace=NAMESPACE)
            found |= {vid: dict(vec.metadata or {}) for vid, vec in response.vectors.items()}
        return found

    def managed_in_app(self, ids: list[str]) -> set[str]:
        """Parmi ces identifiants, les films ajoutés ou modifiés dans l'app ou par l'agent.

        Depuis la page « Mes films », c'est l'app qui fait foi : l'import du CSV ne les
        écrase plus et ne les supprime plus.
        """
        return {vid for vid, meta in self._fetch_metadata(ids).items()
                if meta.get("source") in MANAGED_SOURCES}

    def list_all(self) -> list[dict]:
        """Tous mes films notés, avec leurs champs (sans le texte vectorisé)."""
        films = []
        for vid, meta in self._fetch_metadata(sorted(self.all_ids())).items():
            films.append({"id": vid, **_clean_fields(meta)})
        return films

    def delete(self, ids: list[str]) -> int:
        """Supprime des films de Pinecone (irréversible, mais le CSV fait foi : il suffit de réimporter)."""
        for start in range(0, len(ids), 1000):
            self.index.delete(ids=ids[start:start + 1000], namespace=NAMESPACE)
        return len(ids)

    # ---------- Les futurs outils de l'agent ----------

    def search(self, query: str, top_k: int = 8,
               min_note: float | None = None, max_note: float | None = None) -> list[dict]:
        """Recherche sémantique dans MES films notés.

        Exemples : « comédie absurde », « film visuellement sublime »,
        « trop long », « Adèle Exarchopoulos ».
        min_note / max_note filtrent sur la note (ex. min_note=4 : ce que j'ai aimé).
        Le score dit à quel point le film correspond à la requête (plus haut = mieux).
        """
        note_filter: dict[str, float] = {}
        if min_note is not None:
            note_filter["$gte"] = min_note
        if max_note is not None:
            note_filter["$lte"] = max_note
        params = {
            "namespace": NAMESPACE,
            "inputs": {"text": query},
            "filter": {"note": note_filter} if note_filter else None,
        }
        response = None
        if self.rerank_enabled:
            try:
                response = self.index.search(
                    **params,
                    top_k=max(RERANK_CANDIDATES, top_k),
                    # Le reranker doit pouvoir lire chunk_text : on le demande en plus.
                    fields=RESULT_FIELDS + ["chunk_text"],
                    rerank={"model": RERANK_MODEL, "rank_fields": ["chunk_text"], "top_n": top_k},
                )
            except Exception:
                # Pas de reranking disponible : on retombe sur la recherche vectorielle seule.
                self.rerank_enabled = False
        if response is None:
            response = self.index.search(**params, top_k=top_k, fields=RESULT_FIELDS)
        return [self._clean(hit) for hit in response.result.hits]

    @staticmethod
    def _clean(hit) -> dict:
        return {"score": round(hit.score, 3), **_clean_fields(dict(hit.fields))}

    def already_seen(self, tmdb_ids: list[int]) -> dict[int, float | None]:
        """Pour chaque film TMDB : ma note si je l'ai déjà vu, sinon None.

        Une simple lecture par identifiant (pas une recherche) : rapide et exacte.
        """
        if not tmdb_ids:
            return {}
        wanted = {f"tmdb-{i}": i for i in tmdb_ids}
        response = self.index.fetch(ids=list(wanted), namespace=NAMESPACE)
        found = {wanted[vid]: (vec.metadata or {}).get("note") for vid, vec in response.vectors.items()}
        return {i: found.get(i) for i in tmdb_ids}

    def count(self) -> int:
        stats = self.index.describe_index_stats()
        namespace = stats.namespaces.get(NAMESPACE)
        return namespace.vector_count if namespace else 0
