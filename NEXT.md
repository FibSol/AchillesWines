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

- [ ] **P2 · 4h** [Patroclus] Scrapers iDealwine + Cavissima + Lavinia + Vinatis
- [ ] **P2 · 3h** [Patroclus] Scrapers Belgique : WDC + Cinoco + Wijnhuis
- [ ] **P2 · 3h** [Patroclus] Vintage ratings : Decanter Guide + Wine Spectator vintage charts
- [ ] **P2 · 4h** [Patroclus] Critic ratings publics : RVF articles libres, Decanter articles, James Suckling top-100
- [x] **P2 · 2h** [Cassandra+Odysseus] Confidence badge UI sur chaque cuvée (verified/reviewed/needs_review) ✓ 2026-05-22

## Sprint 6 — Menu pairing

- [x] **P2 · 5h** [Odysseus + Helena] Page Menu : compose menu, drinking window matcher, scoring "depuis ta cave" ✓ 2026-05-22
- [x] **P2 · 3h** [Patroclus → Odysseus v1] API `/api/pairing/propose` avec ranked picks par service ✓ 2026-05-22 (v1 keyword-based, Patroclus to enrich later if needed)
- [x] **P2 · 2h** [Cassandra] Tests algo pairing (lib/pairing.ts scorePairing + course-keyword regex coverage) ✓ 2026-05-22 (28 tests, full suite 66/66)

## Sprint 7 — Déploiement RPi

- [x] **P3 · 3h** [Hector] Dockerfile multi-stage Next + sidecar ✓ 2026-05-22 (closes #6, ADR-007)
- [x] **P3 · 2h** [Hector] docker-compose.yml + nginx reverse proxy ✓ 2026-05-22 (closes #7, ADR-008)
- [ ] **P3 · 2h** [Hector] PWA manifest + service worker (next-pwa)
- [x] **P3 · 1h** [Hector] Backup script SQLite GPG vers NAS ✓ 2026-05-22 (closes #9, ADR-009)
- [ ] **P3 · 3h** [Hector] Home Assistant addon config + integration

## Sprint 9 — Email newsletter ingestion (ADR-011)

- [x] **P2 · 4h** [Patroclus + Cassandra] Email newsletter scraper: IMAP mailbox client + generic HTML parser + EmailNewsletterScraper base + .eml replay + 40 unit tests + docs/EMAIL.md ✓ 2026-05-22 (ADR-011)
- [ ] **P2 · 1h** [Patroclus] Set `from_email` to the real subscriber address for each `*_email` row in dim_source after the user subscribes the mailbox
- [ ] **P3 · 2h** [Patroclus] Per-vendor `_parse_html()` overrides as the generic heuristic shows holes per source
- [ ] **P3 · 3h** [Patroclus] Optional LLM fallback parser (Claude API) for emails the heuristic can't handle — gated behind a per-source `use_llm_fallback` flag to keep API costs predictable

## Sprint 8 — Authentification scrapers (ADR-010)

- [x] **P2 · 3h** [Patroclus + Odysseus + Cassandra] Auth system: `auth.py` + `AuthenticatedScraper` base + `/admin/auth` UI + test_login JobRunner flow + 16 unit tests + docs/AUTH.md ✓ 2026-05-22 (ADR-010)
- [ ] **P2 · 0.5h** [Cassandra] Marquer `requires_auth=1` sur dim_source pour les sources concrètes (idealwine, lavinia, vinatis, rvf) au moment où chaque scraper landed
- [ ] **P3 · 2h** [Patroclus] Persister les sessions dans `ops_auth_sessions` (cookie_jar JSON + expires_at) si le re-login chaque batch devient un problème (rate-limit, latence). Pour l'instant la décision ADR-010 est re-login à chaque fois.

## Idées différées (P3 backlog)

- [ ] OCR étiquette via Claude Vision (photo → ajout cellar)
- [ ] Push notifications PWA pour promos
- [ ] Algorithme de similarité vectorielle pour recommandations
- [ ] LWIN integration si abonnement Liv-ex obtenu un jour
- [ ] Recharts Vintage divergence heatmap (sources × année)
- [ ] X-Wines + Mendeley soMLier snapshot import (crowd reviews)
