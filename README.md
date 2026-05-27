# Achilles's Wines

> Personal home wine cellar app. Multilingual, multi-source, strict data quality.  
> Design Athena · Raspberry Pi 5 + Home Assistant deployment.

---

## What it does

A full-stack personal wine cellar app that:
- Tracks your bottles across 36 storage locations (4 320 max capacity)
- Scrapes prices from 37 sources (FR/BE retailers, wine press, official registries)
- Enforces strict multi-source validation — no data enters `fact_price` or `fact_rating` from a single source
- Gives you a **Best Value** ranking, **Vintage heatmap**, **Interactive map**, and **Menu pairing**
- Runs entirely on your home network — no cloud, no subscription

---

## Install — Local development (Windows)

> These steps assume Windows 10/11, Node.js 20+ and Python 3.12 installed.

### 1. Clone the repo

```powershell
cd C:\Claude
git clone https://github.com/FibSol/AchillesWines.git achilles-wines
cd achilles-wines
```

### 2. Install Node dependencies

```powershell
npm install
```

> `better-sqlite3` compiles a native addon. If it fails, install the Windows build tools first:
> ```powershell
> npm install --global windows-build-tools
> ```

### 3. Set up the environment

```powershell
Copy-Item .env.example .env
```

Open `.env` in your editor. The defaults work for local dev — the only thing worth filling in now is an optional `ANTHROPIC_API_KEY` if you want LLM email fallback parsing.

### 4. Create and migrate the database

```powershell
npm run db:migrate
npm run db:seed
```

This creates `data/achilles.db` with the schema (17 tables) and seeds 36 cellar locations, 13 data sources, and a demo wine.

### 5. (Optional) Import from burgundy-manager

If you have an existing `burgundy-manager` database, run the import scripts to bring over ~8 700 producers, appellations, and cuvées:

```powershell
npx tsx scripts/import-from-burgundy-manager.ts
```

> The script reads `C:\Users\Nicolas\Bourgogne\burgundy-manager\data\burgundy.db` by default.
> See `scripts/import-from-burgundy-manager.ts` for the `--source` flag to override the path.

### 6. Start the web app

```powershell
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The dashboard shows live stats from the DB.

### 7. Set up the Python scraper sidecar

In a second terminal:

```powershell
cd C:\Claude\achilles-wines\scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Run a quick test:

```powershell
python -m achilles_scraper.cli --help
```

Run a scraper manually (example — Millesima, 50 products):

```powershell
python -m achilles_scraper.cli run --source millesima --limit 50
```

Trigger the promoter (moves staged prices to `fact_price` if ≥2 sources agree ±15%):

```powershell
python -m achilles_scraper.cli promote
```

### 8. (Optional) Configure scraper credentials

Some sources require a login. Set credentials in `.env`:

```dotenv
# Example: iDealwine account
ACHILLES_AUTH_IDEALWINE_USERNAME=your@email.com
ACHILLES_AUTH_IDEALWINE_PASSWORD=yourpassword
```

See [docs/AUTH.md](docs/AUTH.md) for the full list and test-login instructions, and [docs/EMAIL.md](docs/EMAIL.md) for the IMAP newsletter ingestion setup.

---

## Install — Production on Raspberry Pi 5 + Home Assistant

See **[docs/INSTALL_HAOS.md](docs/INSTALL_HAOS.md)** for the full step-by-step guide (no Linux experience required).

**Summary of steps:**
1. Install the Advanced SSH add-on in Home Assistant
2. SSH in and clone the repo to `/share/achilles-wines`
3. `cp .env.example .env` and fill in your settings
4. `docker compose build` (takes 10–15 min on first run, ARM64 compile)
5. `docker compose up -d`
6. Open `http://<your-rpi-ip>:8080` in any browser on your local network

The compose stack runs 3 containers: `web` (Next.js), `scraper` (Python sidecar), `nginx` (reverse proxy).  
Auto-restart on reboot is built in via `restart: unless-stopped`.

---

## Migrate dev → production

Once you're happy with the local state (≥80% of scrapers have run at least once):

```powershell
# Dry run first
.\scripts\migrate-dev-to-prod.ps1 --dry-run

# Live run
.\scripts\migrate-dev-to-prod.ps1
```

Set `ACHILLES_RPI_HOST` in your local `.env` to the RPi IP before running.  
The script dumps `dim_producer`, `dim_appellation`, `dim_wine`, `fact_price`, `fact_rating`, `cellar_*`, SCP to the RPi, stops the addon, applies, restarts, and prints row counts.

---

## Run the test suites

```powershell
# TypeScript + Vitest (frontend tests)
npx vitest run

# TypeScript type check
npx tsc --noEmit

# Python unit tests (scraper)
cd scraper
python -m pytest scraper/tests/ -v
```

Current status: **209/209 Python · 72/72 Vitest · 0 TS errors**

---

## Architecture

