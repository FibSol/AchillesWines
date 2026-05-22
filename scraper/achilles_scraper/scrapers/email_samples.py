"""
Sample EmailNewsletterScraper subclasses.

These are stubs — adjust `from_email` to the actual sender domain you
subscribed to, then register the matching `dim_source` row with the same
`source_code`. The generic HTML heuristic is enough for many vendors; if
the layout is exotic, override `_parse_html()`.
"""
from .email_newsletter import EmailNewsletterScraper


class MillesimaEmailScraper(EmailNewsletterScraper):
    source_code = "millesima_email"
    # Real value to set in dim_source seed:
    from_email = "newsletter@millesima.fr"
    domain_hints = ("millesima.fr", "millesima.com")


class IDealwineEmailScraper(EmailNewsletterScraper):
    source_code = "idealwine_email"
    from_email = "no-reply@idealwine.com"
    domain_hints = ("idealwine.com", "idealwine.net")


class LaviniaEmailScraper(EmailNewsletterScraper):
    source_code = "lavinia_email"
    from_email = "newsletter@lavinia.fr"
    domain_hints = ("lavinia.fr", "lavinia.com")
