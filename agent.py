"""MCP Host/Client: an OpenAI Agents SDK agent connected to the troupe-coop MCP server.

    python agent.py            # interactive chat with the troupe assistant
    python agent.py --check    # start the MCP server, list its tools/resources, exit (no LLM call)

The agent launches ``python -m troupe_coop.server`` as a subprocess and talks
to it over MCP (stdio). Every tool call and result is printed so the full
round trip agent -> MCP client -> MCP server -> back is visible.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from agents import Agent, Runner, RunContextWrapper
from agents.mcp import MCPServerStdio

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# ANSI colours (enable VT mode on older Windows consoles)
os.system("")
DIM, CYAN, YELLOW, GREEN, RED, BOLD, RESET = "\033[2m", "\033[36m", "\033[33m", "\033[32m", "\033[31m", "\033[1m", "\033[0m"

BASE_INSTRUCTIONS = """\
You are the coop assistant of a Scouts du Liban troupe leader (the "chef").
The chef uses you to organise members' orders from the SDL coop and to track who has paid.

Tools (from the troupe-coop MCP server):
- check_coop_item: look up an item's live price and whether a size/variant is offered. Read-only.
- process_member_order: the normal way to order a coop item for a member. It checks the item,
  charges the member and records any cash paid now, in one call.
- record_ledger_entry: record a payment that arrives later or in advance (entry_type="payment"),
  or a non-coop charge such as a camp fee (entry_type="charge").

Rules:
- Reply in the language the chef writes in (English, French or Lebanese Arabic / Arabizi).
- Coop item names are French. Search with the French catalog name (shirt -> chemise, troop -> troupe,
  whistle -> sifflet, neckerchief ring -> bague foulard, belt -> ceinture, socks -> chaussettes).
  When replying in English, keep the official French name and add a short English gloss in
  parentheses the first time, e.g. "Chemise Troupe Kaki (khaki troop shirt)".
- Never guess a size, colour or item. If a tool says 'ambiguous' or 'needs_variant', ask the chef.
  If a size is not offered, say so and propose the suggested alternatives; don't order them unasked.
- If several items are requested in one message, handle each one and summarise at the end.
- Money is in US dollars. A positive balance means the member owes the troupe; a negative one
  means they paid in advance and have credit.
- You never place orders on the coop website. The consolidated coop order (below) is a list the
  chef sends or brings to the coop (cash only). So say an order was "recorded", never "placed".
- Keep answers short and practical, like a message to a busy chef.
"""


def _resource_text(result) -> str:
    return "\n".join(getattr(c, "text", "") for c in result.contents)


def build_agent(server: MCPServerStdio) -> Agent:
    async def instructions(ctx: RunContextWrapper, agent: Agent) -> str:
        # MCP resources are application-controlled: the host reads them and hands them to the model
        # as fresh context on every model call, so balances are always up to date.
        balances = _resource_text(await server.read_resource("troupe://balances"))
        coop_order = _resource_text(await server.read_resource("troupe://coop-order"))
        return (
            f"{BASE_INSTRUCTIONS}\n"
            f"Current troupe balances (resource troupe://balances):\n{balances}\n\n"
            f"Consolidated coop order so far (resource troupe://coop-order):\n{coop_order}\n"
        )

    return Agent(
        name="Troupe coop assistant",
        instructions=instructions,
        mcp_servers=[server],
        model=os.environ.get("OPENAI_MODEL") or None,  # None = the Agents SDK default model
    )


def make_server() -> MCPServerStdio:
    return MCPServerStdio(
        name="troupe-coop",
        params={"command": sys.executable, "args": ["-m", "troupe_coop.server"], "cwd": str(ROOT)},
        cache_tools_list=True,
        client_session_timeout_seconds=30,  # coop lookups hit a live website
    )


def _short(text: str, limit: int = 400) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " ..."


def _tool_output_text(output) -> str:
    """Pull the human-readable 'message' out of a tool result when there is one."""
    raw = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("type") == "text":
            data = json.loads(data["text"])
        if isinstance(data, dict) and "message" in data:
            return f"{data.get('status', '')}: {data['message']}"
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return raw


async def chat(server: MCPServerStdio) -> None:
    agent = build_agent(server)
    history: list = []
    print(f"{BOLD}Troupe coop assistant{RESET} - type your request, or 'exit'.")
    while True:
        try:
            user = input(f"\n{BOLD}chef>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in {"exit", "quit", "q"}:
            break
        if not user:
            continue
        history.append({"role": "user", "content": user})
        result = Runner.run_streamed(agent, history, max_turns=15)
        async for event in result.stream_events():
            if event.type != "run_item_stream_event":
                continue
            item = event.item
            if item.type == "tool_call_item":
                raw = item.raw_item
                name = getattr(raw, "name", None) or getattr(item, "tool_name", "tool")
                args = getattr(raw, "arguments", "")
                print(f"{CYAN}  -> agent calls MCP tool {BOLD}{name}{RESET}{CYAN}({_short(args, 200)}){RESET}")
            elif item.type == "tool_call_output_item":
                text = _tool_output_text(item.output)
                colour = RED if "error" in text.lower()[:40] else YELLOW
                print(f"{colour}  <- server returned: {_short(text)}{RESET}")
        print(f"\n{GREEN}{result.final_output}{RESET}")
        history = result.to_input_list()


async def check(server: MCPServerStdio) -> None:
    tools = await server.list_tools()
    resources = await server.list_resources()
    templates = await server.list_resource_templates()
    print("Connected to MCP server 'troupe-coop'.")
    print("Tools:", ", ".join(t.name for t in tools))
    print("Resources:", ", ".join(str(r.uri) for r in resources.resources))
    print("Resource templates:", ", ".join(t.uri_template for t in templates.resource_templates))
    print(_short(_resource_text(await server.read_resource("troupe://balances")), 300))


async def main() -> None:
    check_only = "--check" in sys.argv
    if not check_only and not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
    async with make_server() as server:
        await (check(server) if check_only else chat(server))


if __name__ == "__main__":
    asyncio.run(main())
