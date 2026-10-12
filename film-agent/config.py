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


class ConfigError(RuntimeError):
    """Variable de configuration absente ou invalide."""


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    pinecone_api_key: str
    tmdb_api_key: str
    claude_model: str
    pinecone_index: str

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


def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        pinecone_api_key=_require("PINECONE_API_KEY"),
        tmdb_api_key=_require("TMDB_API_KEY"),
        claude_model=_require("CLAUDE_MODEL"),
        pinecone_index=os.getenv("PINECONE_INDEX", "mes-films").strip() or "mes-films",
    )


def mask(secret: str) -> str:
    """Affiche une clé de façon reconnaissable mais inutilisable : 'sk-a…(108 car.)'."""
    return f"{secret[:4]}…({len(secret)} car.)" if secret else "<vide>"
