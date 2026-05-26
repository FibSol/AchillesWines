"""
EmailNewsletterScraper subclasses — one per newsletter sender.

`from_email` is an IMAP FROM substring filter, so a domain fragment like
"millesima.com" matches any sender address that contains that string
(e.g. info@news.millesima.com, newsletter@millesima.fr, etc.).
"""
from __future__ import annotations

import re
from typing import Optional

from .email_newsletter import EmailNewsletterScraper
from ..email_parser import (
    EmailOffer,
    PRICE_RE as _PRICE_RE,
    _parse_price as _ep_parse_price,
    _detect_vintage as _ep_detect_vintage,
    _detect_bottle_ml as _ep_detect_bottle_ml,
    _split_producer_cuvee as _ep_split,
    parse_newsletter_html,
)

try:
    from selectolax.parser import HTMLParser as _HTMLParser
    _HAS_SELECTOLAX = True
except ImportError:
    _HAS_SELECTOLAX = False


# ---------------------------------------------------------------------------
# Shared helpers for block-first parsing
# ---------------------------------------------------------------------------

def _is_product_url(
    href: str,
    domain_fragments: tuple[str, ...],
    path_keywords: tuple[str, ...],
) -> bool:
    """Return True when href looks like a product page for this vendor."""
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False
    if not href.startswith(("http://", "https://", "//")):
        return False
    lower = href.lower()
    return (
        any(d in lower for d in domain_fragments)
        and any(k in lower for k in path_keywords)
    )


def _block_offer(anchor: object, href: str) -> Optional[EmailOffer]:
    """
    Walk up from *anchor* to find a sizeable content block (TD / DIV / LI /
    ARTICLE), then extract wine title + price from that block.

    Improvement over the generic parser: instead of reading only the anchor
    text, looks for a heading-like element (h1–h4 / strong / b) within the
    same block.  This handles newsletters that use image anchors or short CTA
    text where the product name lives in a separate element.

    Falls back to anchor text when no heading-like node is found.
    Returns None when the block contains no parseable price.
    """
    if not _HAS_SELECTOLAX:
        return None

    # 1. Walk up to find a sizeable content block.
    cur = anchor
    block = None
    for _ in range(10):
        if cur is None:
            break
        tag = (getattr(cur, "tag", "") or "").lower()
        if tag in ("td", "th", "div", "li", "article", "section"):
            try:
                t = cur.text(separator=" ", strip=True)
            except Exception:
                t = ""
            if len(t) >= 15:
                block = cur
                break
        cur = getattr(cur, "parent", None)

    if block is None:
        return None

    # 2. Find the wine title — prefer a heading-like child over anchor text.
    title_text = ""
    for sel in ("h1", "h2", "h3", "h4", "strong", "b"):
        for node in block.css(sel):
            if node is anchor:
                continue
            t = node.text(strip=True)
            # Skip price-only cells ("189,00 €") — they have € and are short.
            if t and len(t) >= 6 and not ("€" in t and len(t) < 30):
                title_text = t
                break
        if title_text:
            break

    # Fallback: read the anchor text itself.
    if not title_text:
        title_text = (anchor.text(strip=True) if hasattr(anchor, "text") else "")

    if not title_text or len(title_text) < 6:
        return None

    # 3. Find the price anywhere in the block.
    block_raw = block.text(separator=" ", strip=True)
    price = _ep_parse_price(block_raw)
    if not price or price <= 0:
        return None

    # 4. Parse producer / cuvée / vintage.
    producer, cuvee = _ep_split(title_text)
    vintage = _ep_detect_vintage(title_text)
    if vintage is not None and cuvee:
        cuvee = re.sub(rf"\b{vintage}\b", "", cuvee).strip(" \t-—–·,")
    bottle_ml = _ep_detect_bottle_ml(title_text)

    return EmailOffer(
        producer_name=producer or title_text,
        cuvee_name=cuvee or "",
        vintage=vintage,
        bottle_ml=bottle_ml,
        price_eur=price,
        source_url=href,
        raw_anchor_text=title_text,
    )


# ---------------------------------------------------------------------------
# Vendor subclasses
# ---------------------------------------------------------------------------

