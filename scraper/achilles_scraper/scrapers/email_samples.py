"""
EmailNewsletterScraper subclasses — one per newsletter sender.

`from_email` is an IMAP FROM substring filter, so a domain fragment like
"millesima.com" matches any sender address that contains that string
(e.g. info@news.millesima.com, newsletter@millesima.fr, etc.).
"""
from .email_newsletter import EmailNewsletterScraper


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
    source_code = "ventealapropriete_email"
    from_email = "ventealapropriete.com"
    domain_hints = ("ventealapropriete.com",)
