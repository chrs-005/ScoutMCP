"""Optional checks against the real coop website: RUN_LIVE=1 pytest tests/test_live.py"""

import os

import pytest

from troupe_coop.coop import CoopClient, CoopUnavailableError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to hit the live coop site"),
]


def test_live_search_and_product():
    client = CoopClient()
    hits = client.search("chemise troupe kaki")
    kaki = next(h for h in hits if h.name == "Chemise Troupe Kaki")
    product = client.get_product(kaki.url)
    assert product.price > 0
    assert "M" in product.attributes["Size"]


def test_unreachable_site_raises_clear_error():
    client = CoopClient(base_url="https://coop.invalid", timeout=3)
    with pytest.raises(CoopUnavailableError, match="could not be reached"):
        client.search("beret")