class MillesimaEmailScraper(EmailNewsletterScraper):
    """
    Millesima newsletter parser.

    Two email formats coexist:
    1. "Nouveautés" format — product data is fully inline in a TD:
       "Producer : Cuvée Vintage Appellation Color  NNN,NN€ Un carton de N Bouteilles (75cl)  Découvrir"
       Price is per carton; divide by bottle count for per-unit price.

    2. Legacy format — product link on millesima.com/millesima.fr with block-first
       extraction (image + CTA anchor; title in adjacent strong/heading).

    Both formats use tracking redirect URLs (t.news.millesima.com), so URL-based
    product detection is skipped in favour of text-pattern matching for format 1.
    """

    source_code = "millesima_email"
    from_email = "millesima.com"
    domain_hints = ("millesima.fr", "millesima.com")

    _DOMAIN_FRAGS: tuple[str, ...] = ("millesima.fr", "millesima.com")
    _PATH_KEYS: tuple[str, ...] = ("/vins/", "/bdd/produit", "/wine/", "/wines/", "/bouteille")

    # Matches "NNN,NN€ Un carton de N Bouteilles"
    _CARTON_RE = re.compile(
        r"(\d{1,4}[,.]\d{2})\s*€\s+Un carton de (\d+) Bouteilles",
        re.IGNORECASE,
    )
    # Colour words that trail the appellation — strip them from cuvée.
    _COLOR_WORDS = {"Blanc", "Rouge", "Rosé", "Rose", "Effervescent", "Mousseux", "Pétillant"}

    def _parse_inline(self, html: str) -> list[EmailOffer]:
        """Parse 'Nouveautés' style: full product info in a single TD."""
        if not _HAS_SELECTOLAX:
            return []
        tree = _HTMLParser(html)
        offers: list[EmailOffer] = []
        seen_texts: set[str] = set()

        for node in tree.css("td, div, p"):
            raw = node.text(separator=" ", strip=True)
            # Must contain " : " separator and a "carton de N Bouteilles" price.
            if " : " not in raw:
                continue
            m = self._CARTON_RE.search(raw)
            if not m:
                continue

            key = re.sub(r"\s+", " ", raw).strip()
            if key in seen_texts:
                continue
            seen_texts.add(key)

            price_str = m.group(1).replace(",", ".")
            try:
                carton_price = float(price_str)
            except ValueError:
                continue
            n_bottles = int(m.group(2))
            if n_bottles <= 0:
                continue
            price_per_bottle = round(carton_price / n_bottles, 2)

            # Text before the price pattern.
            prefix = raw[: m.start()].strip()
            # Split producer / rest on first " : ".
            colon_idx = prefix.find(" : ")
            if colon_idx < 0:
                continue
            producer = prefix[:colon_idx].strip()
            rest = prefix[colon_idx + 3:].strip()

            # Reject noise: preamble blocks have very long "producer" text or
            # contain multiple producers listed (commas) or preamble markers.
            if (
                len(producer) > 60
                or "en ligne" in producer.lower()
                or producer.count(",") >= 2
            ):
                continue

            # Detect vintage.
            vy = _ep_detect_vintage(rest)
            if vy is not None:
                # Cuvée is everything before the vintage.
                cuvee = re.sub(rf"\b{vy}\b.*", "", rest).strip()
            else:
                cuvee = rest

            # Strip trailing colour word from cuvée.
            words = cuvee.split()
            while words and words[-1] in self._COLOR_WORDS:
                words.pop()
            cuvee = " ".join(words).strip(" ,–—-")

            if not producer or not cuvee:
                continue

            # Source URL: nearest tracking href (best effort).
            href = ""
            for a in node.css("a[href]"):
                href = a.attributes.get("href", "") or ""
                if href:
                    break

            offers.append(EmailOffer(
                producer_name=producer,
                cuvee_name=cuvee,
                vintage=vy,
                bottle_ml=750,
                price_eur=price_per_bottle,
                source_url=href or None,
                raw_anchor_text=prefix,
            ))

        return offers

    def _parse_html(self, html: str) -> list[EmailOffer]:
        if not html or not _HAS_SELECTOLAX:
            return []

        # Try inline (Nouveautés) format first.
        offers = self._parse_inline(html)
        if offers:
            return offers

        # Legacy: product links on millesima domain.
        tree = _HTMLParser(html)
        seen: set[str] = set()
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href", "") or ""
            if not _is_product_url(href, self._DOMAIN_FRAGS, self._PATH_KEYS):
                continue
            if href in seen:
                continue
            seen.add(href)
            offer = _block_offer(anchor, href)
            if offer:
                offers.append(offer)

        if not offers:
            return parse_newsletter_html(html, source_domain_hints=self.domain_hints)
        return offers


