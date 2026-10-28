"""Call each MCP tool directly over stdio (no LLM), including the failure cases.

    python scripts/demo_tools.py

Starts the real server as a subprocess, exactly like the agent does, and uses
the live coop website. Run scripts/reset_demo.py afterwards to undo the
ledger writes.
"""

import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

CALLS = [
    ("Data: price + size check", "check_coop_item", {"item": "Chemise Troupe Kaki", "variant": ["M"]}),
    ("Data: size not offered", "check_coop_item", {"item": "Chemise Troupe Kaki", "variant": ["8"]}),
    ("Data: ambiguous name", "check_coop_item", {"item": "chemise troupe"}),
    ("Data: item does not exist (error)", "check_coop_item", {"item": "tente geante"}),
    ("Orchestration: order + partial payment", "process_member_order",
     {"member": "Karim", "item": "Chemise Troupe Kaki", "variant": ["S"], "quantity": 1, "paid_now_usd": 10}),
    ("Orchestration: unavailable size -> nothing recorded", "process_member_order",
     {"member": "Rami", "item": "Chemise Troupe Kaki", "variant": ["8"]}),
    ("Action: late payment", "record_ledger_entry", {"member": "Jad", "entry_type": "payment", "amount_usd": 15, "description": "Cash"}),
    ("Action: unknown member (error)", "record_ledger_entry", {"member": "Ziad", "entry_type": "payment", "amount_usd": 5}),
    ("Action: negative amount (error)", "record_ledger_entry", {"member": "Jad", "entry_type": "payment", "amount_usd": -5}),
]


async def main():
    transport = StdioTransport(command=sys.executable, args=["-m", "troupe_coop.server"], cwd=str(ROOT))
    async with Client(transport) as client:
        for title, tool, args in CALLS:
            print(f"\n=== {title}\n{tool}({json.dumps(args, ensure_ascii=False)})")
            result = await client.call_tool(tool, args, raise_on_error=False)
            if result.is_error:
                print("ERROR ->", result.content[0].text)
            else:
                data = result.structured_content
                print("->", data.get("status"), "|", data.get("message", data))
        balances = json.loads((await client.read_resource("troupe://balances"))[0].text)
        print("\n=== Resource troupe://balances")
        for m in balances["members"]:
            print(f"  {m['member']:<16} {m['status']}")


if __name__ == "__main__":
    asyncio.run(main())
