# Reliability audit — 2026-05-23

Source DB: `data\achilles.db`  (1497 MB)

## ⚠ Critical findings (read this first)

Ordered by impact on DB reliability. The raw queries that produced these are in
the sections below.

### F-1 — Foreign keys aren't enforced on the Python side (P0)

`PRAGMA foreign_keys = 0` on the audit connection — that's the SQLite default,
and the Python scrapers inherit it. Drizzle (TypeScript) turns FKs on per
connection so writes from the Next.js app DO enforce them, which is why the
**hachette_vins** scraper is generating *13,650 "FOREIGN KEY constraint failed"*
DLQ rows: those few inserts happen to go through a connection with FKs on, and
they reference wine_keys that were never added to `dim_wine` first.

**Direct consequence:** `dim_wine → dim_producer` has **841 orphan rows**.
Producers were deleted while their wines remained. With FKs enforced, this
would have been impossible.

Fix: every Python scraper opening a sqlite connection must `PRAGMA foreign_keys = ON`.
Add it to `achilles_scraper.db.get_db()` so it's centralised.

### F-2 — 73% of dim_producer rows are stuck in `pending_review` (P1)

**24,166 / 32,901** producers have status='pending_review'. The promoter
auto-creates them when a scraper sees a new producer, but nothing ever moves
them to `active`. Without an enrichment / approval workflow they accumulate
forever and pollute matching (anything joining on `status='active'` silently
filters them out).

Fix options: (a) batch-approve producers that appear in ≥N retailer scrapes,
(b) build a `/admin/producers/pending` page, or (c) downgrade the gate so new
producers land in `active` directly when seen from ≥2 sources (mirrors the
tri-source rule).

### F-3 — `fact_rating` is effectively a single-source table (P1)

| source | rows | share |
| --- | --- | --- |
| `kaggle_reviews` (WE, user_aggregate) | 264,942 | 99.98% |
| `xwines` (XW, user_aggregate) | 50 | 0.02% |
| `hachette_vins` (Hachette, critic) | 4 | 0.00% |

ADR-013 requires ≥2 critic sources before a rating promotes. Today we have
essentially **one source** (a one-shot Kaggle dump) feeding ratings.
The press scrapers (rvf, decanter, james_suckling, figaro_vin, terredevins,
hachette_vins, hachette_vins_guide) have produced **8 ratings total** between
them. They're all wired but only `hachette_vins` is actually running, and it's
hitting the FK wall (see F-1).

Also: `critic_code='XW'` is not in the closed enum (`['BH','CT','Decanter','GV',
'Hachette','Halliday','JG','JMIB','JS','RVF','Vinous','WA','WAL','WD','WE','WS']`).
Either add `XW` to the enum or remap it.

### F-4 — `ops_batch_log` is silent for 37/38 scrapers (P1)

Only the INAO scraper writes batch-log entries. Every other run is invisible to
the supervision UI at `/admin/jobs`, which relies on this table for history.
The job_runner writes to `ops_job_queue` (112 rows) but not to `ops_batch_log` —
two parallel ledgers, both half-populated.

Fix: pick one. Either fold `ops_job_queue` into `ops_batch_log` or have the
runner mirror writes to both. Current state defeats the supervision feature.

### F-5 — Duplicate INAO source (case mismatch) (P2)

`dim_source` has `source_code='INAO'` (key=40, only one actively writing) but
`_ALL_SOURCES` in `cli.py` and the migrations both reference `'inao'`. Either
the CLI alias resolves case-insensitively (lucky) or one of them is dead.
Either way, normalise to `'inao'` and DELETE the stray uppercase row (no facts
attached to it, safe to drop).

### F-6 — Grape variety feature is empty (P2)

`dim_variety = 0`, `bridge_wine_variety = 0`. If the UI exposes varietal
filtering or composition, it's broken. Either implement the import (we already
parse varietal strings in several scrapers) or hide the UI surface.

### F-7 — Appellation map coverage is 23% (P2)

497 / 2,128 `dim_appellation` rows have lat/lng. The map view will look sparse
for everything outside the burgundy-manager import. INAO open data has
commune-level coordinates — a one-shot geocoding pass against the INAO
appellation list would fix this.

---

## 1. Row counts

