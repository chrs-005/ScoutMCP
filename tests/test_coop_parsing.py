"""Parsing the coop's Odoo pages (offline, from saved fixtures)."""

from troupe_coop.coop import parse_product, parse_search, rank_hits

from .conftest import fixture_html


def test_search_results_are_parsed():
    hits = parse_search(fixture_html("search_chemise.html"))
    names = {h.name: h.price for h in hits}
    assert names["Chemise Troupe Kaki"] == 15.0
    assert "Chemise Meute" in names
    assert all(h.url.startswith("https://coop.scoutsduliban.org/shop/") for h in hits)


def test_empty_search_returns_no_hits():
    assert parse_search(fixture_html("search_empty.html")) == []


def test_product_sizes_are_parsed():
    url = "https://coop.scoutsduliban.org/shop/chemise-troupe-kaki-1065"
    product = parse_product(fixture_html("product_chemise_troupe_kaki.html"), url)
    assert product.name == "Chemise Troupe Kaki"
    assert product.price == 15.0
    sizes = product.attributes["Size"]
    assert "M" in sizes and "16 (XS)" in sizes
    assert "8" not in sizes and "4XL" not in sizes  # the kaki shirt skips these sizes


def test_multi_attribute_product_and_archived_combinations():
    product = parse_product(fixture_html("product_barrettes.html"), "https://coop.scoutsduliban.org/shop/barrettes-1081")
    assert set(product.attributes) == {"Unité", "Fonction"}
    assert "Troupe" in product.attributes["Unité"]
    assert product.archived, "barrettes have discontinued unit/function combinations"
    assert all(set(combo) == {"Unité", "Fonction"} for combo in product.archived)


def test_product_without_variants():
    product = parse_product(fixture_html("product_sifflet.html"), "https://coop.scoutsduliban.org/shop/sifflet-850")
    assert product.name == "Sifflet"
    assert product.attributes == {}


def test_ranking_exact_partial_and_ambiguous():
    hits = parse_search(fixture_html("search_chemise_troupe.html"))
    assert len(rank_hits("chemise troupe", hits)) == 2  # bleue and kaki -> ambiguous
    assert [h.name for h in rank_hits("chemise troupe kaki", hits)] == ["Chemise Troupe Kaki"]
    assert [h.name for h in rank_hits("CHEMISE TROUPE BLEUE", hits)] == ["Chemise Troupe Bleue"]
