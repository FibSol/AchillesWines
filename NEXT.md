# Achilles's Wines — Next Actions

> Owner: Helena (BA). Re-prioritize after each completed task.
> Priority: P0 (blocker) · P1 (sprint) · P2 (nice-to-have) · P3 (backlog)
> Effort: human-hours estimate

## ✅ Sprint 1 (foundations) — TERMINÉ 2026-05-21

Toutes les fondations sont en place : scaffold Next.js 15, schéma Drizzle 16 tables, i18n 6 langues, thème Dionysus, 11 routes UI, skill achilles-progress.
Voir [PROGRESS.md](PROGRESS.md) pour le détail.

## ✅ Sprint 2 — Data foundations (anti-hallucination first) — TERMINÉ 2026-05-21

- [x] **P0 · 1h** [Hector] Setup Python sidecar : pyproject.toml + .venv + dépendances scraping (httpx, selectolax, playwright, apscheduler, rapidfuzz, pydantic, rich)
- [x] **P0 · 4h** [Patroclus] Exporter producer registry depuis burgundy-manager : ~8 700 domaines + AOC + communes + tier
- [x] **P0 · 3h** [Patroclus] Migration import → `dim_producer` avec `allowed_appellations` reconstruit depuis cuvées existantes
- [x] **P0 · 3h** [Patroclus] Importer `dim_appellation` avec coords lat/lng des communes
- [x] **P0 · 2h** [Cassandra] Tests unitaires Vitest sur `lib/identity.ts` : normText, computeWineKey, isAppellationAllowed
- [x] **P0 · 2h** [Cassandra] Tests unitaires sur `lib/quality/gates.ts` : regionGate, criticEnumGate, applyTriSourceRule

## ✅ Sprint 3 — Premier scraper end-to-end + supervision — TERMINÉ 2026-05-21

- [x] **P1 · 4h** [Patroclus] Scraper Millesima avec ETag/Last-Modified + content-hash + DLQ writer
- [x] **P1 · 2h** [Patroclus] CLI rich `achilles-scraper run --source millesima --limit 100`
- [x] **P1 · 3h** [Patroclus] Promoteur batch : staging.price_candidates → fact_price si tri-source rule passée
- [x] **P1 · 2h** [Cassandra] Tests intégration : scraper fictif → DLQ → review approbation manuelle

### 🆕 Supervision & déclenchement manuel (ADR-006)

