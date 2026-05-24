"""
Unit tests for per-vendor email newsletter parsers (#20).

These tests exercise the block-first `_parse_html` overrides added to
MillesimaEmailScraper, IDealwineEmailScraper, and LaviniaEmailScraper.
They use realistic HTML fixtures that represent the layouts where the
generic parser (anchor-text only) previously returned 0 offers.
"""
import unittest
from unittest.mock import MagicMock

from achilles_scraper.scrapers.email_samples import (
    MillesimaEmailScraper,
    IDealwineEmailScraper,
    LaviniaEmailScraper,
    _is_product_url,
    _block_offer,
)


def _scraper(cls):
    """Instantiate a scraper with a fake connection (not used in _parse_html)."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    return cls(conn)


# ---------------------------------------------------------------------------
# _is_product_url helper
# ---------------------------------------------------------------------------

class IsProductUrlTests(unittest.TestCase):
    def test_matching_domain_and_path(self):
        self.assertTrue(
            _is_product_url(
                "https://www.millesima.fr/vins/coche-dury.html",
                ("millesima.fr",),
                ("/vins/",),
            )
        )

    def test_missing_path_keyword(self):
        self.assertFalse(
            _is_product_url(
                "https://www.millesima.fr/blog/article",
                ("millesima.fr",),
                ("/vins/",),
            )
        )

    def test_missing_domain(self):
        self.assertFalse(
            _is_product_url(
                "https://www.example.com/vins/abc",
                ("millesima.fr",),
                ("/vins/",),
            )
        )

    def test_mailto_rejected(self):
        self.assertFalse(
            _is_product_url("mailto:contact@millesima.fr", ("millesima.fr",), ("/vins/",))
        )

    def test_hash_rejected(self):
        self.assertFalse(
            _is_product_url("#top", ("millesima.fr",), ("/vins/",))
        )


# ---------------------------------------------------------------------------
# Millesima — image anchor, title in <strong>
# ---------------------------------------------------------------------------

class MillesimaEmailParserTests(unittest.TestCase):
    # Simulates a Millesima card where the anchor wraps an image and the wine
    # name lives in a <strong> in the same table cell.
    _HTML_IMAGE_ANCHOR = """
    <html><body>
      <table>
        <tr>
          <td>
            <a href="https://www.millesima.fr/vins/coche-dury-meursault-2020.html">
              <img src="bottle.jpg" alt=""/>
            </a>
            <strong>Domaine Coche-Dury – Meursault 2020</strong>
            <p class="price">245,00 €</p>
          </td>
        </tr>
      </table>
    </body></html>
    """

    # Anchor text contains the full product name (standard case → generic
    # fallback still extracts correctly).
    _HTML_ANCHOR_TEXT = """
    <html><body>
      <table>
        <tr>
          <td>
            <a href="https://www.millesima.fr/vins/palmer-margaux-2018.html">
              Château Palmer – Margaux 2018
            </a>
            <span>389,00 €</span>
          </td>
        </tr>
      </table>
    </body></html>
    """

    # Short CTA anchor — wine name in h3.
    _HTML_SHORT_ANCHOR = """
    <html><body>
      <div class="product-card">
        <h3>Château Pétrus – Pomerol 2010</h3>
        <p>3 600,00 €</p>
        <a href="https://www.millesima.fr/vins/petrus-pomerol-2010.html">Voir</a>
      </div>
    </body></html>
    """

    _HTML_NO_PRODUCTS = """
    <html><body>
      <a href="https://www.millesima.fr/blog/actualites">Read the blog</a>
    </body></html>
    """

    def setUp(self):
        self.scraper = _scraper(MillesimaEmailScraper)

    def test_image_anchor_extracts_title_from_strong(self):
        offers = self.scraper._parse_html(self._HTML_IMAGE_ANCHOR)
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.producer_name, "Domaine Coche-Dury")
        self.assertIn("Meursault", o.cuvee_name)
        self.assertNotIn("2020", o.cuvee_name)
        self.assertEqual(o.vintage, 2020)
        self.assertAlmostEqual(o.price_eur, 245.0)

    def test_standard_anchor_text_still_works(self):
        offers = self.scraper._parse_html(self._HTML_ANCHOR_TEXT)
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.producer_name, "Château Palmer")
        self.assertAlmostEqual(o.price_eur, 389.0)
        self.assertEqual(o.vintage, 2018)

    def test_short_anchor_extracts_title_from_h3(self):
        offers = self.scraper._parse_html(self._HTML_SHORT_ANCHOR)
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual(o.producer_name, "Château Pétrus")
        self.assertAlmostEqual(o.price_eur, 3600.0)

    def test_no_product_links_returns_empty(self):
        offers = self.scraper._parse_html(self._HTML_NO_PRODUCTS)
        self.assertEqual(offers, [])

    def test_empty_html_returns_empty(self):
        self.assertEqual(self.scraper._parse_html(""), [])


# ---------------------------------------------------------------------------
# iDealwine — lot listing with heading, short "Enchérir" anchor
# ---------------------------------------------------------------------------

class IDealwineEmailParserTests(unittest.TestCase):
    # Classic auction lot: title in <h3>, CTA anchor is "Enchérir".
    _HTML_LOT_LISTING = """
    <html><body>
      <div class="lot">
        <h3>Domaine de la Romanée-Conti – La Tâche 2015</h3>
        <p>Estimation : 1 500 – 2 000 €</p>
        <a href="https://www.idealwine.com/vins/romanee-conti-la-tache-2015.html">
          Enchérir
        </a>
      </div>
      <div class="lot">
        <h3>Domaine Leroy – Chambolle-Musigny 2012</h3>
        <p>Estimation : 450 €</p>
        <a href="https://www.idealwine.com/achat/leroy-chambolle-2012.html">
          Voir le lot
        </a>
      </div>
    </body></html>
    """

    # Short anchor text but domain hint in URL: should still pick up price.
    _HTML_FULL_ANCHOR = """
    <html><body>
      <td>
        <a href="https://www.idealwine.com/vins/lafite-rothschild-pauillac-2016.html">
          Château Lafite-Rothschild – Pauillac 2016
        </a>
        <span>720,00 €</span>
      </td>
    </body></html>
    """

    _HTML_NO_PRODUCTS = """
    <html><body>
      <a href="https://www.idealwine.com/about/press">Press</a>
    </body></html>
    """

    def setUp(self):
        self.scraper = _scraper(IDealwineEmailScraper)

    def test_lot_listing_extracts_two_lots(self):
        offers = self.scraper._parse_html(self._HTML_LOT_LISTING)
        self.assertEqual(len(offers), 2)

    def test_lot_producer_correct(self):
        offers = self.scraper._parse_html(self._HTML_LOT_LISTING)
        producers = {o.producer_name for o in offers}
        self.assertIn("Domaine de la Romanée-Conti", producers)
        self.assertIn("Domaine Leroy", producers)

    def test_lot_price_extracted(self):
        offers = self.scraper._parse_html(self._HTML_LOT_LISTING)
        # First lot estimate "1 500 – 2 000 €" → PRICE_RE picks first number.
        drc = next(o for o in offers if "Romanée-Conti" in o.producer_name)
        self.assertGreater(drc.price_eur, 0)

    def test_standard_anchor_fallback(self):
        offers = self.scraper._parse_html(self._HTML_FULL_ANCHOR)
        self.assertEqual(len(offers), 1)
        self.assertAlmostEqual(offers[0].price_eur, 720.0)

    def test_no_product_links_returns_empty(self):
        self.assertEqual(self.scraper._parse_html(self._HTML_NO_PRODUCTS), [])

    def test_empty_html_returns_empty(self):
        self.assertEqual(self.scraper._parse_html(""), [])


# ---------------------------------------------------------------------------
# Lavinia — product card with name in <strong>, short "Acheter" anchor
# ---------------------------------------------------------------------------

class LaviniaEmailParserTests(unittest.TestCase):
    # Lavinia card: image link + name in <strong> + price in <span>.
    _HTML_PRODUCT_CARD = """
    <html><body>
      <div class="product">
        <a href="https://www.lavinia.fr/fr/produit/opus-one-napa-2019.html">
          <img src="opus.jpg"/>
        </a>
        <strong>Opus One – Napa Valley 2019</strong>
        <span class="price">180,00 €</span>
        <a href="https://www.lavinia.fr/fr/produit/opus-one-napa-2019.html">
          Acheter
        </a>
      </div>
      <div class="product">
        <a href="https://www.lavinia.fr/fr/produit/sassicaia-bolgheri-2018.html">
          <img src="sassicaia.jpg"/>
        </a>
        <strong>Sassicaia – Bolgheri 2018</strong>
        <p>95,00 €</p>
        <a href="https://www.lavinia.fr/fr/produit/sassicaia-bolgheri-2018.html">
          Acheter
        </a>
      </div>
    </body></html>
    """

    _HTML_NO_PRODUCTS = """
    <html><body>
      <a href="https://www.lavinia.fr/fr/cgu">CGU</a>
    </body></html>
    """

    def setUp(self):
        self.scraper = _scraper(LaviniaEmailScraper)

    def test_two_products_extracted(self):
        offers = self.scraper._parse_html(self._HTML_PRODUCT_CARD)
        # Each product has 2 anchors (image + "Acheter"), but seen-set dedupes.
        self.assertEqual(len(offers), 2)

    def test_product_names_correct(self):
        offers = self.scraper._parse_html(self._HTML_PRODUCT_CARD)
        producers = {o.producer_name for o in offers}
        self.assertIn("Opus One", producers)
        self.assertIn("Sassicaia", producers)

    def test_prices_correct(self):
        offers = self.scraper._parse_html(self._HTML_PRODUCT_CARD)
        by_producer = {o.producer_name: o.price_eur for o in offers}
        self.assertAlmostEqual(by_producer["Opus One"], 180.0)
        self.assertAlmostEqual(by_producer["Sassicaia"], 95.0)

    def test_vintage_extracted(self):
        offers = self.scraper._parse_html(self._HTML_PRODUCT_CARD)
        vintages = {o.vintage for o in offers}
        self.assertIn(2019, vintages)
        self.assertIn(2018, vintages)

    def test_no_product_links_returns_empty(self):
        self.assertEqual(self.scraper._parse_html(self._HTML_NO_PRODUCTS), [])

    def test_empty_html_returns_empty(self):
        self.assertEqual(self.scraper._parse_html(""), [])


if __name__ == "__main__":
    unittest.main()
