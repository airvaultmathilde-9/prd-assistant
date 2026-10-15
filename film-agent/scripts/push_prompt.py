"""Envoyer le fichier prompts/system_prompt.md dans Langfuse, comme nouvelle version du prompt.

Depuis film-agent/ :
  python scripts/push_prompt.py                  # nouvelle version, étiquetée « production »
  python scripts/push_prompt.py --label staging  # nouvelle version à tester, sans toucher à la production

À faire une fois pour démarrer. Ensuite, modifie le prompt directement dans Langfuse
(onglet Prompts) : ce script ne sert plus qu'à repartir du fichier si tu le souhaites.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_manager import LOCAL_FILE, PROMPT_NAME  # noqa: E402
from tracing import get_client  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Envoyer le prompt local dans Langfuse.")
    parser.add_argument("--label", default="production",
                        help="étiquette de la nouvelle version (défaut : production)")
    args = parser.parse_args()
    client = get_client()
    if client is None:
        sys.exit("❌ Langfuse n'est pas configuré : ajoute LANGFUSE_PUBLIC_KEY et LANGFUSE_SECRET_KEY dans .env.")
    prompt = client.create_prompt(name=PROMPT_NAME, type="text", prompt=LOCAL_FILE.read_text(encoding="utf-8"),
                                  labels=[args.label], commit_message="Depuis prompts/system_prompt.md")
    client.flush()
    print(f"✅ « {PROMPT_NAME} » version {prompt.version} créée dans Langfuse, étiquette « {args.label} ».")
    print("   Langfuse → Prompts pour la voir et la modifier.")


if __name__ == "__main__":
    main()
