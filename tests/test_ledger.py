"""The troupe ledger (balances, advance payments, failures)."""

import pytest

from troupe_coop.ledger import Ledger, LedgerError


def test_seed_balances(data_dir):
    ledger = Ledger()
    assert ledger.balance("Jad") == 15.0  # ordered, has not paid yet
    assert ledger.balance("Maya Khoury") == -20.0  # paid in advance -> credit
    assert ledger.balance("lea") == 0.0  # paid when ordering


def test_member_names_are_matched_loosely(data_dir):
    ledger = Ledger()
    assert ledger.resolve_member("karim") == "Karim Haddad"
    assert ledger.resolve_member("HADDAD") == "Karim Haddad"
    assert ledger.resolve_member("Nour Abi Khalil") == "Nour Abi Khalil"


def test_unknown_member_is_a_clear_error(data_dir):
    with pytest.raises(LedgerError, match="not in the troupe roster"):
        Ledger().resolve_member("Ziad")


@pytest.mark.parametrize("amount", [0, -5])
def test_non_positive_amount_is_rejected(data_dir, amount):
    with pytest.raises(LedgerError, match="greater than 0"):
        Ledger().add_entry("Jad", "payment", amount, "bad")


def test_late_payment_settles_balance(data_dir):
    ledger = Ledger()
    ledger.add_entry("Jad", "payment", 15, "Cash")
    assert ledger.balance("Jad") == 0.0
    assert "settled" in ledger.statement("Jad")["status"]


def test_advance_credit_is_used_by_a_later_charge(data_dir):
    ledger = Ledger()
    ledger.add_entry("Maya", "charge", 15, "Chemise")
    assert ledger.balance("Maya") == -5.0
    assert "credit" in Ledger.describe_balance(-5.0)


def test_balances_and_coop_order_summaries(data_dir):
    ledger = Ledger()
    summary = ledger.balances()
    assert summary["total_owed_to_troupe_usd"] == 15.0
    assert summary["total_credit_held_usd"] == 20.0
    order = ledger.coop_order()
    assert order["total_items"] == 2
    assert order["total_usd"] == 20.0
    short = next(line for line in order["lines"] if line["item"] == "Short")
    assert short["variant"] == "Size: 14" and short["for_members"] == {"Jad Saliba": 1}
