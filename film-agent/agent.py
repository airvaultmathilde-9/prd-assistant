"""Phase 3 : l'agent de recommandation, en conversation dans le Terminal.

Lancement (depuis film-agent/) :  python agent.py
Option --trace-full : affiche les paramètres complets de chaque appel d'outil.

La boucle d'agent elle-même (penser -> appeler un outil -> lire le résultat ->
recommencer ou répondre) est gérée par le Claude Agent SDK. Notre travail :
lui donner des outils, des instructions, et des limites.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from agent_tools import SessionRegistry, allowed_tool_names, build_server, build_tools
from config import PROJECT_DIR, Settings, get_settings
from ratings_store import RatingsStore
from tmdb_client import TMDBClient

SYSTEM_PROMPT = (PROJECT_DIR / "prompts" / "system_prompt.md").read_text(encoding="utf-8")

# Limites : un agent a besoin de garde-fous sur ses propres boucles.
MAX_TURNS = 25          # nombre maximal d'allers-retours (outil + réponse) par question
MAX_BUDGET_USD = 1.00   # coût maximal par question


def build_options(settings: Settings, registry: SessionRegistry) -> ClaudeAgentOptions:
    tools = build_tools(TMDBClient(settings.tmdb_api_key),
                        RatingsStore(settings.pinecone_api_key, settings.pinecone_index),
                        registry)
    return ClaudeAgentOptions(
        model=settings.claude_model,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"films": build_server(tools)},
        # Aucun outil intégré de Claude Code (pas de terminal, pas de fichiers, pas de web) :
        # l'agent ne peut faire QUE ce que nos outils permettent.
        tools=[],
        allowed_tools=allowed_tool_names(tools),
        # N'utilise pas tes réglages Claude Code personnels ni le CLAUDE.md du dépôt.
        setting_sources=[],
        cwd=str(PROJECT_DIR),
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
        env={"ANTHROPIC_API_KEY": settings.anthropic_api_key},
    )


# ---------- Affichage de la trace : voir l'agent « réfléchir » ----------

def _short_name(name: str) -> str:
    return name.rsplit("__", 1)[-1]  # mcp__films__discover_movies -> discover_movies


def _describe_result(block: ToolResultBlock) -> str:
    text = block.content if isinstance(block.content, str) else " ".join(
        part.get("text", "") for part in block.content or [])
    if block.is_error:
        return f"❌ {text[:120]}"
    try:
        data = json.loads(text)
    except ValueError:
        return text[:80]
    if isinstance(data, list):
        titles = [d.get("title") or d.get("titre") or d.get("name") for d in data[:4]]
        return f"{len(data)} résultat(s) : {', '.join(t for t in titles if t)}{'…' if len(data) > 4 else ''}"
    if isinstance(data, dict) and "options" in data:
        best = data["options"][0] if data["options"] else None
        return f"{best['platform']} ({best['access']})" if best else "pas disponible en France"
    return "ok"


def print_message(message, full_trace: bool) -> None:
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                print(f"\n🎬 {block.text}")
            elif isinstance(block, ToolUseBlock):
                params = json.dumps(block.input, ensure_ascii=False)
                if not full_trace and len(params) > 100:
                    params = params[:100] + "…"
                print(f"   🔧 {_short_name(block.name)} {params}")
    elif isinstance(message, UserMessage) and isinstance(message.content, list):
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                print(f"      ↳ {_describe_result(block)}")
    elif isinstance(message, ResultMessage):
        cost = f"{message.total_cost_usd:.3f} $" if message.total_cost_usd is not None else "?"
        if message.subtype == "error_max_turns":
            print(f"\n⚠️  Limite de {MAX_TURNS} tours atteinte : l'agent s'est arrêté.")
        elif message.subtype == "error_max_budget_usd":
            print(f"\n⚠️  Budget de {MAX_BUDGET_USD:.2f} $ atteint : l'agent s'est arrêté.")
        print(f"\n   ({message.num_turns} tours · {message.duration_ms / 1000:.0f} s · coût {cost})")


async def chat(full_trace: bool) -> None:
    settings = get_settings()
    registry = SessionRegistry()
    print("Agent films : dis-moi ce que tu as envie de regarder (« quit » pour sortir).")
    async with ClaudeSDKClient(options=build_options(settings, registry)) as client:
        while True:
            try:
                question = (await asyncio.to_thread(input, "\nToi > ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question.lower() in ("quit", "exit", "q"):
                break
            if not question:
                continue
            await client.query(question)
            async for message in client.receive_response():
                print_message(message, full_trace)
    print(f"\nÀ bientôt ! ({len(registry.movies)} films TMDB consultés pendant la session)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent de recommandation de films.")
    parser.add_argument("--trace-full", action="store_true", help="paramètres complets des outils")
    args = parser.parse_args()
    asyncio.run(chat(args.trace_full))
    return 0


if __name__ == "__main__":
    sys.exit(main())
