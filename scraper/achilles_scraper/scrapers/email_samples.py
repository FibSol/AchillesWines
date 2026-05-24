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
from ..email_parser import EmailOffer

try:
    from selectolax.parser import HTMLParser as _HTMLParser
    _HAS_SELECTOLAX = True
except ImportError:
    _HAS_SELECTOLAX = False


class MillesimaEmailScraper(EmailNewsletterScraper):
    source_code = "millesima_email"
    from_email = "millesima.com"
    domain_hints = ("millesima.fr", "millesima.com")


class IDealwineEmailScraper(EmailNewsletterScraper):
    source_code = "idealwine_email"
    from_email = "idealwine.com"
    domain_hints = ("idealwine.com", "idealwine.net")


class LaviniaEmailScraper(EmailNewsletterScraper):
    source_code = "lavinia_email"
    from_email = "lavinia.fr"
    domain_hints = ("lavinia.fr", "lavinia.com")


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
