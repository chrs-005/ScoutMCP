"""Read-only client for the Scouts du Liban coop shop.

The coop runs a standard Odoo eCommerce site, so every page we need is plain
server-rendered HTML:

* ``/shop?search=<words>`` lists product cards (name, price, link).
* ``/shop/<slug>`` is a product page with its variant attributes
  (Size, Color, Unité, ...) and the list of archived (discontinued) variant
  combinations.

Nothing in this module ever writes to the coop site.
"""

from __future__ import annotations

import json
import re
import ssl
import time
import unicodedata
from dataclasses import dataclass, field

import httpx
import truststore
from bs4 import BeautifulSoup

BASE_URL = "https://coop.scoutsduliban.org"
USER_AGENT = "TroupeCoopAssistant/1.0 (EECE 503P student project; read-only)"
CACHE_SECONDS = 600


class CoopError(Exception):
    """Base class for coop lookup failures."""


class CoopUnavailableError(CoopError):
    """The coop website could not be reached or returned an error."""


@dataclass
class SearchHit:
    name: str
    url: str
    price: float


@dataclass
class Product:
    name: str
    url: str
    price: float
    # attribute name -> list of offered values, in the coop's display order
    attributes: dict[str, list[str]] = field(default_factory=dict)
    # combinations of {attribute: value} that the coop has archived
    archived: list[dict[str, str]] = field(default_factory=list)


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace ("Imperméable" -> "impermeable")."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def _parse_price(text: str) -> float:
    return float(text.replace(",", "").strip())


def parse_search(html: str, base_url: str = BASE_URL) -> list[SearchHit]:
    """Extract product cards from a ``/shop?search=`` results page."""
    soup = BeautifulSoup(html, "html.parser")
    hits = []
    for card in soup.select(".oe_product_cart"):
        link = card.select_one("a.oe_product_image_link") or card.select_one("a[href^='/shop/']")
        price = card.select_one(".oe_currency_value")
        if not link or not price:
            continue
        hits.append(
            SearchHit(
                name=card.get("aria-label") or link.get("title", "").strip(),
                url=base_url + link["href"],
                price=_parse_price(price.get_text()),
            )
        )
    return hits


def parse_product(html: str, url: str) -> Product:
    """Extract name, price, variant attributes and archived combinations from a product page."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1")
    price = soup.select_one(".product_price .oe_currency_value") or soup.select_one(".oe_currency_value")
    if not title or not price:
        raise CoopError(f"Could not read product details from {url}")

    attributes: dict[str, list[str]] = {}
    value_by_id: dict[str, tuple[str, str]] = {}
    for li in soup.select("li.variant_attribute"):
        attr_name = li.get("data-attribute-name", "").strip()
        values = []
        for inp in li.select("input[data-value-id], option[data-value-id]"):
            value = (inp.get("data-value-name") or inp.get_text()).strip()
            values.append(value)
            value_by_id[inp["data-value-id"]] = (attr_name, value)
        attributes[attr_name] = values

    archived = []
    variants = soup.select_one("ul.js_add_cart_variants")
    if variants and variants.get("data-attribute-exclusions"):
        data = json.loads(variants["data-attribute-exclusions"])
        for combo in data.get("archived_combinations", []):
            pairs = [value_by_id.get(str(value_id)) for value_id in combo]
            if pairs and all(pairs):
                archived.append(dict(pairs))

    return Product(
        name=title.get_text(strip=True),
        url=url,
        price=_parse_price(price.get_text()),
        attributes=attributes,
        archived=archived,
    )


def rank_hits(query: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Return the best-matching hits for ``query``.

    An exact (accent-insensitive) name match wins outright. Otherwise hits are
    scored by how many query words appear in the product name; every hit tied
    for the top score is returned, so more than one result means "ambiguous".
    """
    q = normalize(query)
    exact = [h for h in hits if normalize(h.name) == q]
    if exact:
        return exact[:1]
    words = q.split()
    scored = []
    for hit in hits:
        name_words = normalize(hit.name).split()
        score = sum(1 for w in words if any(nw.startswith(w) for nw in name_words))
        if score:
            scored.append((score, hit))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [hit for score, hit in scored if score == best]


class CoopClient:
    """Small cached HTTP client for the coop shop."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = 15.0, http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            # Use the OS certificate store so it works behind antivirus / corporate TLS proxies.
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )
        self._cache: dict[str, tuple[float, str]] = {}

    def _get(self, path_or_url: str, params: dict | None = None) -> str:
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        key = url + "?" + json.dumps(params or {}, sort_keys=True)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            response = self._http.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CoopUnavailableError(
                f"The coop website returned HTTP {exc.response.status_code} for {url}."
            ) from exc
        except httpx.HTTPError as exc:
            raise CoopUnavailableError(
                f"The coop website ({self.base_url}) could not be reached: {exc.__class__.__name__}."
            ) from exc
        self._cache[key] = (time.monotonic(), response.text)
        return response.text

    def search(self, query: str) -> list[SearchHit]:
        return parse_search(self._get("/shop", params={"search": query}), self.base_url)

    def get_product(self, url: str) -> Product:
        return parse_product(self._get(url), url)