- [x] **P1 · 1h** [Hector] Ajouter table `ops_job_queue` au schéma Drizzle + migration (job_id, source_key, requested_by, requested_at, status [queued|running|done|failed|cancelled], started_at, finished_at, rows_fetched, rows_inserted, rows_dlq, error_message, batch_id, params JSON)
- [x] **P1 · 2h** [Patroclus] Endpoint `POST /api/jobs` (insert queued job) + `GET /api/jobs` (list with filters) avec Zod validation
- [x] **P1 · 3h** [Odysseus] Page `/admin/jobs` : tableau live des jobs (queue + history des 50 derniers) avec auto-refresh 5 s, badges status (queued/running/done/failed), métriques fetched/inserted/dlq, durée
- [x] **P1 · 2h** [Odysseus] Bouton "🚀 Launch now" par source dans `/admin/jobs` (et raccourci dans `/qualite`) qui POST `/api/jobs` avec source_key + params optionnels (limit, since_date)
- [x] **P1 · 2h** [Patroclus] Job runner Python : poll `ops_job_queue` toutes les 5 s, claim atomique (`UPDATE … SET status='running' WHERE status='queued' LIMIT 1 RETURNING *`), exécute le scraper correspondant, update status final
- [x] **P1 · 1h** [Odysseus] Bouton "✋ Cancel" sur job queued (UPDATE status='cancelled' si toujours queued)
- [x] **P1 · 1h** [Cassandra] Lien depuis chaque job vers le DLQ filtré sur son `batch_id` (un job qui crée 12 DLQ rows → click "12" → liste filtrée)
- [x] **P2 · 2h** [Odysseus] Logs streaming (tail des 100 dernières lignes de log/<batch_id>.log) dans un drawer si on clique sur un job running ✓ 2026-05-22
- [x] **P2 · 1h** [Patroclus] Make scraper runner write per-batch logs to `logs/<batch_id>.log` (stdout + stderr captured) so the new drawer at /admin/jobs has content to tail. Drawer already wired to read this path. ✓ 2026-05-22 (closes #1)

## Sprint 4 — UI core en profondeur

- [x] **P0 · 1h** [Cassandra] Purge prices from wrong source: DELETE from `fact_price` + `staging_price_candidates` any rows where source_key comes from burgundy-manager (not a scraper). Verify only scraper-sourced rows remain (e.g. source_key = 'millesima'). ✓ 2026-05-22 (0 rows found — tables were already clean)
- [x] **P1 · 4h** [Odysseus] Page Best Value : algo de scoring qualité-prix (`(rating_norm_100^2) / log(price_eur)`) ✓ 2026-05-22
- [x] **P1 · 3h** [Odysseus] Page Vintages : heatmap Recharts région × année ✓ 2026-05-22
- [x] **P1 · 4h** [Odysseus] Page Map : React-Leaflet dark tiles + markers corail + GeoJSON régions ✓ 2026-05-22
- [x] **P1 · 3h** [Odysseus] Page Domaine/[id] : détail cuvées, charts prix/ratings, drinking window ✓ 2026-05-22
- [x] **P1 · 4h** [Odysseus] Page Cellar : drag-and-drop entre emplacements, modal ajout/consommation ✓ 2026-05-22
- [x] **P1 · 3h** [Odysseus] Page Cellar CSV import/export + template download ✓ 2026-05-22

## Sprint 5 — Ingestion ramp-up

- [x] **P2 · 0.5h** [Patroclus] Extend `scripts/import-from-burgundy-manager.ts` with a Stage 3 that imports every `cuvees` row from `C:\Users\Nicolas\Bourgogne\burgundy-manager\data\burgundy.db` into `dim_wine` (look up `producer_key` + `appellation_key` already imported in Stages 1-2; compute `wine_key` via `lib/identity`). Closes the gap that makes /vintages heatmap effectively empty on this DB. (Discovered 2026-05-22: `dim_wine` has only the 1 demo wine from seed.ts.) ✓ 2026-05-22 (3 650 wines inserted as NV, 2 148 skipped on appellation mismatch)
- [x] **P2 · 4h** [Patroclus] Scrapers iDealwine + Cavissima + Lavinia + Vinatis ✓ 2026-05-22
- [x] **P2 · 3h** [Patroclus] Scrapers Belgique : WDC + Cinoco + Wijnhuis ✓ 2026-05-22
- [x] **P2 · 3h** [Patroclus] Vintage ratings : Decanter Guide + Wine Spectator vintage charts ✓ 2026-05-22
- [x] **P2 · 4h** [Patroclus] Critic ratings publics : RVF articles libres, Decanter articles, James Suckling top-100 ✓ 2026-05-22
- [x] **P2 · 2h** [Cassandra+Odysseus] Confidence badge UI sur chaque cuvée (verified/reviewed/needs_review) ✓ 2026-05-22

### Sources added 2026-05-22 (login-gated, requires_auth=1)

> ⚠ Credentials were leaked in chat on 2026-05-22 — rotate at each provider before pasting into .env. See ACHILLES_AUTH_* in .env.example for the variable names.

Wine shops:
- [x] **P2 · 1.5h** [Patroclus] Scraper wine-searcher — not yet (no dim_source row, deferred to next sprint)
- [x] **P2 · 1h**   [Patroclus] Scraper cavissima_be (BE) ✓ 2026-05-22
- [x] **P2 · 1.5h** [Patroclus] Scraper ventealapropriete (FR, flash sales) ✓ 2026-05-22
- [x] **P2 · 1h**   [Patroclus] Scraper hachette_vins_shop (FR) ✓ 2026-05-22
- [x] **P2 · 1h**   [Patroclus] Scraper comptoir_des_millesimes (FR) ✓ 2026-05-22
- [x] **P2 · 1h**   [Patroclus] Scraper topwijnen_be (BE) ✓ 2026-05-22
- [x] **P2 · 0.5h** [Patroclus] Scraper millesima_be (BE) ✓ 2026-05-22
- [x] **P2 · 1h**   [Patroclus] Scraper vinsbrunin (FR) ✓ 2026-05-22
- [x] **P2 · 1h**   [Patroclus] Scraper wijnendeclerck_be (BE) ✓ 2026-05-22
- [x] **P2 · 1h**   [Patroclus] Scraper belgiumwinewatchers (BE) ✓ 2026-05-22

Wine press (E_press_critic → write to fact_rating):
- [ ] **P2 · 2h**   [Patroclus] Scraper magazines_fr (aggregator — subscription needed, URL patterns TBD) — [#18](https://github.com/FibSol/AchillesWines/issues/18)
- [x] **P2 · 1.5h** [Patroclus] Scraper figaro_vin (lefigaro.fr/avis-vin) ✓ 2026-05-22
- [x] **P2 · 1.5h** [Patroclus] Scraper terredevins ✓ 2026-05-22
- [x] **P2 · 2h**   [Patroclus] Scraper hachette_vins (guide ratings) ✓ 2026-05-22

## Sprint 11 — Scraper URL fixes + design review

- [x] **P1 · 0.5h** [Patroclus] Fix vinatis.py catalog URL (404 on `/vente-vin?page=1`) — [#14](https://github.com/FibSol/AchillesWines/issues/14) ✓ 2026-05-23
- [x] **P1 · 0.5h** [Patroclus] Fix cavissima.py catalog URL (404 on `/vins/?p=1`) — [#15](https://github.com/FibSol/AchillesWines/issues/15) ✓ 2026-05-23
- [x] **P1 · 1h**   [Patroclus] Tune BE shop URL patterns after first live test (wdc, cinoco, wijnhuis, topwijnen_be) — [#16](https://github.com/FibSol/AchillesWines/issues/16) ✓ 2026-05-23
- [x] **P1 · 0.5h** [Patroclus] Add wine-searcher to dim_source (missed in 0004) + add scraper class — [#17](https://github.com/FibSol/AchillesWines/issues/17) ✓ 2026-05-23
- [x] **P1 · 3h**   [Odysseus] Design review + Athena redesign: replaced Dionysus palette/fonts with Athena (noir/magenta/crème/champagne + Fraunces + Inter via next/font) ✓ 2026-05-23 — [#23](https://github.com/FibSol/AchillesWines/issues/23)

## Sprint 6 — Menu pairing

- [x] **P2 · 5h** [Odysseus + Helena] Page Menu : compose menu, drinking window matcher, scoring "depuis ta cave" ✓ 2026-05-22
- [x] **P2 · 3h** [Patroclus → Odysseus v1] API `/api/pairing/propose` avec ranked picks par service ✓ 2026-05-22 (v1 keyword-based, Patroclus to enrich later if needed)
- [x] **P2 · 2h** [Cassandra] Tests algo pairing (lib/pairing.ts scorePairing + course-keyword regex coverage) ✓ 2026-05-22 (28 tests, full suite 66/66)

## Sprint 7 — Déploiement RPi

- [x] **P3 · 3h** [Hector] Dockerfile multi-stage Next + sidecar ✓ 2026-05-22 (closes #6, ADR-007)
- [x] **P3 · 2h** [Hector] docker-compose.yml + nginx reverse proxy ✓ 2026-05-22 (closes #7, ADR-008)
- [x] **P3 · 2h** [Hector] PWA manifest + service worker (next-pwa) ✓ 2026-05-22
- [x] **P3 · 1h** [Hector] Backup script SQLite GPG vers NAS ✓ 2026-05-22 (closes #9, ADR-009)
- [x] **P3 · 3h** [Hector] Home Assistant addon config + integration ✓ 2026-05-22

## Sprint 9 — Email newsletter ingestion (ADR-011)

- [x] **P2 · 4h** [Patroclus + Cassandra] Email newsletter scraper: IMAP mailbox client + generic HTML parser + EmailNewsletterScraper base + .eml replay + 40 unit tests + docs/EMAIL.md ✓ 2026-05-22 (ADR-011)
- [ ] **P2 · 1h** [Patroclus] Set `from_email` to the real subscriber address for each `*_email` row in dim_source after the user subscribes the mailbox — [#19](https://github.com/FibSol/AchillesWines/issues/19)
- [ ] **P3 · 2h** [Patroclus] Per-vendor `_parse_html()` overrides as the generic heuristic shows holes per source — [#20](https://github.com/FibSol/AchillesWines/issues/20)
- [ ] **P3 · 3h** [Patroclus] Optional LLM fallback parser (Claude API) for emails the heuristic can't handle — gated behind a per-source `use_llm_fallback` flag to keep API costs predictable — [#21](https://github.com/FibSol/AchillesWines/issues/21)

## Sprint 8 — Authentification scrapers (ADR-010)

- [x] **P2 · 3h** [Patroclus + Odysseus + Cassandra] Auth system: `auth.py` + `AuthenticatedScraper` base + `/admin/auth` UI + test_login JobRunner flow + 16 unit tests + docs/AUTH.md ✓ 2026-05-22 (ADR-010)
- [x] **P2 · 0.5h** [Cassandra] Marquer `requires_auth=1` sur dim_source pour les sources concrètes (idealwine, lavinia, vinatis, rvf) ✓ 2026-05-22 (migration 0005)
- [ ] **P3 · 2h** [Patroclus] Persister les sessions dans `ops_auth_sessions` (cookie_jar JSON + expires_at) si le re-login chaque batch devient un problème (rate-limit, latence). Pour l'instant la décision ADR-010 est re-login à chaque fois. — [#22](https://github.com/FibSol/AchillesWines/issues/22)

## Sprint 10 — Robustesse & orchestration scraper

- [x] **P2 · 2h** [Patroclus] Retry + backoff sur site down : si `_fetch_build_id()` échoue (site down ou timeout), retenter automatiquement avec backoff exponentiel (ex. 3 tentatives : 30 s → 5 min → 30 min) avant d'abandonner et écrire en DLQ. Le scraper doit être 100 % autonome. ✓ 2026-05-22
- [x] **P2 · 1h** [Patroclus] Cache du buildId Next.js : persister le dernier buildId connu dans `ops_batch_log` ou un fichier `.millesima_build_id` pour pouvoir continuer à scraper même si la homepage est down (le buildId ne change qu'au redéploiement). ✓ 2026-05-22
- [x] **P2 · 2h** [Hector] Scheduler APScheduler dans le job runner Python : lancer automatiquement les scrapers web (millesima, idealwine…) sur un cron configurable (ex. 1×/jour à 3h00) sans intervention manuelle. ✓ 2026-05-22
- [x] **P2 · 1h** [Patroclus] Scraper email + scraper web en parallèle : lancer `millesima` (web) + `millesima_email` / `idealwine_email` / `lavinia_email` (IMAP) simultanément via `concurrent.futures.ThreadPoolExecutor` dans le job runner, chaque source restant isolée avec son propre batch_id. ✓ 2026-05-22

## Sprint 13 — Full-catalog ingestion + price quality

- [x] **P0 · 3h** [Patroclus] Fix wine_key identity divergence (vintage in producer, appellation in hash, Shopify vendor=shop-name) → first cross-source overlap; full-catalog run: 1752 wine_keys in fact_price ✓ 2026-05-23
- [x] **P1 · 1h** [Patroclus] Run wijnhuis unlimited scrape (currently only 500 from benchmark); run promoter after to add BE overlap ✓ 2026-05-23
- [x] **P1 · 1h** [Patroclus] Add promote button to /admin/jobs UI (POST /api/promote) with stats chip (N pending, M overlap) ✓ 2026-05-23
- [x] **P2 · 1h** [Odysseus] Best Value page: price-confidence fallback mode when fact_rating empty (shows 1787 wines ranked by multi-source price agreement) ✓ 2026-05-23
- [x] **P0 · 2h** [Patroclus] Fix staging_price_candidates dedup bug: add UNIQUE INDEX on (wine_key, source_key, content_hash); add insert_staging_candidate() helper; migrate all 6 retail scrapers; purge 56,460 duplicate rows + 14,190 inflated fact_price rows; re-run promoter → 1,383 clean rows ✓ 2026-05-23
- [x] **P2 · 2h** [Patroclus] Run topwijnen_be full catalog (Shopify) — 5,910 products staged (deduped) + promoter ran ✓ 2026-05-23 (wdc_be still pending)
- [ ] **P2 · 1h** [Patroclus] Run wdc_be full catalog to widen overlap coverage
- [ ] **P2 · 3h** [Patroclus] Rewrite vinsbrunin scraper for WiziShop platform (current code uses WooCommerce selectors; site uses `/bordeaux/`, `/bourgogne/`, etc. with `?page=N` pagination; no single catalog URL)
- [ ] **P2 · 2h** [Patroclus] Force-clear millesima content hashes + re-run to fix ~1092 Champagne/NV wines stuck in DLQ (appellation="" — fix applied but cached pages won't re-trigger)

## Sprint 12 — Production data migration

- [ ] **P1 · 1h** [Patroclus] Migrate dev DB → prod RPi once ≥ 80% of scrapers have at least one successful `done` run. Gate: `SELECT COUNT(DISTINCT source_key) FROM ops_job_queue WHERE status='done'` ≥ 80% of enabled sources. Script `scripts/migrate-dev-to-prod.ps1`: dump dim_producer, dim_appellation, dim_wine, bridge_wine_variety, fact_price, fact_rating, fact_vintage_rating, staging_price_candidates, cellar_* from dev; SCP to RPi; stop add-on, apply, restart; print row counts before/after. Do NOT overwrite dim_source, ops_scraper_schedule, ops_* tables on prod. — [#29](https://github.com/FibSol/AchillesWines/issues/29)

## Idées différées (P3 backlog)

- [ ] OCR étiquette via Claude Vision (photo → ajout cellar) — [#24](https://github.com/FibSol/AchillesWines/issues/24)
- [ ] Push notifications PWA pour promos — [#25](https://github.com/FibSol/AchillesWines/issues/25)
- [ ] Algorithme de similarité vectorielle pour recommandations — [#26](https://github.com/FibSol/AchillesWines/issues/26)
- [ ] LWIN integration si abonnement Liv-ex obtenu un jour
- [ ] Recharts Vintage divergence heatmap (sources × année) — [#27](https://github.com/FibSol/AchillesWines/issues/27)
- [ ] X-Wines + Mendeley soMLier snapshot import (crowd reviews) — [#28](https://github.com/FibSol/AchillesWines/issues/28)
