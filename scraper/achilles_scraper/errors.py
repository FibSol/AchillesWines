"""
Shared exception classes for the Achilles scraper sidecar.

Kept in a leaf module (no imports from other achilles_scraper sub-modules)
so that both ``auth.py`` and ``retry.py`` can import from here without
creating a circular dependency.
"""


class AuthError(Exception):
    """Login attempted but the target rejected our credentials, or the dance broke."""


class AuthMissingError(AuthError):
    """Required ACHILLES_AUTH_* env vars are absent.

    Scraper runner converts this to a DLQ row with errorClass="auth_error"
    and skips the batch.
    """
