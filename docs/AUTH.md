# Scraper authentication

Some retail and critic sites gate prices/ratings behind a login. Achilles's Wines supports **form-login** flows (username + password) with credentials in environment variables — see [ADR-010](../DECISIONS.md).

## How it works

1. The schema's `dim_source.requires_auth` flag identifies which sources need a login.
2. Credentials live in env vars (`.env` on dev, Docker env / HA secrets on prod):

   ```
   ACHILLES_AUTH_<SOURCE_CODE>_USERNAME=alice
   ACHILLES_AUTH_<SOURCE_CODE>_PASSWORD=s3cret
   ```
   `<SOURCE_CODE>` is the `dim_source.source_code` upper-cased, with `-` replaced by `_`.

3. Scrapers that need login subclass `AuthenticatedScraper` (in `scraper/achilles_scraper/auth.py`) and implement `_login(client, creds)` — the login dance is per-site.
4. Sessions are **not** persisted. Every batch logs in fresh. (Faster cache would be a future schema migration; see ADR-010 for the trade-off.)

## Adding a new authenticated scraper

```python
# scraper/achilles_scraper/scrapers/idealwine.py
import httpx
from ..auth import AuthenticatedScraper, Credentials
from .base import ScrapeResult

class IDealwineScraper(AuthenticatedScraper):
    source_code = "idealwine"

    def _login(self, client: httpx.Client, creds: Credentials) -> bool:
        # Step 1: GET login page for CSRF token (if any)
        # Step 2: POST credentials
        # Step 3: detect success (cookie set, redirect, response status)
        r = client.post(
            "https://www.idealwine.com/account/login",
            data={"email": creds.username, "password": creds.password},
        )
        # Treat 401/403 as bad creds (return False), other errors raise.
        if r.status_code in (401, 403):
            return False
        r.raise_for_status()
        return "auth_token" in client.cookies

    def run(self, limit=None) -> ScrapeResult:
        with self.authenticated_client() as client:
            # … normal scraping, cookies already attached
            ...
        return ScrapeResult(batch_id=self.batch_id or "")
```

Register the scraper in `scraper/achilles_scraper/cli.py`'s `_load_scrapers()` and mark the row in `dim_source` with `requires_auth = 1`.

## Testing login from the UI

The `/admin/auth` page lists every source where `requires_auth = 1`:

- ✅ green badge if both env vars are present at server boot.
- ⚠ red badge if either is missing.
- "Test login" button queues a job with `params: { test_auth: true }`. The job runner skips the actual scrape and just runs `_login()`, recording success/failure on `ops_job_queue`. Result viewable in `/admin/jobs`.

## Failure semantics

| Situation                            | What happens                                                                    |
|--------------------------------------|---------------------------------------------------------------------------------|
| Required env var missing             | `AuthMissingError` → job marked failed, message names the missing var.          |
| `_login()` returns `False`           | `AuthError` → job marked failed with "login rejected (bad credentials?)".       |
| `_login()` raises (network, 5xx)     | `AuthError` wrapping the original exception.                                    |
| DLQ on per-row 401 during scraping   | Up to the scraper to decide; `errorClass="auth_error"` exists in the DLQ enum.  |

## What is NOT supported (yet)

- OAuth / SAML / SSO
- Captchas, 2FA, magic links
- Pasted-cookie-jar workflow (we picked form-only — see ADR-010)
- Persistent session cache (re-login every batch)

If you need any of these later, see ADR-010 for the rejected designs and bring them back from there.