class IDealwineEmailScraper(EmailNewsletterScraper):
    """
    iDealwine auction emails list lots with a title (often in an <h3>) and
    an estimate price, linked via short "Voir le lot" / "Enchérir" anchors.
    The block-first parser extracts name from the heading; generic fallback
    handles edge cases.
    """

    source_code = "idealwine_email"
    from_email = "idealwine.com"
    domain_hints = ("idealwine.com", "idealwine.net")

    _DOMAIN_FRAGS: tuple[str, ...] = ("idealwine.com", "idealwine.net")
    _PATH_KEYS: tuple[str, ...] = ("/vins/", "/achat/", "/fr/lot/", "/lot/", "/wine/", "/auction/")

    def _parse_html(self, html: str) -> list[EmailOffer]:
        if not html or not _HAS_SELECTOLAX:
            return []
        tree = _HTMLParser(html)
        offers: list[EmailOffer] = []
        seen: set[str] = set()
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href", "") or ""
            if not _is_product_url(href, self._DOMAIN_FRAGS, self._PATH_KEYS):
                continue
            if href in seen:
                continue
            seen.add(href)
            offer = _block_offer(anchor, href)
            if offer:
                offers.append(offer)
        if not offers:
            return parse_newsletter_html(html, source_domain_hints=self.domain_hints)
        return offers


class LaviniaEmailScraper(EmailNewsletterScraper):
    """
    Lavinia newsletters use structured product cards similar to Millesima.
    The product title is often in a <strong> or <p> near the "Ajouter au
    panier" / image anchor.  Block-first parser; generic fallback.
    """

    source_code = "lavinia_email"
    from_email = "lavinia.fr"
    domain_hints = ("lavinia.fr", "lavinia.com")

    _DOMAIN_FRAGS: tuple[str, ...] = ("lavinia.fr", "lavinia.com")
    _PATH_KEYS: tuple[str, ...] = ("/produit/", "/vins/", "/wine/", "/fr/produit/", "/es/", "/de/")

    def _parse_html(self, html: str) -> list[EmailOffer]:
        if not html or not _HAS_SELECTOLAX:
            return []
        tree = _HTMLParser(html)
        offers: list[EmailOffer] = []
        seen: set[str] = set()
        for anchor in tree.css("a[href]"):
            href = anchor.attributes.get("href", "") or ""
            if not _is_product_url(href, self._DOMAIN_FRAGS, self._PATH_KEYS):
                continue
            if href in seen:
                continue
            seen.add(href)
            offer = _block_offer(anchor, href)
            if offer:
                offers.append(offer)
        if not offers:
            return parse_newsletter_html(html, source_domain_hints=self.domain_hints)
        return offers


