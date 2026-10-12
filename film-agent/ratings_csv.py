"""Phase 2 : de mon CSV de notes à des enregistrements prêts pour Pinecone.

Trois étapes, chacune testable seule :
1. read_ratings   : lire le CSV (tabulation, point-virgule ou virgule).
2. match_rating   : retrouver chaque film dans TMDB (sans jamais deviner au hasard).
3. build_record   : écrire le texte qui sera transformé en vecteur, plus les métadonnées.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

REQUIRED_COLUMNS = ("titre", "note_sur_5")


@dataclass(frozen=True)
class Rating:
    titre: str
    annee_sortie: int | None
    annee_visionnage: int | None
    note: float
    commentaire: str
    line: int  # numéro de ligne dans le CSV, pour des messages d'erreur utiles

    @property
    def key(self) -> str:
        """Clé lisible d'un film du CSV, utilisée dans le fichier de correspondances."""
        return f"{self.titre} ({self.annee_sortie or '?'})"


# ---------- 1. Lecture du CSV ----------

def _to_int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def read_ratings(path: Path) -> tuple[list[Rating], list[str]]:
    """Renvoie (notes valides, erreurs lisibles). Une ligne invalide n'arrête pas tout."""
    # utf-8-sig : accepte le caractère invisible qu'Excel ajoute en début de fichier.
    text = path.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0] if text else ""
    delimiter = "\t" if "\t" in header else ";" if ";" in header else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)

    columns = [c.strip() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        return [], [f"colonnes manquantes : {', '.join(missing)} (trouvées : {', '.join(columns)})"]

    ratings, errors = [], []
    for line, row in enumerate(reader, start=2):  # ligne 1 = en-tête
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        titre = row.get("titre", "")
        if not titre:
            errors.append(f"ligne {line} : titre vide, ignorée")
            continue
        try:
            note = float(row.get("note_sur_5", "").replace(",", "."))  # « 3,5 » accepté
        except ValueError:
            errors.append(f"ligne {line} ({titre}) : note illisible « {row.get('note_sur_5')} »")
            continue
        if not 0 <= note <= 5:
            errors.append(f"ligne {line} ({titre}) : note {note} hors de l'échelle 0-5")
            continue
        ratings.append(Rating(
            titre=titre,
            annee_sortie=_to_int(row.get("annee_sortie", "")),
            annee_visionnage=_to_int(row.get("annee_visionnage", "")),
            note=note,
            commentaire=row.get("commentaire", ""),
            line=line,
        ))
    return ratings, errors


# ---------- 2. Correspondance avec TMDB ----------

@dataclass(frozen=True)
class Match:
    tmdb_id: int | None
    confidence: str  # "sûr", "probable", "à vérifier", "introuvable"
    tmdb_title: str | None = None
    tmdb_year: int | None = None
    candidates: tuple[str, ...] = ()  # pour aider à corriger à la main


def _simplify(title: str) -> str:
    """« La Vie d'Adèle – Chapitres 1 & 2 » -> « la vie d adele chapitres 1 et 2 »."""
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = t.replace("&", " et ")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _simplify(a), _simplify(b)).ratio()


def _query_variants(titre: str) -> list[str]:
    """Titres à essayer, du plus précis au plus large."""
    variants = [titre]
    for sep in (" – ", " — ", " - ", " : ", ": "):
        if sep in titre:
            variants.append(titre.split(sep)[0])  # « La Vie d'Adèle – Chapitres… » -> « La Vie d'Adèle »
    return list(dict.fromkeys(variants))  # sans doublons, ordre conservé


