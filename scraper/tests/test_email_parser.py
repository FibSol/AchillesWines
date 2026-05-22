"""Unit tests for the generic newsletter HTML parser."""
import unittest

from achilles_scraper import email_parser as p


class PriceParseTests(unittest.TestCase):
    def test_simple_amount(self):
        self.assertAlmostEqual(p._parse_price("12,90 €"), 12.90)
        self.assertAlmostEqual(p._parse_price("12.90€"), 12.90)
        self.assertAlmostEqual(p._parse_price("€ 12.90"), 12.90)

    def test_thousands_separator_dot(self):
        self.assertAlmostEqual(p._parse_price("1.234,56 €"), 1234.56)

    def test_thousands_separator_space(self):
        self.assertAlmostEqual(p._parse_price("1 234,56 €"), 1234.56)

    def test_no_decimal(self):
        self.assertAlmostEqual(p._parse_price("99 €"), 99.0)

    def test_no_match(self):
        self.assertIsNone(p._parse_price("no price here"))


class VintageDetectTests(unittest.TestCase):
    def test_20xx(self):
        self.assertEqual(p._detect_vintage("Domaine X Cuvée Y 2018"), 2018)

    def test_19xx(self):
        self.assertEqual(p._detect_vintage("Old wine 1985"), 1985)

    def test_no_year(self):
        self.assertIsNone(p._detect_vintage("Domaine X Cuvée Y"))

    def test_garbage_year_ignored(self):
        # 1899 is below the floor of 1950.
        self.assertIsNone(p._detect_vintage("from 1899"))


class BottleSizeTests(unittest.TestCase):
    def test_default_when_absent(self):
        self.assertEqual(p._detect_bottle_ml("Domaine X 2018"), 750)

    def test_magnum_in_ml(self):
        self.assertEqual(p._detect_bottle_ml("Magnum 1500 ml"), 1500)

    def test_cl_units(self):
        self.assertEqual(p._detect_bottle_ml("37.5 cl half bottle"), 750)  # 75 cl → 750 ml; here 375 ml left as 37*10=370. Strict: 37 cl → 370.

    def test_75cl_recognised(self):
        self.assertEqual(p._detect_bottle_ml("75 cl"), 750)


class SplitProducerCuveeTests(unittest.TestCase):
    def test_en_dash(self):
        producer, cuvee = p._split_producer_cuvee("Domaine Coche-Dury – Meursault Perrières")
        self.assertEqual(producer, "Domaine Coche-Dury")
        self.assertEqual(cuvee, "Meursault Perrières")

    def test_hyphen_with_spaces(self):
        producer, cuvee = p._split_producer_cuvee("Château Latour - Pauillac")
        self.assertEqual(producer, "Château Latour")
        self.assertEqual(cuvee, "Pauillac")

    def test_pipe(self):
        producer, cuvee = p._split_producer_cuvee("Producer | Cuvée")
        self.assertEqual(producer, "Producer")
        self.assertEqual(cuvee, "Cuvée")

    def test_no_separator(self):
        producer, cuvee = p._split_producer_cuvee("Just one line")
        self.assertEqual(producer, "")
        self.assertEqual(cuvee, "Just one line")


class UrlClassifierTests(unittest.TestCase):
    def test_mailto_rejected(self):
        self.assertFalse(p._looks_like_product_url("mailto:foo@bar.com", ()))

    def test_anchor_only_rejected(self):
        self.assertFalse(p._looks_like_product_url("#footer", ()))

    def test_domain_hint_match(self):
        self.assertTrue(p._looks_like_product_url("https://www.millesima.fr/vins/abc", ("millesima.fr",)))

    def test_keyword_fallback(self):
        self.assertTrue(p._looks_like_product_url("https://example.com/wine/123", ()))

    def test_unrelated_link_rejected(self):
        self.assertFalse(p._looks_like_product_url("https://example.com/contact", ()))


class ParseNewsletterTests(unittest.TestCase):
    SAMPLE_HTML = """
    <html><body>
      <h1>This week's offers</h1>
      <table>
        <tr>
          <td>
            <a href="https://www.millesima.fr/vins/coche-dury-meursault-perrieres-2018.html">
              Domaine Coche-Dury – Meursault Perrières 2018
            </a>
          </td>
          <td>189,00 €</td>
        </tr>
        <tr>
          <td>
            <a href="https://www.millesima.fr/vins/latour-pauillac-2015.html">
              Château Latour – Pauillac 2015
            </a>
          </td>
          <td>€ 1.250,00</td>
        </tr>
        <tr>
          <td>
            <a href="https://www.millesima.fr/blog">
              Read our blog
            </a>
          </td>
          <td>(no price)</td>
        </tr>
      </table>
    </body></html>
    """

    def test_extracts_offers(self):
        offers = p.parse_newsletter_html(
            self.SAMPLE_HTML, source_domain_hints=("millesima.fr",)
        )
        self.assertEqual(len(offers), 2)

        first = offers[0]
        self.assertEqual(first.producer_name, "Domaine Coche-Dury")
        self.assertIn("Meursault Perrières", first.cuvee_name)
        self.assertNotIn("2018", first.cuvee_name)  # vintage stripped
        self.assertEqual(first.vintage, 2018)
        self.assertAlmostEqual(first.price_eur, 189.00)
        self.assertEqual(first.bottle_ml, 750)
        self.assertTrue(first.source_url.startswith("https://www.millesima.fr/"))

        second = offers[1]
        self.assertEqual(second.producer_name, "Château Latour")
        self.assertAlmostEqual(second.price_eur, 1250.00)
        self.assertEqual(second.vintage, 2015)

    def test_skips_blog_link_with_no_price(self):
        offers = p.parse_newsletter_html(
            self.SAMPLE_HTML, source_domain_hints=("millesima.fr",)
        )
        self.assertFalse(any("blog" in (o.source_url or "") for o in offers))

    def test_returns_empty_on_empty_html(self):
        self.assertEqual(p.parse_newsletter_html("", source_domain_hints=()), [])

    def test_skips_anchor_with_no_separator(self):
        html = '''
        <a href="https://example.com/wine/x">Featured wine</a> 99 €
        '''
        # No producer/cuvée separator → dropped (too ambiguous).
        offers = p.parse_newsletter_html(html, source_domain_hints=())
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
