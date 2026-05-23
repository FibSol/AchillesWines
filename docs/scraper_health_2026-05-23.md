# Scraper health — 2026-05-23

Ran 38 scrapers via subprocess with `--limit 5` and 60s hard timeout against `data\achilles.test.db` (copy of prod).

Connections opened via `get_db()` so `PRAGMA foreign_keys=ON`.

## Summary

**GREEN** 21 · **YELLOW** 2 · **GRAY** 2 · **RED** 13

## RED — errored, fetched 0 rows, or timed out

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `cavissima_be` | 0 | 0 | 1 | 0 | 3.7s | Login failed: login rejected for cavissima_be (bad credentials?) |
| `decanter` | 0 | 0 | 1 | 0 | 2.9s | Decanter search requires a paid Piano subscription. The response contains an empty 'piano-container-search-results' div. Set requires_auth=1 in dim_source and provide valid Piano credentials to enable |
| `figaro_vin` | 0 | 0 | 1 | 0 | 3.3s | avis-vin.lefigaro.fr wine scores are paywalled. /vins?page=N returns HTTP 400. Individual wine pages require a Figaro Premium subscription. Re-implement with authenticated session when credentials are |
| `idealwine_email` | 0 | 0 | 0 | 0 | 2.0s |  |
| `james_suckling` | 0 | 0 | 1 | 0 | 3.6s | jamessuckling.com/top-wines/ is a client-side-only Next.js SPA (no __NEXT_DATA__ in HTML). Wine content requires JS execution. Set requires_auth=1 in dim_source as a proxy for 'needs browser' and prov |
| `lavinia` | 0 | 0 | 0 | 0 | 2.6s | login rejected for lavinia (bad credentials?) |
| `lavinia_email` | 0 | 0 | 0 | 0 | 1.4s |  |
| `millesima_email` | 0 | 0 | 0 | 0 | 1.7s |  |
| `rvf` | 0 | 0 | 1 | 0 | 1.4s | larvf.com (RVF) wine scores are fully paywalled. Public search returns article cards but no /20 scores are visible in HTML. Re-implement with authenticated session when RVF credentials are available. |
| `terredevins` | 0 | 0 | 1 | 0 | 1.4s | terredevins.com wine scores are subscription-gated. /vins and /search?q=...&post_type=vin both return 404. Degustation content requires a premium subscription. Re-implement with authenticated session  |
| `ventealapropriete_email` | 0 | 0 | 0 | 0 | 1.6s |  |
| `wdc_be` | 0 | 0 | 1 | 0 | 1.3s | wdc.be domain is for sale (Nameshift/NVA Online Advertising B.V. — verified 2026-05-23). The wine shop no longer exists at this URL. Source deactivated. |
| `wine_searcher` | 0 | 0 | 0 | 0 | 1.3s | wine_searcher: not implemented — subscription required |

## YELLOW — fetched but inserted 0 (gate / dim resolution)

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `hachette_vins` | 5 | 0 | 5 | 0 | 5.9s |  |
| `inao` | 315 | 0 | 0 | 5 | 3.2s |  |

## GRAY — credentials missing (expected — no creds in .env)

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `cellartracker` | 0 | 0 | 0 | 0 | 1.7s | Credentials missing: set ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD |
| `cellartracker_xlquery` | 0 | 0 | 0 | 0 | 1.7s | Credentials missing: set ACHILLES_AUTH_CELLARTRACKER_USERNAME / _PASSWORD |

## GREEN — fetched and inserted

| scraper | fetched | inserted | dlq | skipped | elapsed | error |
| --- | --- | --- | --- | --- | --- | --- |
| `belgiumwinewatchers` | 0 | 0 | 0 | 18 | 2.6s |  |
| `cavissima` | 5 | 0 | 0 | 5 | 2.7s |  |
| `cinoco` | 5 | 0 | 0 | 5 | 3.4s |  |
| `comptoir_des_millesimes` | 5 | 5 | 0 | 0 | 3.5s |  |
| `ec_agrifood` | 225 | 0 | 0 | 225 | 3.0s |  |
| `eurostat_harvest` | 1710 | 5 | 0 | 543 | 3.0s |  |
| `hachette_vins_shop` | 5 | 0 | 0 | 5 | 2.9s |  |
| `idealwine` | 5 | 5 | 0 | 0 | 14.9s |  |
| `kaggle_reviews` | 129971 | 5 | 0 | 129966 | 17.4s |  |
| `kaggle_reviews_v1` | 150930 | 5 | 0 | 150925 | 18.4s |  |
| `millesima` | 0 | 0 | 0 | 44 | 3.2s |  |
| `millesima_be` | 5 | 1 | 0 | 4 | 3.2s |  |
| `topwijnen_be` | 5 | 2 | 0 | 3 | 5.4s |  |
| `ventealapropriete` | 5 | 0 | 0 | 5 | 3.5s |  |
| `vinatis` | 5 | 1 | 0 | 4 | 3.0s |  |
| `vinsbrunin` | 5 | 0 | 0 | 5 | 3.8s |  |
| `vintage_ratings` | 5 | 5 | 0 | 0 | 3.7s |  |
| `werc` | 9293 | 5 | 0 | 9288 | 44.1s |  |
| `wijnendeclerck_be` | 5 | 3 | 0 | 2 | 11.9s |  |
| `wijnhuis` | 5 | 5 | 0 | 0 | 2.3s |  |
| `xwines` | 1000 | 5 | 0 | 461 | 2.9s |  |
