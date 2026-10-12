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


class RatingsStoreError(Exception):
    """Erreur Pinecone dont le message est sûr à afficher."""


class RatingsStore:
    def __init__(self, api_key: str, index_name: str, index: Any | None = None):
        # `index` est injectable : les tests passent un faux index, sans réseau.
        self._api_key = api_key
        self._index_name = index_name
        self._index = index

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
        Le score (0 à 1) dit à quel point le film ressemble à la requête.
        """
        note_filter: dict[str, float] = {}
        if min_note is not None:
            note_filter["$gte"] = min_note
        if max_note is not None:
            note_filter["$lte"] = max_note
        response = self.index.search(
            namespace=NAMESPACE,
            top_k=top_k,
            inputs={"text": query},
            filter={"note": note_filter} if note_filter else None,
            fields=RESULT_FIELDS,
        )
        return [{"score": round(hit.score, 3), **dict(hit.fields)} for hit in response.result.hits]

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