| table | rows |
| --- | --- |
| dim_source | 38 |
| dim_producer | 32,901 |
| dim_appellation | 2,128 |
| dim_variety | 0 |
| dim_wine | 149,601 |
| bridge_wine_variety | 0 |
| fact_price | 2,355 |
| fact_rating | 264,996 |
| fact_vintage_rating | 1,059 |
| cellar_locations | 36 |
| cellar_inventory | 0 |
| cellar_consumption | 0 |
| ops_dead_letter | 17,071 |
| ops_content_hashes | 3,556 |
| ops_batch_log | 2 |
| ops_job_queue | 112 |
| staging_price_candidates | 31,661 |
| fact_market_index | 217 |
| fact_harvest_volume | 548 |
| fact_werc_stats | 9,293 |

## 2. Source coverage

Rows produced per source across fact tables.

| source_code | tier | auth | enabled | fact_price | fact_rating | staging | DLQ | last_run_at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| kaggle_reviews | D_user_aggregate | 0 | 1 | 0 | 264942 | 0 | 0 |  |
| millesima | B_retailer_major | 0 | 1 | 568 | 0 | 9295 | 1664 |  |
| topwijnen_be | B_retailer_major | 1 | 1 | 813 | 0 | 5910 | 0 |  |
| cavissima | B_retailer_major | 0 | 1 | 161 | 0 | 4013 | 1242 |  |
| vinatis | B_retailer_major | 1 | 1 | 175 | 0 | 3293 | 328 |  |
| cinoco | B_retailer_major | 0 | 1 | 14 | 0 | 3148 | 154 |  |
| wijnendeclerck_be | B_retailer_major | 1 | 1 | 116 | 0 | 1756 | 0 |  |
| hachette_vins_shop | B_retailer_major | 1 | 1 | 161 | 0 | 1134 | 2 |  |
| wijnhuis | B_retailer_major | 0 | 1 | 12 | 0 | 930 | 0 |  |
| ventealapropriete | B_retailer_major | 1 | 1 | 118 | 0 | 676 | 0 |  |
| millesima_be | B_retailer_major | 1 | 1 | 166 | 0 | 499 | 1 |  |
| comptoir_des_millesimes | B_retailer_major | 1 | 1 | 24 | 0 | 500 | 2 |  |
| idealwine | B_retailer_major | 1 | 1 | 16 | 0 | 459 | 0 |  |
| xwines | D_user_aggregate | 0 | 1 | 0 | 50 | 0 | 0 |  |
| vinsbrunin | B_retailer_major | 1 | 1 | 4 | 0 | 30 | 1 |  |
| belgiumwinewatchers | B_retailer_major | 1 | 1 | 7 | 0 | 18 | 0 |  |
| hachette_vins | E_press_critic | 1 | 1 | 0 | 4 | 0 | 13652 |  |
| INAO | A_official | 0 | 1 | 0 | 0 | 0 | 0 | 1779552914 |
| burgundy_manager | A_official | 0 | 1 | 0 | 0 | 0 | 0 |  |
| cavissima_be | B_retailer_major | 1 | 1 | 0 | 0 | 0 | 3 |  |
| decanter | E_press_critic | 1 | 1 | 0 | 0 | 0 | 4 |  |
| ec_agrifood | A_official | 0 | 1 | 0 | 0 | 0 | 2 |  |
| eurostat_harvest | A_official | 0 | 1 | 0 | 0 | 0 | 0 |  |
| figaro_vin | E_press_critic | 1 | 1 | 0 | 0 | 0 | 3 |  |
| idealwine_email | B_retailer_major | 0 | 1 | 0 | 0 | 0 | 0 |  |
| james_suckling | E_press_critic | 1 | 1 | 0 | 0 | 0 | 1 |  |
| lavinia | B_retailer_major | 1 | 1 | 0 | 0 | 0 | 0 |  |
| lavinia_email | B_retailer_major | 0 | 1 | 0 | 0 | 0 | 0 |  |
| magazines_fr | E_press_critic | 1 | 1 | 0 | 0 | 0 | 0 |  |
| millesima_email | B_retailer_major | 0 | 1 | 0 | 0 | 0 | 0 |  |
| rvf | E_press_critic | 1 | 1 | 0 | 0 | 0 | 2 |  |
| terredevins | E_press_critic | 1 | 1 | 0 | 0 | 0 | 6 |  |
| ventealapropriete_email | B_retailer_major | 0 | 1 | 0 | 0 | 0 | 0 |  |
| vintage_consensus | E_press_critic | 0 | 1 | 0 | 0 | 0 | 0 |  |
| wdc_be | B_retailer_major | 0 | 0 | 0 | 0 | 0 | 2 |  |
| werc | A_official | 0 | 1 | 0 | 0 | 0 | 2 |  |
| wine_searcher | B_retailer_major | 1 | 1 | 0 | 0 | 0 | 0 |  |
| wine_spectator | F_vintage_authority | 0 | 1 | 0 | 0 | 0 | 0 |  |

