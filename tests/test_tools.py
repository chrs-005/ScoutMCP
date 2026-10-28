"""The three MCP tools and the resources, called through a real FastMCP client (in memory)."""

import json

import pytest
from fastmcp import Client

from troupe_coop.ledger import Ledger
from troupe_coop.server import mcp


async def call(name, args, **kw):
    async with Client(mcp) as client:
        return await client.call_tool(name, args, **kw)


def error_text(result):
    assert result.is_error
    return result.content[0].text


# ----- Data tool: check_coop_item ------------------------------------------


async def test_list_exactly_three_tools():
    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}
    assert tools == {"check_coop_item", "record_ledger_entry", "process_member_order"}


async def test_available_size(fake_coop):
    r = (await call("check_coop_item", {"item": "Chemise Troupe Kaki", "variant": ["M"]})).structured_content
    assert r["status"] == "available"
    assert r["unit_price_usd"] == 15.0 and r["variant"] == {"Size": "M"}


async def test_size_aliases_are_understood(fake_coop):
    r = (await call("check_coop_item", {"item": "Chemise Troupe Kaki", "variant": ["medium"]})).structured_content
    assert r["variant"] == {"Size": "M"}
    r = (await call("check_coop_item", {"item": "Chemise Troupe Kaki", "variant": ["xs"]})).structured_content
    assert r["variant"] == {"Size": "16 (XS)"}
    r = (await call("check_coop_item", {"item": "chaussettes", "variant": ["36-40"]})).structured_content
    assert r["status"] == "available" and r["variant"] == {"Size": "36-40 EU"}


async def test_size_not_offered_suggests_closest(fake_coop):
    r = (await call("check_coop_item", {"item": "Chemise Troupe Kaki", "variant": ["8"]})).structured_content
    assert r["status"] == "unavailable"
    assert r["suggestions"] == ["10"]
    assert "not offered" in r["message"]


async def test_missing_variant_lists_options(fake_coop):
    r = (await call("check_coop_item", {"item": "Chemise Troupe Kaki"})).structured_content
    assert r["status"] == "needs_variant"
    assert "M" in r["options"]["Size"]


async def test_ambiguous_name_lists_candidates(fake_coop):
    r = (await call("check_coop_item", {"item": "chemise troupe"})).structured_content
    assert r["status"] == "ambiguous"
    assert {c["name"] for c in r["candidates"]} == {"Chemise Troupe Bleue", "Chemise Troupe Kaki"}


async def test_discontinued_combination_is_unavailable(fake_coop):
    product = fake_coop.get_product("https://coop.scoutsduliban.org/shop/barrettes-1081")
    archived = product.archived[0]
    r = (await call("check_coop_item", {"item": "Barrettes", "variant": list(archived.values())})).structured_content
    assert r["status"] == "unavailable"
    assert "discontinued" in r["message"]
    r = (await call("check_coop_item", {"item": "Barrettes", "variant": ["Troupe", "Chef/Cheftaine"]})).structured_content
    assert r["status"] == "available"


async def test_unknown_item_is_a_clear_error(fake_coop):
    r = await call("check_coop_item", {"item": "zzz nothing"}, raise_on_error=False)
    assert "No coop item matches" in error_text(r)


async def test_coop_site_down_is_a_clear_error(fake_coop):
    fake_coop.down = True
    r = await call("check_coop_item", {"item": "beret", "variant": ["58"]}, raise_on_error=False)
    assert "could not be reached" in error_text(r)


# ----- Action tool: record_ledger_entry -------------------------------------


async def test_record_payment(data_dir):
    r = (await call("record_ledger_entry", {"member": "jad", "entry_type": "payment", "amount_usd": 10})).structured_content
    assert r["member"] == "Jad Saliba"
    assert r["balance_usd"] == 5.0 and r["status"] == "owes $5.00"


async def test_record_entry_unknown_member(data_dir):
    r = await call("record_ledger_entry", {"member": "Ziad", "entry_type": "payment", "amount_usd": 5}, raise_on_error=False)
    assert "not in the troupe roster" in error_text(r)


async def test_record_entry_rejects_negative_amount(data_dir):
    before = len(Ledger().entries())
    r = await call("record_ledger_entry", {"member": "Jad", "entry_type": "payment", "amount_usd": -5}, raise_on_error=False)
    assert "greater than 0" in error_text(r)
    assert len(Ledger().entries()) == before


# ----- Orchestration tool: process_member_order ------------------------------


async def test_order_with_partial_payment(data_dir, fake_coop):
    args = {"member": "Karim", "item": "Chemise Troupe Kaki", "variant": ["S"], "quantity": 2, "paid_now_usd": 20}
    r = (await call("process_member_order", args)).structured_content
    assert r["status"] == "recorded"
    assert r["total_usd"] == 30.0 and r["balance_usd"] == 10.0
    assert len(r["steps"]) == 3  # check -> charge -> payment
    entries = [e for e in Ledger().entries() if e["member"] == "Karim Haddad"]
    assert [e["type"] for e in entries] == ["charge", "payment"]
    assert entries[0]["item"]["variant"] == {"Size": "S"}


async def test_order_uses_advance_credit(data_dir, fake_coop):
    r = (await call("process_member_order", {"member": "Maya", "item": "beret", "variant": ["59"]})).structured_content
    assert r["status"] == "recorded"
    assert r["balance_usd"] == -15.0  # $20 advance - $5 beret


async def test_unavailable_size_records_nothing(data_dir, fake_coop):
    before = len(Ledger().entries())
    r = (await call("process_member_order", {"member": "Rami", "item": "Chemise Troupe Kaki", "variant": ["8"]})).structured_content
    assert r["status"] == "not_recorded"
    assert r["item_check"]["suggestions"] == ["10"]
    assert len(Ledger().entries()) == before


async def test_unknown_member_fails_before_contacting_coop(data_dir, fake_coop):
    r = await call("process_member_order", {"member": "Ziad", "item": "beret", "variant": ["58"]}, raise_on_error=False)
    assert "not in the troupe roster" in error_text(r)
    assert fake_coop.calls == []


async def test_order_when_coop_is_down(data_dir, fake_coop):
    fake_coop.down = True
    r = await call("process_member_order", {"member": "Jad", "item": "beret", "variant": ["58"]}, raise_on_error=False)
    assert "could not be reached" in error_text(r)
    assert Ledger().balance("Jad") == 15.0  # unchanged


@pytest.mark.parametrize("bad", [{"quantity": 0}, {"paid_now_usd": -1}])
async def test_order_argument_validation(data_dir, fake_coop, bad):
    args = {"member": "Jad", "item": "beret", "variant": ["58"], **bad}
    r = await call("process_member_order", args, raise_on_error=False)
    assert r.is_error


# ----- Resources -------------------------------------------------------------


async def test_resources(data_dir):
    async with Client(mcp) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert {"troupe://members", "troupe://balances", "troupe://coop-order"} <= uris
        balances = json.loads((await client.read_resource("troupe://balances"))[0].text)
        statement = json.loads((await client.read_resource("troupe://members/jad/statement"))[0].text)
    assert balances["total_owed_to_troupe_usd"] == 15.0
    assert statement["member"] == "Jad Saliba" and statement["balance_usd"] == 15.0
