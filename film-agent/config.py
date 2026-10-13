"""Configuration de l'agent : lecture du fichier .env.

Pourquoi un module dédié ?
- Un seul endroit sait où sont les secrets. Le reste du code demande
  `get_settings()` et ne lit jamais os.environ directement.
- On vérifie tôt qu'il ne manque rien, avec un message clair
  (qui nomme la variable manquante, jamais sa valeur).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent

# On cherche d'abord film-agent/.env, puis le .env à la racine du dépôt.
for candidate in (PROJECT_DIR / ".env", PROJECT_DIR.parent / ".env"):
    if candidate.exists():
        load_dotenv(candidate)
        break

# Réglages TMDB imposés par le besoin : données en français, disponibilité en France.
TMDB_LANGUAGE = "fr-FR"
TMDB_REGION = "FR"

# Mes abonnements en illimité. On compare des noms (et non des identifiants TMDB)
# car TMDB a plusieurs variantes : « Netflix », « Netflix Standard with Ads »…
MY_SUBSCRIPTIONS = ("Netflix", "Canal+")

# Plateformes gratuites (avec ou sans pub) : proposées juste après mes abonnements.
# TMDB les range parfois en « abonnement » : on les reconnaît donc aussi par leur nom.
FREE_PLATFORMS = ("Arte", "France TV", "france.tv", "TF1+", "M6+", "Pluto TV")

# Liens de recherche directs par plateforme ({q} = titre du film).
# TMDB ne fournit pas de lien direct vers le film sur chaque plateforme :
# on construit une recherche. ⚠️ Modèles à vérifier d'un clic (scripts/demo_tmdb.py).
# Une plateforme absente d'ici reçoit le lien de la page TMDB « Où regarder ».
PLATFORM_SEARCH_URLS = {
    "Netflix": "https://www.netflix.com/search?q={q}",
    "Canal+": "https://www.canalplus.com/recherche/?q={q}",
    "Arte": "https://www.arte.tv/fr/search/?q={q}",
    "France TV": "https://www.france.tv/recherche/?q={q}",
}


class ConfigError(RuntimeError):
    """Variable de configuration absente ou invalide."""


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    pinecone_api_key: str
    tmdb_api_key: str
    claude_model: str
    pinecone_index: str
    # Garde-fous de coût (réglables dans .env, valeurs par défaut prudentes)
    max_turns: int = 12               # allers-retours maximum par recherche
    max_budget_usd: float = 0.25      # coût maximum par recherche
    daily_budget_usd: float = 1.00    # coût maximum par jour (toutes recherches confondues)

    def __repr__(self) -> str:
        # Garde-fou : même un print(settings) ne doit pas afficher les clés.
        return (
            f"Settings(claude_model={self.claude_model!r}, "
            f"pinecone_index={self.pinecone_index!r}, clés=<masquées>)"
        )

    __str__ = __repr__


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"La variable {name} est absente ou vide. "
            f"Ajoute-la dans film-agent/.env (voir .env.example)."
        )
    return value


def _number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip().replace(",", ".")
    try:
        return float(raw) if raw else default
    except ValueError:
        raise ConfigError(f"La variable {name} doit être un nombre (reçu : « {raw} »).") from None


def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        pinecone_api_key=_require("PINECONE_API_KEY"),
        tmdb_api_key=_require("TMDB_API_KEY"),
        claude_model=_require("CLAUDE_MODEL"),
        pinecone_index=os.getenv("PINECONE_INDEX", "mes-films").strip() or "mes-films",
        max_turns=int(_number("AGENT_MAX_TURNS", 12)),
        max_budget_usd=_number("AGENT_MAX_BUDGET_USD", 0.25),
        daily_budget_usd=_number("AGENT_DAILY_BUDGET_USD", 1.00),
    )


def mask(secret: str) -> str:
    """Affiche une clé de façon reconnaissable mais inutilisable : 'sk-a…(108 car.)'."""
    return f"{secret[:4]}…({len(secret)} car.)" if secret else "<vide>"