def match_rating(tmdb, rating: Rating) -> Match:
    """Trouve le film TMDB qui correspond à une ligne du CSV.

    Règle d'or : mieux vaut « à vérifier » qu'un mauvais film. Un mauvais
    identifiant ferait croire à l'agent que tu as vu un film que tu n'as pas vu.
    """
    candidates: dict[int, dict] = {}
    for query in _query_variants(rating.titre):
        # D'abord avec l'année (précis), puis sans (les dates TMDB varient parfois d'un an).
        for year in ([rating.annee_sortie, None] if rating.annee_sortie else [None]):
            for movie in tmdb.search_movies(query, year=year, limit=8):
                candidates.setdefault(movie["tmdb_id"], movie)
        if candidates:
            break

    if not candidates:
        return Match(None, "introuvable")

    def title_score(movie: dict) -> float:
        return max(_similarity(rating.titre, movie["title"] or ""),
                   _similarity(rating.titre, movie["original_title"] or ""))

    def year_gap(movie: dict) -> int:
        if not rating.annee_sortie or not movie["year"]:
            return 0
        return abs(movie["year"] - rating.annee_sortie)

    # Classement : ressemblance du titre, pénalisée par l'écart d'année ;
    # à égalité, le film le plus connu (beaucoup de votes) passe devant.
    ranked = sorted(candidates.values(),
                    key=lambda m: (title_score(m) - 0.1 * min(year_gap(m), 5), m["vote_count"]),
                    reverse=True)
    best = ranked[0]
    best_title_score = title_score(best)
    year_ok = year_gap(best) <= 1
    if best_title_score >= 0.9 and year_ok:
        confidence = "sûr"
    elif best_title_score >= 0.6 and year_ok:
        confidence = "probable"
    else:
        confidence = "à vérifier"
    return Match(
        tmdb_id=best["tmdb_id"] if confidence != "à vérifier" else None,
        confidence=confidence,
        tmdb_title=best["title"],
        tmdb_year=best["year"],
        candidates=tuple(f"{m['title']} ({m['year']}) -> {m['tmdb_id']}" for m in ranked[:3]),
    )


# ---------- 3. Construction de l'enregistrement Pinecone ----------

def note_in_words(note: float) -> str:
    if note >= 4.5:
        return "adoré"
    if note >= 3.5:
        return "aimé"
    if note >= 2.5:
        return "mitigé"
    if note >= 1.5:
        return "pas aimé"
    return "détesté"


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _ascii_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _simplify(text)).strip("-")


def record_id(rating: Rating, tmdb_id: int | None) -> str:
    """Identifiant STABLE : relancer l'import met à jour au lieu de dupliquer."""
    if tmdb_id:
        return f"tmdb-{tmdb_id}"
    return f"csv-{_ascii_slug(rating.titre)}-{rating.annee_sortie or 'na'}"


def build_record(rating: Rating, tmdb_id: int | None, details: dict | None) -> dict:
    """Un enregistrement = un texte (vectorisé par Pinecone) + des métadonnées (filtrables).

    Le texte mélange les faits (réalisation, genres, casting) et MON avis :
    ainsi « un film absurde avec un duo d'acteurs » retrouve Mandibules
    même si le mot « absurde » n'apparaît que dans mon commentaire.
    """
    details = details or {}
    year = rating.annee_sortie or details.get("year")
    parts = [f"{rating.titre} ({year or 'année inconnue'})."]
    if details.get("directors"):
        parts.append(f"Réalisation : {', '.join(details['directors'])}.")
    if details.get("genres"):
        parts.append(f"Genres : {', '.join(details['genres'])}.")
    if details.get("cast"):
        parts.append(f"Avec : {', '.join(details['cast'][:4])}.")
    if details.get("overview"):
        # Le résumé TMDB dit DE QUOI parle le film (quête, guerre, famille…) :
        # c'est ce qui manquait pour qu'« épique » retrouve Le Seigneur des anneaux.
        parts.append(f"Résumé : {_shorten(details['overview'], 400)}")
    parts.append(f"Ma note : {rating.note:g}/5, j'ai {note_in_words(rating.note)}.")
    if rating.commentaire:
        parts.append(f"Mon avis : {rating.commentaire}")

    record = {
        "_id": record_id(rating, tmdb_id),
        "chunk_text": " ".join(parts),  # le champ que Pinecone transforme en vecteur
        "titre": rating.titre,
        "note": rating.note,
        "avis": note_in_words(rating.note),
        "commentaire": rating.commentaire,
        "annee_sortie": year,
        "annee_visionnage": rating.annee_visionnage,
        "tmdb_id": tmdb_id,
        "genres": details.get("genres"),
        "realisation": details.get("directors"),
        "casting": details.get("cast", [])[:4] or None,
        "langue_originale": details.get("original_language"),
    }
    # Pinecone refuse les valeurs nulles et les listes vides dans les métadonnées.
    return {k: v for k, v in record.items() if v not in (None, "", [])}
