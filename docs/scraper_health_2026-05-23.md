# Scraper health — 2026-05-23

Ran 37 scrapers via subprocess with `--limit 5` and 60s hard timeout against `data\achilles.test.db` (copy of prod).

Connections opened via `get_db()` so `PRAGMA foreign_keys=ON`.

## Summary

**GREEN** 11 · **YELLOW** 8 · **GRAY** 2 · **RED** 16

## Interpretation

Headline: **19 of 37 scrapers are healthy** (11 GREEN + 8 YELLOW). The 8
YELLOW are mostly idempotent re-runs — they fetched rows that were already
in the DB and correctly skipped them (`skipped == fetched`). The one
exception is **`inao`**, which fetched 315 but only marked 5 as skipped —
the other 310 rows went somewhere uncounted and warrant a closer look.

Breakdown of the 16 RED:

**Real bugs (fixable, prioritised):**
- `hachette_vins` — **timed out after 60s** with no output. Same scraper that
  produced 13,650 FK-violation DLQ rows in the audit. Likely an infinite
  loop or runaway pagination. P0.
- `comptoir_des_millesimes` — URL changed: `/vins` returns 404. Catalog URL
  needs to be updated. P1.
- `figaro_vin`, `rvf`, `terredevins` — each wrote 1 DLQ row but returned
  `error=""` to the caller. Silent failure mode hides what broke. Fix the
  scrapers to propagate the actual error into `ScrapeResult.error`. P2.
- `belgiumwinewatchers` — 0 fetched, 0 DLQ, empty error. Truly silent
  failure. Needs investigation. P2.

**External / not our fault:**
- `decanter` — requires paid Piano subscription. Either pay or remove.
- `james_suckling` — site is now a JS-only SPA; needs Playwright (or remove).
- `wdc_be` — domain is for sale, source is dead. **Mark `enabled=0`.**
- `wine_searcher` — marked "not implemented" intentionally.

**Bad credentials in .env (rotate or remove):**
- `cavissima_be` — login rejected.
- `lavinia` — login rejected.

**Newsletter scrapers — empty IMAP queue (expected when no fresh mail):**
- `idealwine_email`, `lavinia_email`, `millesima_email`, `ventealapropriete_email`
  All four returned cleanly with 0 fetched and no error. These run on
  inbound mail; no mail = no work. Not broken.

Breakdown of the 8 YELLOW:

- `cavissima`, `cinoco`, `ec_agrifood`, `hachette_vins_shop`, `ventealapropriete`,
  `vinsbrunin`, `wijnendeclerck_be` — all `fetched == skipped`, healthy
  idempotent runs. Not actually yellow.
- `inao` — fetched 315, skipped only 5. The other 310 are unaccounted for.
  Investigate.

(The YELLOW vs GREEN cut-off is misleading in this run: any scraper where
all fetched rows are skipped *should* count as GREEN. Future runs will
recategorise once `skipped` is treated as a healthy terminal state.)


## RED — errored, fetched 0 rows, or timed out

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `belgiumwinewatchers` | 0 | 0 | 0 | 0 | 3.0s |  |
| `cavissima_be` | 0 | 0 | 1 | 0 | 3.3s | Login failed: login rejected for cavissima_be (bad credentials?) |
| `comptoir_des_millesimes` | 0 | 0 | 1 | 0 | 2.7s | HTTP error on page 1: Client error '404 Not Found' for url 'https://www.comptoirdesmillesimes.com/vins' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404 |
| `decanter` | 0 | 0 | 1 | 0 | 2.2s | Decanter search requires a paid Piano subscription. The response contains an empty 'piano-container-search-results' div. Set requires_auth=1 in dim_source and provide valid Piano credentials to enable |
| `figaro_vin` | 0 | 0 | 1 | 0 | 1.4s |  |
| `hachette_vins` | 0 | 0 | 0 | 0 | 60.0s | timed out after 60s |
| `idealwine_email` | 0 | 0 | 0 | 0 | 1.5s |  |
| `james_suckling` | 0 | 0 | 1 | 0 | 3.2s | jamessuckling.com/top-wines/ is a client-side-only Next.js SPA (no __NEXT_DATA__ in HTML). Wine content requires JS execution. Set requires_auth=1 in dim_source as a proxy for 'needs browser' and prov |
| `lavinia` | 0 | 0 | 0 | 0 | 2.6s | login rejected for lavinia (bad credentials?) |
| `lavinia_email` | 0 | 0 | 0 | 0 | 1.6s |  |
| `millesima_email` | 0 | 0 | 0 | 0 | 1.5s |  |
| `rvf` | 0 | 0 | 1 | 0 | 1.3s |  |
| `terredevins` | 0 | 0 | 1 | 0 | 1.3s |  |
| `ventealapropriete_email` | 0 | 0 | 0 | 0 | 1.5s |  |
| `wdc_be` | 0 | 0 | 1 | 0 | 2.6s | wdc.be domain is for sale (Nameshift/NVA Online Advertising B.V. — verified 2026-05-23). The wine shop no longer exists at this URL. Source deactivated. |
| `wine_searcher` | 0 | 0 | 0 | 0 | 2.3s | wine_searcher: not implemented — subscription required |

## YELLOW — fetched but inserted 0 (gate / dim resolution)

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `cavissima` | 5 | 0 | 0 | 5 | 3.3s |  |
| `cinoco` | 5 | 0 | 0 | 5 | 2.3s |  |
| `ec_agrifood` | 225 | 0 | 0 | 225 | 2.7s |  |
| `hachette_vins_shop` | 5 | 0 | 0 | 5 | 2.5s |  |
| `inao` | 315 | 0 | 0 | 5 | 2.5s |  |
| `ventealapropriete` | 5 | 0 | 0 | 5 | 3.7s |  |
| `vinsbrunin` | 5 | 0 | 0 | 5 | 6.2s |  |
| `wijnendeclerck_be` | 5 | 0 | 0 | 5 | 18.1s |  |

## GRAY — credentials missing (expected — no creds in .env)

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `cellartracker` | 0 | 0 | 0 | 0 | 1.3s | Credentials missing: set ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD |
| `cellartracker_xlquery` | 0 | 0 | 0 | 0 | 1.4s | Credentials missing: set ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD |

## GREEN — fetched and inserted

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `eurostat_harvest` | 1710 | 5 | 0 | 543 | 2.4s |  |
| `idealwine` | 5 | 5 | 0 | 0 | 14.5s |  |
| `kaggle_reviews` | 129971 | 5 | 0 | 129966 | 12.8s |  |
| `millesima` | 0 | 0 | 0 | 44 | 3.0s |  |
| `millesima_be` | 5 | 1 | 0 | 4 | 3.0s |  |
| `topwijnen_be` | 5 | 2 | 0 | 3 | 5.1s |  |
| `vinatis` | 5 | 1 | 0 | 4 | 3.3s |  |
| `vintage_ratings` | 5 | 5 | 0 | 0 | 5.8s |  |
| `werc` | 9293 | 5 | 0 | 9288 | 45.6s |  |
| `wijnhuis` | 5 | 5 | 0 | 0 | 4.1s |  |
| `xwines` | 1000 | 5 | 0 | 461 | 5.1s |  |
