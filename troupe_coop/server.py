"""FastMCP server: the troupe coop toolkit.

Exactly three tools, one per category from class:

* Data          -> ``check_coop_item``       (reads the live coop catalog, changes nothing)
* Action        -> ``record_ledger_entry``   (writes one charge/payment to the troupe ledger)
* Orchestration -> ``process_member_order``  (check item -> charge member -> record upfront payment)

Read-only views of the ledger are exposed as MCP resources, not tools:
``troupe://members``, ``troupe://balances``, ``troupe://coop-order`` and
``troupe://members/{member}/statement``.

Run with:  python -m troupe_coop.server   (stdio transport)
"""

from __future__ import annotations

import logging
import sys
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from .coop import CoopClient, CoopError, Product, normalize, rank_hits
from .ledger import Ledger, LedgerError

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="  [MCP server] %(message)s")
log = logging.getLogger("troupe_coop")
logging.getLogger("httpx").setLevel(logging.WARNING)

mcp = FastMCP(
    name="troupe-coop",
    instructions=(
        "Tools for a Scouts du Liban troupe leader (chef) to manage members' orders from the "
        "SDL coop and track who has paid. Coop item names are in French."
    ),
)

coop = CoopClient()

# Common size words -> how the coop labels them.
SIZE_ALIASES = {"small": "S", "medium": "M", "large": "L", "xlarge": "XL", "xxl": "2XL", "xxxl": "3XL"}
SIZE_LADDER = ["6", "8", "10", "12", "14", "16", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL", "6XL"]


# ----- output models -------------------------------------------------------


class Candidate(BaseModel):
    name: str
    unit_price_usd: float
    url: str


class ItemCheck(BaseModel):
    status: Literal["available", "unavailable", "needs_variant", "ambiguous"]
    message: str
    item: str | None = None
    url: str | None = None
    unit_price_usd: float | None = None
    variant: dict[str, str] = Field(default_factory=dict, description="The variant that was checked, e.g. {'Size': 'M'}.")
    options: dict[str, list[str]] = Field(default_factory=dict, description="Every variant the coop offers for this item.")
    suggestions: list[str] = Field(default_factory=list, description="Closest offered values when the requested one is missing.")
    candidates: list[Candidate] = Field(default_factory=list, description="Possible items when the name was ambiguous.")


class LedgerEntryResult(BaseModel):
    message: str
    entry_id: str
    member: str
    entry_type: Literal["charge", "payment"]
    amount_usd: float
    description: str
    balance_usd: float = Field(description="Member balance after this entry: >0 owes, <0 credit.")
    status: str


class OrderResult(BaseModel):
    status: Literal["recorded", "not_recorded"]
    message: str
    member: str
    item_check: ItemCheck
    quantity: int
    total_usd: float = 0.0
    paid_now_usd: float = 0.0
    balance_usd: float | None = None
    balance_status: str | None = None
    steps: list[str] = Field(default_factory=list, description="What the orchestration did, in order.")


# ----- variant matching ----------------------------------------------------


def _match_value(requested: str, offered: list[str]) -> str | None:
    """Match "m", "Medium", "xs", "Size M" or "16" against the coop's labels."""
    req = normalize(requested)
    for prefix in ("size ", "taille ", "color ", "couleur "):
        if req.startswith(prefix):
            req = req[len(prefix):]
    req = normalize(SIZE_ALIASES.get(req, req))
    for value in offered:
        v = normalize(value)
        inner = v[v.find("(") + 1 : v.find(")")] if "(" in v else None
        # "xs" -> "16 (XS)", "16" -> "16 (XS)", "36-40" -> "36-40 EU"
        if req == v or req == inner or req == v.split(" (")[0] or v.startswith(req + " "):
            return value
    return None


def _ladder_pos(value: str) -> int | None:
    v = normalize(value).split(" (")[0].upper()
    v = SIZE_ALIASES.get(v.lower(), v)
    return SIZE_LADDER.index(v) if v in SIZE_LADDER else None


def _closest(requested: str, offered: list[str]) -> list[str]:
    pos = _ladder_pos(requested)
    if pos is None:
        return []
    ranked = [(abs(p - pos), value) for value in offered if (p := _ladder_pos(value)) is not None]
    if not ranked:
        return []
    best = min(d for d, _ in ranked)
    return [value for d, value in ranked if d == best]


def _check_variant(product: Product, requested: list[str]) -> ItemCheck:
    base = dict(item=product.name, url=product.url, unit_price_usd=product.price, options=product.attributes)
    chosen: dict[str, str] = {}
    for value in requested:
        matched = False
        for attr, offered in product.attributes.items():
            hit = _match_value(value, offered)
            if hit and attr not in chosen:
                chosen[attr] = hit
                matched = True
                break
        if matched:
            continue
        # Not offered: say which attribute we think it was for and what is closest.
        attr = next(iter(product.attributes)) if len(product.attributes) == 1 else (
            "Size" if "Size" in product.attributes and _ladder_pos(value) is not None else None
        )
        if attr:
            suggestions = _closest(value, product.attributes[attr])
            msg = (
                f"{product.name} is not offered in {attr} '{value}'. "
                f"Offered {attr} values: {', '.join(product.attributes[attr])}."
            )
            if suggestions:
                msg += f" Closest: {', '.join(suggestions)}."
        else:
            suggestions = []
            msg = f"'{value}' is not a variant of {product.name}. Options: {product.attributes or 'none (single item)'}."
        return ItemCheck(status="unavailable", message=msg, variant=chosen, suggestions=suggestions, **base)

    missing = [attr for attr in product.attributes if attr not in chosen]
    if missing:
        listing = "; ".join(f"{a}: {', '.join(product.attributes[a])}" for a in missing)
        return ItemCheck(
            status="needs_variant",
            message=f"{product.name} (${product.price:.2f}) comes in several variants. Please choose {listing}.",
            variant=chosen,
            **base,
        )

    if chosen in product.archived:
        return ItemCheck(
            status="unavailable",
            message=f"{product.name} ({_fmt_variant(chosen)}) has been discontinued by the coop.",
            variant=chosen,
            **base,
        )

    label = f"{product.name} ({_fmt_variant(chosen)})" if chosen else product.name
    return ItemCheck(
        status="available",
        message=f"{label} is offered by the coop at ${product.price:.2f} each.",
        variant=chosen,
        **base,
    )


def _fmt_variant(variant: dict[str, str]) -> str:
    return ", ".join(f"{k}: {v}" for k, v in variant.items())


# ----- the three tools -----------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
def check_coop_item(
    item: Annotated[
        str,
        Field(
            min_length=2,
            description="Item name in French as listed by the coop, e.g. 'Chemise Troupe Kaki', 'Beret', 'Sifflet'. "
            "Translate English requests first (shirt -> chemise, troop -> troupe, whistle -> sifflet).",
        ),
    ],
    variant: Annotated[
        list[str] | None,
        Field(description="Requested variant values, e.g. ['M'] for a size, or ['Troupe', 'Chef/Cheftaine']. Omit to list options."),
    ] = None,
) -> ItemCheck:
    """Look up one item in the live Scouts du Liban coop catalog and report its price and whether the
    requested variant (size, color, unit...) is offered. Read-only: it never orders or changes anything.

    status is one of: 'available', 'unavailable' (size/variant not offered or discontinued, with
    suggestions), 'needs_variant' (item has sizes/colors and none was given; options are listed),
    or 'ambiguous' (several items match; candidates are listed).
    """
    log.info("check_coop_item(item=%r, variant=%r)", item, variant)
    try:
        hits = coop.search(item)
        if not hits:
            raise ToolError(
                f"No coop item matches '{item}'. Coop names are in French; try a shorter or French name "
                "(e.g. 'chemise', 'foulard', 'beret')."
            )
        best = rank_hits(item, hits)
        if not best:
            best = hits
        if len(best) > 1:
            return ItemCheck(
                status="ambiguous",
                message=f"'{item}' matches {len(best)} coop items. Which one?",
                candidates=[Candidate(name=h.name, unit_price_usd=h.price, url=h.url) for h in best[:8]],
            )
        product = coop.get_product(best[0].url)
    except CoopError as exc:
        raise ToolError(str(exc)) from exc
    return _check_variant(product, variant or [])


def _record_entry(member: str, entry_type: str, amount_usd: float, description: str, item: dict | None = None) -> LedgerEntryResult:
    """Shared implementation of the Action tool (the orchestration passes item metadata too)."""
    ledger = Ledger()
    try:
        entry = ledger.add_entry(member, entry_type, amount_usd, description, item=item)
        balance = ledger.balance(entry["member"])
    except LedgerError as exc:
        raise ToolError(str(exc)) from exc
    status = ledger.describe_balance(balance)
    verb = "Charged" if entry["type"] == "charge" else "Received payment of"
    return LedgerEntryResult(
        message=f"{verb} ${entry['amount_usd']:.2f} ({entry['description']}) for {entry['member']}. They now {status}.",
        entry_id=entry["id"],
        member=entry["member"],
        entry_type=entry["type"],
        amount_usd=entry["amount_usd"],
        description=entry["description"],
        balance_usd=balance,
        status=status,
    )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def record_ledger_entry(
    member: Annotated[str, Field(description="Troupe member name as in the roster (first name is enough if unique).")],
    entry_type: Annotated[
        Literal["charge", "payment"],
        Field(description="'charge' = the member owes this amount; 'payment' = the chef received this amount from the member."),
    ],
    amount_usd: Annotated[float, Field(gt=0, le=1000, description="Amount in US dollars, greater than 0.")],
    description: Annotated[str, Field(description="Short reason, e.g. 'Cash payment' or 'Camp fee'.")] = "",
) -> LedgerEntryResult:
    """Write ONE entry to a troupe member's account in the local ledger and return their new balance.
    Use 'payment' when a member pays (late or in advance); use 'charge' for a cost that is not a coop
    item. For coop items use process_member_order instead. Does not contact the coop."""
    log.info("record_ledger_entry(member=%r, type=%s, amount=%s)", member, entry_type, amount_usd)
    return _record_entry(member, entry_type, amount_usd, description)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
def process_member_order(
    member: Annotated[str, Field(description="Troupe member the item is for.")],
    item: Annotated[str, Field(min_length=2, description="Coop item name in French, e.g. 'Chemise Troupe Kaki'.")],
    variant: Annotated[list[str] | None, Field(description="Variant values such as ['M'] for size.")] = None,
    quantity: Annotated[int, Field(ge=1, le=20)] = 1,
    paid_now_usd: Annotated[float, Field(ge=0, le=1000, description="Cash the member handed over now (0 if paying later).")] = 0,
) -> OrderResult:
    """Handle a member's coop order end to end: (1) check the item, size and live price with
    check_coop_item, (2) if available, charge the member price x quantity with record_ledger_entry,
    (3) record any cash paid now as a payment. If the item/size is not available nothing is recorded
    and the reason plus alternatives are returned."""
    log.info("process_member_order(member=%r, item=%r, variant=%r, qty=%s, paid_now=%s)", member, item, variant, quantity, paid_now_usd)
    ledger = Ledger()
    try:
        member_name = ledger.resolve_member(member)  # fail fast before hitting the coop site
    except LedgerError as exc:
        raise ToolError(str(exc)) from exc

    steps = []
    check = check_coop_item(item, variant)
    steps.append(f"check_coop_item -> {check.status}: {check.message}")
    if check.status != "available":
        return OrderResult(
            status="not_recorded",
            message=f"Nothing recorded for {member_name}: {check.message}",
            member=member_name,
            item_check=check,
            quantity=quantity,
            steps=steps,
        )

    total = round(check.unit_price_usd * quantity, 2)
    label = f"{quantity} x {check.item}" + (f" ({_fmt_variant(check.variant)})" if check.variant else "")
    item_meta = {
        "name": check.item,
        "variant": check.variant,
        "quantity": quantity,
        "unit_price_usd": check.unit_price_usd,
        "url": check.url,
    }
    result = _record_entry(member_name, "charge", total, label, item=item_meta)
    steps.append(f"record_ledger_entry(charge ${total:.2f}) -> {result.status}")
    if paid_now_usd > 0:
        result = _record_entry(member_name, "payment", paid_now_usd, f"Paid when ordering {label}")
        steps.append(f"record_ledger_entry(payment ${paid_now_usd:.2f}) -> {result.status}")

    return OrderResult(
        status="recorded",
        message=f"Recorded {label} for {member_name}: ${total:.2f}. {member_name} now {result.status}.",
        member=member_name,
        item_check=check,
        quantity=quantity,
        total_usd=total,
        paid_now_usd=paid_now_usd,
        balance_usd=result.balance_usd,
        balance_status=result.status,
        steps=steps,
    )


# ----- resources (pure data lookups) ---------------------------------------


@mcp.resource("troupe://members", mime_type="application/json", description="The troupe roster.")
def members_resource() -> dict:
    return Ledger().roster()


@mcp.resource("troupe://balances", mime_type="application/json", description="Every member's balance: who owes money and who has credit.")
def balances_resource() -> dict:
    return Ledger().balances()


@mcp.resource("troupe://coop-order", mime_type="application/json", description="All items charged to members, grouped by item and size, ready to send to the coop.")
def coop_order_resource() -> dict:
    return Ledger().coop_order()


@mcp.resource("troupe://members/{member}/statement", mime_type="application/json", description="All ledger entries and the balance for one member.")
def statement_resource(member: str) -> dict:
    return Ledger().statement(member)


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
