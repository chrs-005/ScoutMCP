import shutil
from pathlib import Path

import pytest

from troupe_coop import server
from troupe_coop.coop import BASE_URL, CoopUnavailableError, parse_product, parse_search

FIXTURES = Path(__file__).parent / "fixtures"
SEED = Path(__file__).resolve().parent.parent / "data" / "seed"

SEARCH_PAGES = {
    "chemise": "search_chemise.html",
    "chemise troupe": "search_chemise_troupe.html",
    "chemise troupe kaki": "search_chemise_troupe_kaki.html",
    "beret": "search_beret.html",
    "barrettes": "search_barrettes.html",
    "chaussettes": "search_chaussettes.html",
}
PRODUCT_PAGES = {
    "/shop/chemise-troupe-kaki-1065": "product_chemise_troupe_kaki.html",
    "/shop/chemise-meute-1066": "product_chemise_meute.html",
    "/shop/barrettes-1081": "product_barrettes.html",
    "/shop/beret-1073": "product_beret.html",
    "/shop/sifflet-850": "product_sifflet.html",
    "/shop/chaussettes-1072": "product_chaussettes.html",
}


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeCoop:
    """Serves saved coop pages instead of hitting the live site."""

    def __init__(self):
        self.down = False
        self.calls = []

    def search(self, query):
        self.calls.append(("search", query))
        if self.down:
            raise CoopUnavailableError("The coop website (https://coop.scoutsduliban.org) could not be reached: ConnectTimeout.")
        page = SEARCH_PAGES.get(query.lower().strip(), "search_empty.html")
        return parse_search(fixture_html(page))

    def get_product(self, url):
        self.calls.append(("product", url))
        path = url.replace(BASE_URL, "").split("?")[0]
        # Category-prefixed links (/shop/uniformes-58/beret-1073) map to the same page.
        slug = "/shop/" + path.rstrip("/").split("/")[-1]
        return parse_product(fixture_html(PRODUCT_PAGES[slug]), url)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    for name in ("members.json", "ledger.json"):
        shutil.copyfile(SEED / name, tmp_path / name)
    monkeypatch.setenv("TROUPE_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_coop(monkeypatch):
    fake = FakeCoop()
    monkeypatch.setattr(server, "coop", fake)
    return fake
