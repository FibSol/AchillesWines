# Changelog

All notable changes to Achilles's Wines are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [1.3.0] — 2026-06-08

### Added
- Cellar KPIs panel (total bottles, locations in use, avg score) + bottle details dialog
- Tasting page filters (appellation, vintage, score range)
- Pairing page: purchase price fallback chip when no market price is available
- **Apollo (Design Reviewer)** added to the team — UI/UX audit role with a local Clone-Wars benchmark catalogue

### Changed
- **Completed the Dionysus→Athena design migration** — swept ~111 dead `coral` token references across 27 components, plus dead `mint`/`aubergine` tokens, all reclassified to Athena tokens (magenta = interactive, champagne = data) per ADR-012
- Recolored the categorical data palette (wine-type maps, chart series, map tier markers) to an Athena-derived palette
- Dashboard refresh: live status pill, editorial hairline, ADR-012 icon semantics; DLQ ops metric moved out of the consumer stat grid into the pipeline-status strip
- Dashboard strings fully internationalized (quick-card descriptions + pipeline status across all 6 locales)

### Fixed
- Restored the app's accent color app-wide — icons/accents that silently fell back to cream text after the incomplete ADR-012 migration now render correctly

---

## [1.2.1] — 2026-06-06

### Changed
- Resize cellar grid to 20 locations × 200 bottles per location (was 15 × 120)

---

## [1.2.0] — 2026-06-05