## 3. Dim integrity

| metric | value |
| --- | --- |
| dim_producer total | 32,901 |
| dim_producer status=pending_review | 24,166 |
| dim_producer status=deprecated | 0 |
| dim_appellation total | 2,128 |
| dim_appellation with lat/lng | 497 |
| dim_wine total | 149,601 |
| dim_wine NV (is_non_vintage=1) | 9,718 |
| dim_wine with vintage | 139,883 |

### Orphan facts (FK violations would show > 0)

| relation | orphan_count |
| --- | --- |
| fact_price → dim_wine | 0 |
| fact_rating → dim_wine | 0 |
| staging_price_candidates → dim_wine | 0 |
| dim_wine → dim_producer | 841 |
| dim_wine → dim_appellation | 0 |

### Duplicate dim_producer (producer_norm, country_code)

*(no rows)*

### Duplicate dim_appellation (country_code, appellation_norm)

*(no rows)*

## 4. fact_rating critic-code conformance

Closed enum per ADR-013 / scrapers: `['BH', 'CT', 'Decanter', 'GV', 'Hachette', 'Halliday', 'JG', 'JMIB', 'JS', 'RVF', 'Vinous', 'WA', 'WAL', 'WD', 'WE', 'WS']`

| critic_code | reviewer_type | rows | in_enum? |
| --- | --- | --- | --- |
| WE | user_aggregate | 264942 | ✓ |
| XW | user_aggregate | 50 | ❌ not in enum |
| Hachette | critic | 4 | ✓ |

## 5. ops_dead_letter histogram

Total DLQ rows: **17,071**

### By error_class

| error_class | rows |
| --- | --- |
| validation_error | 13650 |
| parse_error | 2062 |
| unresolved_dim | 1336 |
| auth_error | 12 |
| network_error | 8 |
| scraper_not_applicable | 2 |
| source_dead | 1 |

### Top 30 (source, error_class) cells

| source_code | error_class | rows |
| --- | --- | --- |
| hachette_vins | validation_error | 13650 |
| cavissima | parse_error | 1242 |
| millesima | unresolved_dim | 1094 |
| millesima | parse_error | 570 |
| vinatis | unresolved_dim | 241 |
| cinoco | parse_error | 154 |
| vinatis | parse_error | 87 |
| terredevins | network_error | 4 |
| cavissima_be | auth_error | 3 |
| decanter | parse_error | 2 |
| ec_agrifood | parse_error | 2 |
| figaro_vin | auth_error | 2 |
| hachette_vins | network_error | 2 |
| hachette_vins_shop | parse_error | 2 |
| rvf | auth_error | 2 |
| terredevins | auth_error | 2 |
| werc | parse_error | 2 |
| comptoir_des_millesimes | auth_error | 1 |
| comptoir_des_millesimes | parse_error | 1 |
| decanter | auth_error | 1 |
| decanter | network_error | 1 |
| figaro_vin | network_error | 1 |
| james_suckling | scraper_not_applicable | 1 |
| millesima_be | unresolved_dim | 1 |
| vinsbrunin | auth_error | 1 |
| wdc_be | scraper_not_applicable | 1 |
| wdc_be | source_dead | 1 |

## 6. ops_batch_log — recent batches

| batch_id | source | fetched | inserted | dlq | status | started | finished | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| inao-20260523-161511-737aeeeb | INAO | 315 | 0 | 0 | success | 2026-05-23 16:15:14 | 2026-05-23 16:15:14 | inao_api_count=0 geojson_features=0 |
| inao-20260523-161448-bb889f1f | INAO | 315 | 291 | 0 | success | 2026-05-23 16:14:49 | 2026-05-23 16:14:49 | inao_api_count=0 geojson_features=0 |

### Batches with rows_fetched > 0 AND rows_inserted = 0

Strong signal of a broken gate, mismatched dim, or parsing-but-failing-validation.

| source_code | bad_batches | fetched_total | dlq_total |
| --- | --- | --- | --- |
| INAO | 1 | 315 | 0 |

## 7. Cellar sanity

| metric | value |
| --- | --- |
| cellar_locations | 36 |
| cellar_inventory rows | 0 |
| cellar_inventory distinct wines | 0 |
| cellar_inventory orphan (no dim_wine) | 0 |
| cellar_consumption rows | 0 |
