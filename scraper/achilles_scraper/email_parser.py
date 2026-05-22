"""
Generic newsletter HTML parser (ADR-011).

Per-vendor parsers can subclass / override this. The default heuristic:

  1. Find anchor tags whose URL points to a product page (heuristic: hostname
     contains the source's domain, or the path contains 'vins', 'product',
     'wine', or 'bouteille').
  2. Near each anchor, look for a price in EUR — first match within the same
     parent element wins.
  3. Pull producer + cuvée + vintage from the anchor text via the same
     normalisation helpers the rest of the codebase uses.

Output is a list of `EmailOffer` dataclasses. The scraper writes these to
`staging_price_candidates` so the existing tri-source rule (ADR-003) decides
whether they reach `fact_price`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

try:
    from selectolax.parser import HTMLParser, Node
    HAS_SELECTOLAX = True
except ImportError:
    HAS_SELECTOLAX = False
    HTMLParser = None  # type: ignore[assignment]
    Node = object      # type: ignore[assignment,misc]


# Match "12,90 €" / "€ 12.90" / "1 234,50 €" / "12.90€".
PRICE_RE = re.compile(
    # (?<!\d) prevents latching onto the trailing digit of a vintage like
    # "2015 €" and mis-reading it as a price of "5".
    r"(?<!\d)(?P<amount>\d{1,3}(?:[  \.]\d{3})*(?:[.,]\d{1,2})?)\s*€"
    r"|€\s*(?<!\d)(?P<amount2>\d{1,3}(?:[  \.]\d{3})*(?:[.,]\d{1,2})?)"
)
VINTAGE_RE = re.compile(r"\b(19[5-9]\d|20\d{2})\b")
BOTTLE_SIZE_RE = re.compile(r"(?P<ml>\d{2,4})\s*ml\b|(?P<cl>\d{2,4})\s*cl\b", re.IGNORECASE)


@dataclass(frozen=True)
class EmailOffer:
    """One wine offer parsed from a newsletter."""

    producer_name: str
    cuvee_name: str
    vintage: Optional[int]
    bottle_ml: int
    price_eur: float
    source_url: Optional[str]
    raw_anchor_text: str


def _parse_price(s: str) -> Optional[float]:
    m = PRICE_RE.search(s)
    if not m:
        return None
    raw = m.group("amount") or m.group("amount2") or ""
    # Strip spaces / NBSP / dots used as thousands separators, then normalize comma → dot.
    cleaned = raw.replace(" ", "").replace(" ", "")
    # If it has both '.' and ',' assume '.' is thousands, ',' decimal.
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _detect_bottle_ml(s: str) -> int:
    m = BOTTLE_SIZE_RE.search(s)
    if not m:
        return 750
    if m.group("ml"):
        try:
            return int(m.group("ml"))
        except ValueError:
            return 750
    if m.group("cl"):
        try:
            return int(m.group("cl")) * 10
        except ValueError:
            return 750
    return 750


def _detect_vintage(s: str) -> Optional[int]:
    m = VINTAGE_RE.search(s)
    if not m:
        return None
    try:
        y = int(m.group(1))
    except ValueError:
        return None
    if 1950 <= y <= 2099:
        return y
    return None


def _split_producer_cuvee(text: str) -> tuple[str, str]:
    """Best-effort split: 'Domaine X – Cuvée Y' → ('Domaine X', 'Cuvée Y').
    Falls back to ('', text) when we can't find a separator.
    """
    cleaned = re.sub(r"\s+", " ", text).strip("  \t-—–·,")
    for sep in (" – ", " — ", " - ", " — ", " · ", " | "):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                return left, right
    return "", cleaned


def _looks_like_product_url(href: str, source_domain_hints: Iterable[str]) -> bool:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False
    if not href.startswith(("http://", "https://", "//")):
        return False
    lower = href.lower()
    if any(hint and hint in lower for hint in source_domain_hints):
        return True
    return any(
        kw in lower
        for kw in ("/vins/", "/product/", "/products/", "/wine/", "/wines/", "/bouteille")
    )


def _nearest_price(anchor: "Node") -> Optional[float]:
    """Walk up from the anchor and look for a price in the surrounding text.
    `separator=" "` keeps sibling text from glueing together, which would
    otherwise turn "2018" + "189,00 €" into "2018189,00 €" and break the
    lookbehind in PRICE_RE.
    """
    cur: Optional["Node"] = anchor
    for _ in range(4):  # bounded ascent
        if cur is None:
            break
        try:
            text = cur.text(separator=" ", strip=True) if hasattr(cur, "text") else ""
        except TypeError:
            text = cur.text(strip=True) if hasattr(cur, "text") else ""
        p = _parse_price(text)
        if p is not None and p > 0:
            return p
        cur = getattr(cur, "parent", None)
    return None


def parse_newsletter_html(
    html: str,
    *,
    source_domain_hints: Iterable[str] = (),
) -> list[EmailOffer]:
    """Extract `EmailOffer` rows from a newsletter HTML body.

    Args:
        html: the newsletter's text/html part, decoded.
        source_domain_hints: optional substrings used to recognise product
            URLs for this sender (e.g. ('millesima.fr',)). Empty → use only
            the generic keyword fallback.
    """
    if not html or not HAS_SELECTOLAX:
        return []

    tree = HTMLParser(html)
    hints = tuple(h.lower() for h in source_domain_hints if h)

    offers: list[EmailOffer] = []
    seen_urls: set[str] = set()

    for anchor in tree.css("a[href]"):
        href = anchor.attributes.get("href", "")
        if not href:
            continue
        if not _looks_like_product_url(href, hints):
            continue
        if href in seen_urls:
            continue

        text = anchor.text(strip=True)
        if not text or len(text) < 6:
            # Tiny anchors are usually "click here" / images — skip.
            continue

        price = _nearest_price(anchor)
        if price is None or price <= 0:
            continue

        producer, cuvee = _split_producer_cuvee(text)
        # Strip the vintage out of the cuvée name to keep it canonical.
        vintage = _detect_vintage(text)
        cuvee_clean = cuvee
        if vintage is not None:
            cuvee_clean = re.sub(rf"\b{vintage}\b", "", cuvee_clean).strip("  \t-—–·,")

        bottle_ml = _detect_bottle_ml(text)

        # If we couldn't split producer/cuvée, drop the row — too ambiguous.
        if not producer or not cuvee_clean:
            continue

        offers.append(EmailOffer(
            producer_name=producer,
            cuvee_name=cuvee_clean,
            vintage=vintage,
            bottle_ml=bottle_ml,
            price_eur=price,
            source_url=href,
            raw_anchor_text=text,
        ))
        seen_urls.add(href)

    return offers
