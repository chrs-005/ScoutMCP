# Troupe Coop Assistant: an MCP toolkit for a scout leader

**EECE 503P/798S Agentic Systems, C5: Agent Tools.** FastMCP server and OpenAI Agents SDK host.

**Demo video:** https://youtu.be/Yk7hFkNVe3c

## Why this project

I'm a scout chef (troupe leader) with Scouts du Liban, and this is a problem I have right now. Every few weeks, members need uniform pieces and gear from the SDL coop: a *Chemise Troupe Kaki* in size 12, a *Beret*, a *Bague Foulard*. I collect the requests, check what the coop actually stocks and in which sizes, look up prices, and then try to remember who paid in advance, who paid half, and who still owes me money.

Today that lives in WhatsApp messages and memory. This project turns it into an agent I can simply talk to:

> "Jad wants a khaki troupe shirt size 8, he gave me 10 dollars."
> The agent checks the live coop catalog. Size 8 isn't made for that shirt, so it suggests size 10 and, once I confirm, records the order and the payment. Jad now owes $5.

## Submission at a glance

| Deliverable | Where |
|---|---|
| Written summary (Part 1: HF article + Fetch server critique, 371 words) | [docs/part1_summary.md](docs/part1_summary.md) |
| FastMCP server module (3 tools + resources) | [troupe_coop/server.py](troupe_coop/server.py) |
| OpenAI Agents SDK host/client | [agent.py](agent.py) |
| Configuration and setup instructions | this README ([Setup](#setup), [Run](#run)) |
| Tests and example scripts, including failure cases | [tests/](tests/) (35 tests), [scripts/demo_tools.py](scripts/demo_tools.py) |
| Live agent run (real transcript of the round trip) | [docs/example_session.md](docs/example_session.md) |
| Screencast video (6:54) | **https://youtu.be/Yk7hFkNVe3c** (script: [docs/demo_script.md](docs/demo_script.md)) |
| Reflection (2 paragraphs) | [docs/reflection.md](docs/reflection.md) |

### Requirements checklist

| Requirement from the assignment | How this project meets it |
|---|---|
| Exactly three tools: one Data, one Action, one Orchestration | `check_coop_item` (Data), `record_ledger_entry` (Action), `process_member_order` (Orchestration). `test_list_exactly_three_tools` checks the count. |
| Data tool retrieves information without changing anything | Only GET requests to the coop catalog; annotated `readOnlyHint: true`. |
| Action tool changes something | Appends a charge/payment entry to `data/ledger.json`. |
| Orchestration tool coordinates the other two in sequence | Calls `check_coop_item`, then `record_ledger_entry` (charge), then `record_ledger_entry` (payment). `test_orchestration_calls_the_data_then_action_tool` proves the call order. |
| Clear description, typed arguments, typed output for each tool | Docstrings + `Annotated[..., Field(description=...)]` arguments + Pydantic output models (`ItemCheck`, `LedgerEntryResult`, `OrderResult`). FastMCP publishes input and output schemas. |
| Single-purpose tools | Each tool has one job. Combining happens only in the Orchestration tool. Balances and order summaries are resources, not extra tools. |
| At least one predictable failure handled with a clear error | Several: item not found, coop site unreachable, unknown member, amount ≤ 0, size not offered, discontinued variant, ambiguous name. See [Tests](#tests). |
| `@mcp.tool` for tools, `@mcp.resource` for pure data lookups | 3 `@mcp.tool`, 4 `@mcp.resource` (`troupe://members`, `troupe://balances`, `troupe://coop-order`, `troupe://members/{member}/statement`). |
| Agents SDK agent as MCP Host/Client routing requests to the right tool | `agent.py`: `Agent(mcp_servers=[MCPServerStdio(...)])`. The model chooses the tool for each request; see [docs/example_session.md](docs/example_session.md). |
| Unit tests or scripts for each tool, including the failure case | `tests/test_tools.py` (all 3 tools through a real FastMCP client), `tests/test_ledger.py`, `tests/test_coop_parsing.py`, `scripts/demo_tools.py`. |

### Why single-purpose tools

A tool that does one thing has a short, unambiguous description, so the model picks the right tool more reliably. Its failures are also easier to make predictable and to test in isolation. A tool that "checks the price **and** charges the member **and** records the payment" would hide three decisions inside one call. Here that sequence is an explicit Orchestration tool built from two single-purpose tools, and each of those tools stays usable on its own: a late payment is just `record_ledger_entry`.

## Architecture

```
 Chef (terminal)
     |
     v
 agent.py  = MCP HOST  (OpenAI Agents SDK Agent + LLM)
     |        contains the MCP CLIENT (MCPServerStdio)
     |  MCP over stdio (JSON-RPC)
     v
 troupe_coop/server.py = MCP SERVER (FastMCP)
     |-- check_coop_item ------> coop.scoutsduliban.org (live, read-only scraping)
     |-- record_ledger_entry --> data/ledger.json (local)
     '-- process_member_order -> calls the two tools above
     resources: troupe://members, troupe://balances, troupe://coop-order,
                troupe://members/{member}/statement
```

## The three tools

| Category | Tool | What it does | Failure handling |
|---|---|---|---|
| **Data** | `check_coop_item(item, variant?)` | Looks up one item on the live coop site and returns its price, the variants offered (sizes, colours, unit…) and whether the requested variant exists. Read-only. | Returns `unavailable` with the closest sizes (e.g. the Chemise Troupe Kaki has no size 8, so it suggests 10), `needs_variant`, `ambiguous` with candidates, or `discontinued`. Raises a clear error when no item matches or the coop site is unreachable. |
| **Action** | `record_ledger_entry(member, entry_type, amount_usd, description)` | Writes one `charge` or `payment` to a member's account and returns the new balance. A positive balance means the member owes the troupe; a negative one means they paid in advance and have credit. Never contacts the coop. | Unknown member (lists the roster), ambiguous member name, amount ≤ 0 or > $1000 (schema validation). Nothing is written on failure. |
| **Orchestration** | `process_member_order(member, item, variant?, quantity, paid_now_usd)` | (1) validates the member, (2) calls `check_coop_item`, (3) if available, calls the ledger action to charge price × quantity, (4) records `paid_now_usd` as a payment. Returns the steps it took. | If the item or size isn't available, **nothing is recorded** and the reason and alternatives come back. An unknown member fails before any request reaches the coop site. |

Read-only views are exposed as **MCP resources** (`@mcp.resource`), not tools. They don't count toward the three tools, and the host reads them as context on every model call:

- `troupe://members`: the roster
- `troupe://balances`: who owes what, and who has credit
- `troupe://coop-order`: everything ordered, grouped by item and size, ready to bring to the coop (the coop takes cash only)
- `troupe://members/{member}/statement`: one member's history

The agent always replies in English. Only official coop item names stay in French (the coop's catalog language), with an English gloss, e.g. *Chemise Troupe Kaki (khaki troop shirt)*.

## Setup

Requires Python 3.11+ and an OpenAI API key.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # then put your OPENAI_API_KEY in .env
python scripts/reset_demo.py    # creates data/members.json + data/ledger.json from data/seed/
```

> **Antivirus or corporate proxy note.** If `pip install` fails with `InvalidChunkLength` or certificate errors (AVG and Avast intercept HTTPS), install with uv using the OS certificate store: `pip install uv`, then `uv pip install --system-certs -r requirements.txt`. The app itself uses `truststore`, so it trusts the same OS certificates.

Optional: set `OPENAI_MODEL` in `.env`. If it isn't set, the Agents SDK default model is used.

## Run

```bash
python agent.py --check        # starts the MCP server, lists tools/resources (no LLM, no key needed)
python agent.py                # chat with the assistant
python scripts/demo_tools.py   # calls every tool + failure case over stdio, no LLM
```

In the chat, every MCP tool call (`-> agent calls MCP tool …`) and every server response (`<- server returned …`) is printed. The server's own log lines (`[MCP server] …`) appear too, so the full round trip is visible. Example requests:

- `Jad needs a khaki troupe shirt size 8`
- `Maya wants a beret size 59 and a bague foulard`
- `Karim gave me 20$ in advance`
- `Who still owes money?`
- `What do I need to buy from the coop?`
- `How much is the chemise troupe?` (ambiguous: the agent asks whether you mean Bleue or Kaki)

## Tests

```bash
pytest                         # 35 offline tests: coop HTML parsing, ledger, all 3 tools + resources via a FastMCP client
$env:RUN_LIVE=1; pytest tests/test_live.py    # optional, PowerShell: hits the real coop site (bash: RUN_LIVE=1 pytest tests/test_live.py)
```

The offline tests use saved coop pages (`tests/fixtures/`), so they don't depend on the website. Failure cases covered:

- size not offered
- discontinued variant
- ambiguous item name
- item not found
- coop site down
- unknown member
- negative or zero amounts
- quantity 0
- an order for an unavailable size leaves the ledger untouched

## Project structure

```
agent.py                  MCP host/client (OpenAI Agents SDK)
troupe_coop/server.py     FastMCP server: 3 tools + 4 resources
troupe_coop/coop.py       read-only coop scraper (Odoo eCommerce HTML)
troupe_coop/ledger.py     JSON ledger: members, charges, payments, balances
data/seed/                demo roster (fictional members) and starting ledger
scripts/reset_demo.py     restore demo data before recording
scripts/demo_tools.py     no-LLM tool walkthrough including failure cases
tests/                    pytest suite + saved coop HTML fixtures
docs/part1_summary.md     Part 1: MCP article + Fetch server critique
docs/reflection.md        reflection
docs/demo_script.md       screencast script
docs/example_session.md   real transcript of a live agent run
```

## Design notes

- **Read-only toward the coop.** The scraper only issues GET requests to public catalog pages. It never adds to the cart, fills in forms or places orders. Submitting the order stays the chef's job, on purpose. The coop's main domain allows crawling in `robots.txt`, responses are cached for 10 minutes, and the scraper sends an identifying User-Agent.
- **Ledger, not order and payment tables.** A single append-only list of `charge` and `payment` entries keeps the Action tool single-purpose. It also handles both late payers and members who pay in advance (credit) with one rule: balance = charges − payments.
- **Structured output.** Every tool returns a typed Pydantic model (FastMCP publishes the output schema) with a human-readable `message` plus machine-readable fields (`status`, `suggestions`, `candidates`, `balance_usd`, `steps`).
- Member names in `data/seed/members.json` are fictional.
