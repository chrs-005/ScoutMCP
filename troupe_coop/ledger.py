"""The troupe's ledger: who ordered what, and who has paid.

Two JSON files live in the data directory (``data/`` by default, or
``$TROUPE_DATA_DIR``):

* ``members.json``: the troupe roster (edited by hand by the chef).
* ``ledger.json``: an append-only list of entries. A ``charge`` is money a
  member owes the troupe (an item ordered for them); a ``payment`` is money
  the chef received from them. Balance = charges - payments, so a positive
  balance means the member owes money and a negative one means they paid in
  advance and have credit.
"""

from __future__ import annotations

import json
import os
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from .coop import normalize

EntryType = Literal["charge", "payment"]

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class LedgerError(Exception):
    """A predictable ledger failure (unknown member, bad amount, ...)."""


def data_dir() -> Path:
    return Path(os.environ.get("TROUPE_DATA_DIR", DEFAULT_DATA_DIR))


def _round(amount: float) -> float:
    return round(amount + 0.0, 2)


class Ledger:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else data_dir()
        self.members_path = self.directory / "members.json"
        self.ledger_path = self.directory / "ledger.json"

    # ----- storage -------------------------------------------------------

    def _read(self, path: Path, default: dict) -> dict:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_entries(self, entries: list[dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.ledger_path)

    def roster(self) -> dict:
        roster = self._read(self.members_path, {"unit": "Troupe", "members": []})
        if not roster["members"]:
            raise LedgerError(f"No members found in {self.members_path}. Add the troupe roster first.")
        return roster

    def entries(self) -> list[dict]:
        return self._read(self.ledger_path, {"entries": []})["entries"]

    # ----- members -------------------------------------------------------

    def resolve_member(self, name: str) -> str:
        """Map what the chef typed ("karim", "Haddad", "Karim Haddad") to one roster name."""
        members = [m["name"] for m in self.roster()["members"]]
        query = normalize(name)
        if not query:
            raise LedgerError("A member name is required.")
        for member in members:
            if normalize(member) == query:
                return member
        matches = [m for m in members if query in normalize(m).split() or normalize(m).startswith(query)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise LedgerError(f"'{name}' matches several members: {', '.join(matches)}. Use the full name.")
        raise LedgerError(
            f"'{name}' is not in the troupe roster. Known members: {', '.join(members)}."
        )

    # ----- writes --------------------------------------------------------

    def add_entry(
        self,
        member: str,
        entry_type: EntryType,
        amount_usd: float,
        description: str,
        item: dict | None = None,
    ) -> dict:
        if entry_type not in ("charge", "payment"):
            raise LedgerError(f"entry_type must be 'charge' or 'payment', not '{entry_type}'.")
        if amount_usd is None or amount_usd <= 0:
            raise LedgerError(f"Amount must be greater than 0 (got {amount_usd}).")
        if amount_usd > 1000:
            raise LedgerError(f"Amount ${amount_usd:.2f} looks wrong for a single coop entry (limit $1000).")
        member_name = self.resolve_member(member)
        entry = {
            "id": uuid.uuid4().hex[:8],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "member": member_name,
            "type": entry_type,
            "amount_usd": _round(amount_usd),
            "description": description.strip() or entry_type,
        }
        if item:
            entry["item"] = item
        entries = self.entries()
        entries.append(entry)
        self._write_entries(entries)
        return entry

    # ----- reads ---------------------------------------------------------

    def balance(self, member: str) -> float:
        member_name = self.resolve_member(member)
        total = 0.0
        for e in self.entries():
            if e["member"] == member_name:
                total += e["amount_usd"] if e["type"] == "charge" else -e["amount_usd"]
        return _round(total)

    @staticmethod
    def describe_balance(balance: float) -> str:
        if balance > 0:
            return f"owes ${balance:.2f}"
        if balance < 0:
            return f"has ${-balance:.2f} credit (paid in advance)"
        return "settled (owes nothing)"

    def balances(self) -> dict:
        roster = self.roster()
        per_member = {m["name"]: {"charged": 0.0, "paid": 0.0, "items": []} for m in roster["members"]}
        for e in self.entries():
            row = per_member.setdefault(e["member"], {"charged": 0.0, "paid": 0.0, "items": []})
            if e["type"] == "charge":
                row["charged"] += e["amount_usd"]
                row["items"].append(e["description"])
            else:
                row["paid"] += e["amount_usd"]
        members = []
        for m in roster["members"]:
            row = per_member[m["name"]]
            balance = _round(row["charged"] - row["paid"])
            members.append(
                {
                    "member": m["name"],
                    "patrol": m.get("patrol"),
                    "charged_usd": _round(row["charged"]),
                    "paid_usd": _round(row["paid"]),
                    "balance_usd": balance,
                    "status": self.describe_balance(balance),
                    "items": row["items"],
                }
            )
        owed = sum(m["balance_usd"] for m in members if m["balance_usd"] > 0)
        credit = -sum(m["balance_usd"] for m in members if m["balance_usd"] < 0)
        return {
            "unit": roster["unit"],
            "total_owed_to_troupe_usd": _round(owed),
            "total_credit_held_usd": _round(credit),
            "members": members,
        }

    def statement(self, member: str) -> dict:
        member_name = self.resolve_member(member)
        rows = [e for e in self.entries() if e["member"] == member_name]
        balance = self.balance(member_name)
        return {
            "member": member_name,
            "entries": rows,
            "balance_usd": balance,
            "status": self.describe_balance(balance),
        }

    def coop_order(self) -> dict:
        """Everything ordered for members, grouped by coop item and variant."""
        lines: dict[tuple, dict] = {}
        for e in self.entries():
            item = e.get("item")
            if e["type"] != "charge" or not item:
                continue
            variant = ", ".join(f"{k}: {v}" for k, v in sorted(item.get("variant", {}).items()))
            key = (item["name"], variant)
            line = lines.setdefault(
                key,
                {
                    "item": item["name"],
                    "variant": variant or None,
                    "unit_price_usd": item["unit_price_usd"],
                    "quantity": 0,
                    "for_members": defaultdict(int),
                    "url": item.get("url"),
                },
            )
            line["quantity"] += item["quantity"]
            line["for_members"][e["member"]] += item["quantity"]
        result = []
        for line in sorted(lines.values(), key=lambda line: (line["item"], line["variant"] or "")):
            line["for_members"] = dict(line["for_members"])
            line["subtotal_usd"] = _round(line["unit_price_usd"] * line["quantity"])
            result.append(line)
        return {
            "lines": result,
            "total_items": sum(line["quantity"] for line in result),
            "total_usd": _round(sum(line["subtotal_usd"] for line in result)),
            "note": "The coop takes cash only. This list is for the chef to send or bring to the coop; nothing is ordered automatically.",
        }