```
┌─────────────────────────┐     ┌──────────────────────────────┐
│  Next.js 16 (web)       │     │  Python sidecar (scraper)    │
│  ├─ /[locale]/*         │     │  ├─ 37 scrapers              │
│  ├─ /api/*              │◄────│  ├─ job_runner (APScheduler) │
│  ├─ Drizzle + SQLite    │     │  ├─ promoter (tri-source)    │
│  └─ next-intl (6 langs) │     │  └─ cli (manual runs)        │
└────────────┬────────────┘     └──────────────────────────────┘
             │ shared SQLite WAL (achilles-data volume)
             ▼
┌─────────────────────────┐
│  nginx (reverse proxy)  │
│  :8080 → web:3000       │
└─────────────────────────┘
```

Full documentation: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Data quality gates

The previous project (`burgundy-manager`) accumulated data bugs (Raveneau matched to Bordeaux, Laroche to Sancerre). Achilles's Wines enforces 6 gates:

| # | Gate | What it does |
|---|------|-------------|
| 1 | **Producer registry** | Pre-validated seed (8 700 domaines + official syndicats CIVB/BIVB/CIVC/etc.) |
| 2 | **Hard region gate** | `appellation ∈ producer.allowed_appellations` — mismatches → DLQ |
| 3 | **Tri-source rule (price)** | ≥2 sources agree ±15% → `fact_price`; mono-source → `staging` |
| 4 | **Bi-source rule (rating)** | ≥2 critic sources per wine → `fact_rating`; Vivino tiebreaker only |
| 5 | **Critic enum** | Closed set: WA, Vinous, BH, JMIB, RVF, Decanter, JS, JG, WS, Hachette, CT, XW, WE |
| 6 | **DLQ** | All rejected rows land at `/quarantaine` for manual review |

---

## Documentation

### Project & architecture
- [**docs/TEAM.md**](docs/TEAM.md) — The 5 team roles: Helena, Hector, Patroclus, Odysseus, Cassandra
- [**docs/ARCHITECTURE.md**](docs/ARCHITECTURE.md) — Stack, Docker deployment, ETL pipeline
- [**DECISIONS.md**](DECISIONS.md) — Architecture Decision Records (ADR-001 → ADR-014)
- [**PROGRESS.md**](PROGRESS.md) — Append-only delivery log (reverse-chronological)
- [**NEXT.md**](NEXT.md) — Prioritised backlog

### Data & quality
- [**docs/NOMENCLATURE.md**](docs/NOMENCLATURE.md) — Normalisation, `wine_key` composite hash, canonical enums
- [**docs/DATA_SOURCES.md**](docs/DATA_SOURCES.md) — Source tiers A–F, robots.txt compliance, token economy
- [**docs/NAMING-CLEANUP.md**](docs/NAMING-CLEANUP.md) — Post-batch cleanup pipeline

### Wine knowledge base
- [**docs/FR-REGIONS.md**](docs/FR-REGIONS.md) — 15 official French wine regions + sub-regions
- [**docs/FR-IGP-REFERENCE.md**](docs/FR-IGP-REFERENCE.md) — 75 IGP / Vin de Pays
- [**docs/VIN-DE-FRANCE.md**](docs/VIN-DE-FRANCE.md) — Vin de France designation model
- [**docs/BORDEAUX-VALIDATION.md**](docs/BORDEAUX-VALIDATION.md) — Official Bordeaux structure + DB validation rules

### Infrastructure
- [**docs/INSTALL_HAOS.md**](docs/INSTALL_HAOS.md) — Step-by-step install on Raspberry Pi 5 + HAOS
- [**docs/BACKUP.md**](docs/BACKUP.md) — SQLite online-backup → GPG AES-256 → NAS, 7d + 4w retention
- [**docs/AUTH.md**](docs/AUTH.md) — Scraper authentication (env vars, test_login, ADR-010)
- [**docs/EMAIL.md**](docs/EMAIL.md) — Newsletter ingestion via IMAP (HTML parser, .eml replay, ADR-011)

---

## Design

**Athena** — dark luxe sommellerie:

| Token | Value | Role |
|-------|-------|------|
| bg | `#0F0E17` | Background (noir profond) |
| primary | `#A53860` | Interactive (buttons, active state) |
| surface | `#F7F4EA` | Foreground text (crème) |
| accent | `#E5B25D` | Decorative / data (or champagne) |
| font-serif | Fraunces italic variable | Headings (via next/font) |
| font-sans | Inter 400/500/700 | Body (via next/font) |

Map: CartoDB dark tiles + magenta CircleMarker producers + champagne appellation pins.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16.2.6 · TypeScript strict · Tailwind v4 · next-intl 4 · React 19 |
| UI components | Radix UI · React-Leaflet · Recharts · Lucide icons |
| Backend | Next.js API routes · Drizzle ORM 0.45 · better-sqlite3 12.10 (WAL) |
| Scraping | Python 3.12 · httpx · selectolax · APScheduler · rapidfuzz · pydantic · rich · click |
| Testing | Vitest (TS) · pytest (Python) |
| Deployment | Docker Compose · nginx · Home Assistant add-on · GPG backup |

---

## Roadmap

### Sprints 1–3 (foundations) ✅
- Scaffold Next.js 16 + Drizzle schema (17 tables) + i18n 6 languages + Athena theme
- Import producer registry (~8 700 domaines from burgundy-manager)
- Dashboard · Domaines/[id] · Cellar · Best Value · Vintages · Map · Menu
- First Millesima scraper end-to-end + DLQ + job queue UI