### Added
- **Wine Tasting tab** with 6 sommelier flight logics (regional, varietal, vertical, progressive, contrast, food-pairing)
- Factual wine description card for each tasting flight
- **OCR wine label scan** via Claude Vision — add bottles to cellar by photographing the label (#24)
- **Wine similarity vectors + recommendations UI** — find bottles similar to any wine in the cellar (#26)
- **Vintage divergence heatmap** — sources × year comparison grid (#27)
- **X-Wines full import + soMLier crowd reviews** — 1 M+ crowd scores (#28)
- **iDealwine historical auction scraper** — auction hammer prices as price signals (#35)
- **LLM email fallback parser** via Claude Haiku for newsletters with non-standard layouts (#21)
- Dev-to-prod DB copy via `VACUUM INTO` snapshot — proven full-database migration runbook

### Fixed
- Cellar bottle chips: tappable on iOS touch devices (Radix instant-dismiss bug resolved)
- Disable bottle-chip drag on touch so taps register correctly
- Grand vin fallback display + apostrophe-space cleanup on domaines page

### Data
- RVF N°701 complete import: all tasting pages + Bordeaux 2023/2024 vintage prices
- VdF mixed-portfolio web research — deleted 355 non-French, fixed 103 appellations
- Naming cleanup wave 2: CB codes, appellation tails, non-French deletions (#45)
- Manual review wave 1: merged duplicate producers, fixed VdF appellations
- PCT cleanup: 400 fake producer names fixed, 509 wines remapped
- Bridge wine-variety populated via appellation-default grape rules (#42)

---

## [1.1.4] — 2026-05-31

### Fixed
- HA sidebar: use Settings → Dashboards → Webpage panel (ingress + panel_iframe both broken with Next.js asset paths)
- Install guide Part 10 updated with correct UI-based approach

---

## [1.1.3] — 2026-05-31

### Fixed
- 404 on sidebar click: switch to `panel_iframe` pointing at `homeassistant.local:3000` (direct port, no path rewriting)
- Install guide Part 10 updated with `panel_iframe` configuration

---

## [1.1.2] — 2026-05-31

### Fixed
- "Show in sidebar" toggle missing — ingress config was only in `ha-addon/config.yaml`, not deployed `addon/config.yaml`
- Added `CHANGELOG.md` to addon directory so the Changelog tab renders in HA

---

## [1.1.1] — 2026-05-31

### Added
- HA ingress sidebar entry (`ingress: true`, `panel_icon`, `panel_title`) — "Show in sidebar" toggle in add-on Info tab
- Install guide Part 10: automatic ingress sidebar documentation

---

## [1.1.0] — 2026-05-25

### Added
- **Wine-Searcher Pro API scraper** via Firecrawl search API (#34)
- **CellarTracker browser-session scraper** via Claude-in-Chrome MCP
- **CellarTracker xlquery scraper** + ADR-014 critic-hub strategy
- **Per-vendor email parsers** for Millesima, iDealwine, Lavinia newsletters (#20)
- **Daily email ingestion** via Proton Bridge at 16:00 CET — delete-after-scrape behaviour
- **Auth sessions table** (`ops_auth_sessions`) — persist JWT/cookie sessions across scraper batches (#22)
- **Vivino tiebreaker scraper + promote gate** (#37)
- **Rating promoter gate** — ≥2 distinct critic sources required for `fact_rating` (#33)
- **Producer registry expansion** — CIVB, BIVB, Inter-Rhône, InterLoire, CIVC, CIVA, CIVL syndicate members (#31)
- **Coverage tier + dashboard** — `coverage_tier` column, admin coverage page, mono-source purge (#32 #36 #38)
- **INAO French appellation ingestor** — Phase 0 official AOC reference (#30 #39)
- **WineEnthusiast 130k ratings** via Kaggle API ingestion
- Best Value page now includes `staging_price_candidates`
- Price research scripts + visible shop buttons on price table
- Full domaine page rebuild: cuvées summary, score chart, detail table
- AOC sweep: corrected 209 country codes, fixed INAO encoding bug, normalised 35+ name aliases
- Cuvée similarity audit + accent normalisation

### Fixed
- Hachette Shopware 6 + VenteALaPropriete Algolia rewrite
- Millesima Nouveautés inline parser + delete-on-failure guard
- Scraper URL fixes: wijnhuis, topwijnen_be, xwines, wine-searcher
- `job_runner` DB opened via `get_db()` so FK constraints are enforced
- Scraper log path + verbose per-page logging in web drawer
- Staging dedup — UNIQUE INDEX + `insert_staging_candidate` helper

### Removed
- Christie's scraper retired (API dead as of May 2026)

---

## [1.0.5] — 2026-05-23

### Added
- Schedule configuration panel on admin/auth page — set cron schedules per scraper from the web UI
- New DB table `ops_scraper_schedule` (migration 0006) — schedules persist across restarts
- Job runner reads schedules from DB (+ env var overrides) and refreshes live every 60 s
- New API route `GET/PATCH /api/schedules`

---

## [1.0.4] — 2026-05-23

### Fixed
- APScheduler crash on Alpine: pass explicit `timezone="UTC"` to `BackgroundScheduler`
- Add `tzdata` to Dockerfile for system timezone data
- Next.js 16 warning: move `themeColor` from `metadata` to `generateViewport` in root layout

---

## [1.0.3] — 2026-05-23

### Added
- Watchdog health check (`http://[HOST]:3000/`) for automatic add-on restart on crash
- Graceful SIGTERM/SIGINT shutdown — Node.js and Python scraper both stopped cleanly
- OCI image labels (`org.opencontainers.image.*`, `io.hass.*`) via `build.yaml`
- `log_level` option with schema validation

---

## [1.0.2] — 2026-05-23

### Fixed
- Docker build: switch to `node:22-alpine` + `npm install` (resolves lockfile version mismatch)
- Remove `playwright` from scraper dependencies (no musl/aarch64 wheel; unused)
- Add `ARG CACHEBUST` to force fresh git clone on version change

---

## [1.0.1] — 2026-05-23

### Added
- Initial Home Assistant add-on packaging
- Node.js 22 + Python 3 in Alpine container
- `/data` volume mapped for persistent SQLite database
- Scraper job runner starts alongside Next.js web server

---

## [0.1.0] — 2026-05-22

### Added
- Initial commit — Achilles's Wines project scaffold
- Next.js 16 + React 19 + Drizzle + better-sqlite3 + Tailwind v4 + next-intl
- Athena design system (noir `#0F0E17`, magenta vin `#A53860`, crème `#F7F4EA`, or champagne `#E5B25D`)
- Multilingual UI: FR / EN / NL / DE / ES / IT
- Core schema: `dim_producer`, `dim_appellation`, `dim_wine`, `fact_price`, `fact_rating`
- Cellar module: storage locations, inventory, consumption log
- Domaines explorer with map (Leaflet), filters, region heatmap
- Python scraper sidecar: httpx + selectolax + APScheduler + Pydantic + Rich
- Docker Compose + nginx reverse proxy
- Encrypted backup/restore scripts