class VenteALaProprieteEmailScraper(EmailNewsletterScraper):
    """
    Custom parser for Vente à la Propriété newsletters.

    These emails use JWT tracking URLs for every link (t.news.ventealapropriete.com/…),
    so the generic anchor-based parser finds 0 product URLs. Product data is in TEXT
    nodes arranged in blocks: producer (line 1) · region (line 2) · description
    paragraphs · CTA button ("DÉCOUVRIR L'OFFRE" / "JE DÉCOUVRE" / etc.).

    Strategy:
      1. Find each CTA anchor and walk up the DOM to capture the containing block.
      2. Extract producer, region/appellation, vintage, and any price hint from the
         block text.
      3. Prices are often written as "de X euros" (≤X) rather than explicit "X €".
         Blocks without any price hint are skipped (can't populate staging without
         a price).

    Note: the ventealapropriete.com web scraper (Algolia) is the primary price
    source.  These emails add flash-sale timing signals and complementary price
    hints not always in the Algolia feed.
    """

    source_code = "ventealapropriete_email"
    from_email = "ventealapropriete.com"
    domain_hints = ("ventealapropriete.com",)

    # Regex matches CTAs like "DÉCOUVRIR L'OFFRE", "JE DÉCOUVRE", "EN SAVOIR PLUS",
    # "J'EN PROFITE" (both accented and unaccented forms).
    _CTA_RE = re.compile(
        r"D[ÉE]COUVR|EN SAVOIR PLUS|JE D[ÉE]COUVRE|J.EN PROFITE|EN PROFITER",
        re.IGNORECASE,
    )

    # Matches "de 20 euros", "de 20€", "20 €", "20€", "20 euros" etc.
    # The "de" prefix indicates an approximate upper bound.
    _PRICE_RE = re.compile(
        r"(?:de\s+)?(\d{1,3}(?:[  ,]\d{3})*(?:[.,]\d{1,2})?)\s*(?:€|euros?)",
        re.IGNORECASE,
    )

    _VINTAGE_RE = re.compile(r"\b(19[5-9]\d|20[012]\d)\b")

    # Lines that are navigation / structural noise, not wine content.
    _NAV_TEXTS = {
        "TOUTES NOS VENTES", "PARRAINAGE", "NEWSLETTERS", "PRIMEURS",
        "VERSION WEB", "AJOUTEZ", "VOS CONTACTS", "ME DÉSABONNER",
        "GÉRER MES COMMUNICATIONS", "VENTEALAPROPRIETE.COM",
        "LIVRAISON DE QUALITÉ", "PARRAINEZ VOS PROCHES",
        "SATISFAIT OU REMBOURSÉ", "SITE NOTÉ EXCELLENT",
        "DERNIER", "JOUR",
    }

    def _parse_html(self, html: str) -> list[EmailOffer]:
        if not html or not _HAS_SELECTOLAX:
            return []

        tree = _HTMLParser(html)
        offers: list[EmailOffer] = []
        seen_hrefs: set[str] = set()

        for anchor in tree.css("a[href]"):
            cta_text = anchor.text(strip=True)
            if not self._CTA_RE.search(cta_text):
                continue

            href = anchor.attributes.get("href", "") or ""
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            block_text = self._extract_block_text(anchor)
            if not block_text:
                continue

            offer = self._parse_block(block_text, href)
            if offer is not None:
                offers.append(offer)

        return offers

    def _extract_block_text(self, anchor: object) -> str:
        """Walk up from the CTA anchor until we find a node with ≥200 chars of text."""
        cur = anchor
        for _ in range(12):
            if cur is None:
                break
            try:
                t = cur.text(separator="\n", strip=True)
            except Exception:
                t = ""
            if len(t) >= 200:
                return t
            cur = getattr(cur, "parent", None)
        return ""

    def _parse_block(self, block_text: str, href: str) -> Optional[EmailOffer]:
        """Parse one product block and return an EmailOffer, or None if no price found."""
        lines = [
            l.strip()
            for l in block_text.split("\n")
            if l.strip() and len(l.strip()) > 2
        ]
        # Remove navigation noise lines.
        content_lines = [
            l for l in lines
            if l.upper().rstrip(".!?") not in self._NAV_TEXTS
            and not self._CTA_RE.search(l)
        ]

        if len(content_lines) < 2:
            return None

        producer = content_lines[0]
        region = content_lines[1] if len(content_lines) > 1 else ""

        # Subtitle / cuvée: third line if it's a clean title (not a price/score line).
        _NOISE_IN_SUBTITLE = re.compile(r"[€]|euros?|/100", re.IGNORECASE)
        subtitle = ""
        if len(content_lines) > 2:
            candidate = content_lines[2]
            if len(candidate) <= 120 and not _NOISE_IN_SUBTITLE.search(candidate):
                subtitle = candidate

        # Vintage: search only the first 3 lines to avoid picking up domaine-founding
        # years buried deep in description paragraphs.
        vintage: Optional[int] = None
        for line in content_lines[:3]:
            m = self._VINTAGE_RE.search(line)
            if m:
                vintage = int(m.group(1))
                break

        # Price: walk all content lines looking for any price pattern.
        price: Optional[float] = None
        for line in content_lines:
            m = self._PRICE_RE.search(line)
            if m:
                raw = (
                    m.group(1)
                    .replace(" ", "")  # NBSP
                    .replace(" ", "")
                    .replace(" ", "")  # narrow NBSP
                )
                # Thousands vs decimal: if both '.' and ',' present, '.' = thousands.
                if "." in raw and "," in raw:
                    raw = raw.replace(".", "").replace(",", ".")
                else:
                    raw = raw.replace(",", ".")
                try:
                    price = float(raw)
                    if price > 0:
                        break
                    price = None
                except ValueError:
                    pass

        if price is None or price <= 0:
            return None

        # Cuvée: prefer subtitle; fall back to region so wine_key is non-empty.
        cuvee = subtitle or region

        return EmailOffer(
            producer_name=producer,
            cuvee_name=cuvee,
            vintage=vintage,
            bottle_ml=750,
            price_eur=price,
            source_url=href or None,
            raw_anchor_text=f"{producer} / {region}",
        )