### Sprints 4–9 (UI core + ingestion) ✅
- Best Value scoring `(rating²)/log(price)` + scatter
- Vintage heatmap region × year + drill-down
- Cellar drag-and-drop + CSV import/export + ConfidenceBadge
- Menu pairing: multi-course composer + keyword-based scoring
- Email newsletter ingestion via IMAP + .eml replay (ADR-011)
- Scraper auth system: env-vars + test_login UI (ADR-010)
- Dockerfiles multi-stage + docker-compose + nginx (ADR-007/008)
- Backup SQLite GPG-AES256 → NAS + restore (ADR-009)
- Home Assistant add-on config + automations

### Sprints 10–13 (robustness + coverage) ✅
- 37 scrapers active (FR/BE retail, press, vintage charts, crowd, official)
- wine_key deterministic cross-source identity fix
- Promoter batch: staging → fact_price via tri-source ±15%
- Staging dedup UNIQUE index + purge 56 460 duplicates
- WineEnthusiast 129 971 reviews (Kaggle, critic_code=WE)
- APScheduler cron per source, parallel ThreadPoolExecutor
- Retry + backoff for transient site errors
- Session caching in `ops_auth_sessions` (ADR-010 extension)

### Sprint 14 (France coverage 60% strict) ✅
- INAO appellation registry (315-entry taxonomy → 915 dim_appellation rows) — [#30](https://github.com/FibSol/AchillesWines/issues/30)
- Producer registry expansion: CIVB + BIVB + Inter-Rhône + InterLoire + CIVC + CIVA + CIVL → 33 492 producers — [#31](https://github.com/FibSol/AchillesWines/issues/31)
- `coverage_tier` column (notable/mid/long_tail) + `/admin/coverage` KPI dashboard — [#32](https://github.com/FibSol/AchillesWines/issues/32) [#36](https://github.com/FibSol/AchillesWines/issues/36)
- Promoter gate ≥2 critic sources for `fact_rating` — [#33](https://github.com/FibSol/AchillesWines/issues/33)
- Wine-Searcher Pro API scraper (EUR prices, notable tier first) — [#34](https://github.com/FibSol/AchillesWines/issues/34)
- iDealwine historical auction scraper (pre-2010 vintages) — [#35](https://github.com/FibSol/AchillesWines/issues/35)
- Vivino tiebreaker scraper (gated: staging only, ≥2 pro critics required) — [#37](https://github.com/FibSol/AchillesWines/issues/37)
- Mono-source fact_price purge audit (1 778 rows — all clean, 0 mono-source) — [#38](https://github.com/FibSol/AchillesWines/issues/38)
- Dev → RPi production migration script — [#29](https://github.com/FibSol/AchillesWines/issues/29)
- LLM fallback email parser (Claude Haiku, per-source opt-in) — [#21](https://github.com/FibSol/AchillesWines/issues/21)

### Backlog (P3)
- OCR wine label via Claude Vision (photo → add to cellar) — [#24](https://github.com/FibSol/AchillesWines/issues/24)
- PWA push notifications for promos — [#25](https://github.com/FibSol/AchillesWines/issues/25)
- Vector similarity recommendations — [#26](https://github.com/FibSol/AchillesWines/issues/26)
- Vintage divergence heatmap (sources × year) — [#27](https://github.com/FibSol/AchillesWines/issues/27)
- X-Wines + soMLier crowd reviews import — [#28](https://github.com/FibSol/AchillesWines/issues/28)
- Wine-Searcher vintage-chart enrichment (`fact_vintage_rating`) — [#40](https://github.com/FibSol/AchillesWines/issues/40)
- Manual review: naming pollution CSV (~6 400 rows) — [#41](https://github.com/FibSol/AchillesWines/issues/41)
- Populate `bridge_wine_variety` via appellation-default rules — [#42](https://github.com/FibSol/AchillesWines/issues/42)
- LWIN integration (deferred until Liv-ex subscription)

---

## Metrics (2026-05-27)

| KPI | Value |
|-----|-------|
| Producers (dim_producer) | 33 492 |
| Appellations (dim_appellation) | 915 AOC/IGP |
| Wines (dim_wine) | ~3 650 canonical cuvées |
| Validated prices (fact_price) | 3 140 rows (multi-source ≥2) |
| Critic ratings (fact_rating) | ~130 500 rows (WE + RVF + Hachette + CT + Vivino + more) |
| Vintage ratings (fact_vintage_rating) | 1 059 rows |
| Active scrapers | 37 |
| Python tests | 209 / 209 ✅ |
| Vitest tests | 72 / 72 ✅ |
| Languages | 6 (FR / EN / NL / DE / ES / IT) |
| Cellar capacity | 36 locations × 120 bottles = 4 320 max |

---

## Ownership

Personal / local use only. Successor to `C:\Users\Nicolas\Bourgogne\burgundy-manager` (now legacy).  
Repository: [FibSol/AchillesWines](https://github.com/FibSol/AchillesWines)
