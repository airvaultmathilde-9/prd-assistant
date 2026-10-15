"""Les instructions de l'agent, gérées dans Langfuse (onglet « Prompts »).

- Le texte vit dans Langfuse, sous le nom PROMPT_NAME. On le modifie là-bas : chaque
  modification crée une VERSION, et l'étiquette « production » dit laquelle l'agent utilise.
- L'agent relit le prompt à chaque recherche (gardé 60 s en cache) : pas besoin de relancer l'app.
- Filet de sécurité : si Langfuse n'est pas configuré, ne répond pas, ou n'a pas encore ce prompt,
  on utilise le fichier local prompts/system_prompt.md. L'agent ne tombe jamais en panne à cause de ça.
- Chaque trace est reliée à la version utilisée : dans Langfuse, on compare les versions entre elles.

Ce qui reste dans le code : les consignes techniques (budget de tours, format de réponse pour
l'interface) et la skill (.claude/skills), lue par le SDK depuis les fichiers.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from config import PROJECT_DIR
from tracing import get_client

logger = logging.getLogger(__name__)

PROMPT_NAME = "film-agent-instructions"
LOCAL_FILE = PROJECT_DIR / "prompts" / "system_prompt.md"
CACHE_SECONDS = 60


def prompt_label() -> str:
    """Quelle version utiliser : « production » par défaut (LANGFUSE_PROMPT_LABEL pour en tester une autre)."""
    return os.getenv("LANGFUSE_PROMPT_LABEL", "production")


@dataclass
class SystemPrompt:
    text: str
    source: str               # « langfuse v3 (production) » ou « fichier local »
    client: Any = None        # le prompt Langfuse, pour relier les traces à sa version


def load_system_prompt() -> SystemPrompt:
    local = LOCAL_FILE.read_text(encoding="utf-8")
    client = get_client()
    if client is None:
        return SystemPrompt(local, "fichier local")
    label = prompt_label()
    try:
        prompt = client.get_prompt(PROMPT_NAME, label=label, type="text",
                                   cache_ttl_seconds=CACHE_SECONDS, fallback=local)
    except Exception:  # Langfuse injoignable, prompt absent… : on garde le fichier
        logger.warning("Prompt Langfuse indisponible : fichier local utilisé")
        return SystemPrompt(local, "fichier local")
    if getattr(prompt, "is_fallback", False):
        return SystemPrompt(local, "fichier local")
    return SystemPrompt(prompt.prompt, f"langfuse v{prompt.version} ({label})", prompt)
