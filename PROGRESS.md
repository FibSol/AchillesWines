# Achilles's Wines — Progress Log

## 2026-05-22 — Sprint 4 (UI core)

### Odysseus (Frontend)
- [S4-Map] Page Map: React-Leaflet + CartoDB dark tiles + 8345 coral CircleMarker producers + 206 mint appellation centroid pins + GeoJSON polygon overlays (styled coral) + absolute-positioned legend, empty-state, i18n 6 languages (noData/legendProducers/legendAppellations/legendRegions). `ssr: false` placed in WineMapLoader client wrapper to satisfy Next.js 16 app-router constraint · files: components/WineMap.tsx, components/WineMapLoader.tsx, app/[locale]/map/page.tsx, messages/{fr,en,nl,de,es,it}.json
- [S4-Domaine] Page Domaine/[id]: server-rendered detail with producer header (region/subregion/country, website, aliases, allowed_appellations badges), cuvées table (color dot · cuvée · appellation · best rating /100 · price range · source-count badge sized verified/reviewed/needs-review), Recharts LineChart price-over-time (one series per source_code, time-scaled X axis, custom tooltip) and Recharts BarChart ratings-by-critic (avg score per critic_code, dynamic per-bar coral/mint palette). DrinkingWindowBand conditional render — code wired to read drink_from/drink_to from fact_rating rows if/when added (current schema omits the cols, band stays hidden). List cards on /domaines now link to /domaines/[id]. i18n: domaine.* (15 keys × 6 langs). npx tsc --noEmit clean. · files: app/[locale]/domaines/[id]/page.tsx, app/[locale]/domaines/page.tsx, components/ProducerCharts.tsx, messages/{fr,en,nl,de,es,it}.json
- [S4-Cellar] Cellar drag-and-drop board: native HTML5 DnD between 36 locations with drop-target ring highlight, capacity-fill gradient on each cell, click-to-open modal with consume/move tabs (Radix Dialog), add-bottle modal with debounced wine search (POST /api/cellar/wines?q=…), per-cell + button (disabled when full). Server-side capacity enforcement, auto-merge of duplicate (wine,location) rows on move, qty=0 deletes inventory row, consume writes to cellar_consumption with personal_score/occasion/tasting_note. API: POST/PATCH/DELETE /api/cellar/inventory[/:id], POST /api/cellar/consume, GET /api/cellar/wines. router.refresh() after each mutation for fresh server data. i18n: cellar.* (15 new keys × 6 langs). npx tsc --noEmit clean. · files: components/CellarBoard.tsx, app/[locale]/cellar/page.tsx, app/api/cellar/inventory/route.ts, app/api/cellar/inventory/[id]/route.ts, app/api/cellar/consume/route.ts, app/api/cellar/wines/route.ts, messages/{fr,en,nl,de,es,it}.json
- [S4-CellarCsv] Cellar CSV import/export + template: csvStringify/csvParse helpers in lib/csv.ts (RFC 4180-ish, handles quoted fields/escaped quotes/CRLF). Export GET /api/cellar/export → text/csv with header (wine_key · producer · cuvée · vintage · appellation · color · location_id · qty · price · source · notes · purchase_date). Template GET /api/cellar/template with one example row. Import POST /api/cellar/import accepts text/csv or multipart/form-data, resolves wine via wine_key OR producerNorm+cuveeNorm+vintage+appellationNorm (lib/identity helpers), enforces location capacity using running per-location usage map, upserts (wine_key, location_id), returns {accepted, inserted, merged, rejected, rejections[]} with row-level reasons. CellarCsvActions client: Import button opens Radix Dialog with file picker, posts CSV text, displays result cards (inserted/merged/rejected) + collapsible rejections list with row#+reason; Export/Template are direct <a download> links. i18n: cellar.csv.* (12 keys × 6 langs). npx tsc --noEmit clean. · files: lib/csv.ts, app/api/cellar/export/route.ts, app/api/cellar/template/route.ts, app/api/cellar/import/route.ts, components/CellarCsvActions.tsx, app/[locale]/cellar/page.tsx, messages/{fr,en,nl,de,es,it}.json
- [S3-Logs] Logs streaming drawer on /admin/jobs: clickable running/done/failed rows open a right-side Radix Dialog drawer showing last 100 lines tailed from logs/<batch_id>.log via GET /api/jobs/[jobId]/logs?lines=100. API path-traversal-safe (resolved+containment check), reads file, ENOENT → empty list with friendly message, supports custom line counts up to 1000. Drawer auto-refreshes every 3s when job.status='running' (toggle), color-codes error/warn/success keywords (coral/warning/mint), auto-scrolls to bottom, shows source_code + jobId-suffix + batch + status in header. JobsTable rows became clickable cursor-pointer for inspectable statuses; Cancel button + DLQ link stop event propagation to avoid opening the drawer. NB: Python scrapers don't yet write per-batch log files — follow-up task added to NEXT.md for Patroclus. npx tsc --noEmit clean. · files: app/api/jobs/[jobId]/logs/route.ts, components/JobLogsDrawer.tsx, components/jobs-table.tsx
- [S5-Confidence] Shared ConfidenceBadge component (verified/reviewed/needs_review) with lucide icons (ShieldCheck/Eye/AlertCircle), sm/md sizes, optional iconOnly mode, derived from distinct source_key count across fact_price + fact_rating. Applied to: /best-value list (replaces inline ConfidenceBadge), /domaines/[id] cuvées table source-count column, /vintages drill-down wine list (per-row icon-only badge). API /api/vintages/wines now returns sourceCount via distinct source_key aggregation. Labels pass next-intl t.raw() so `{count}` placeholder reaches the client component where it gets interpolated per-row. deriveConfidence() helper (≥3 verified, ≥1 reviewed, 0 needs_review) exported alongside Confidence + ConfidenceLabels types. npx tsc --noEmit clean. · files: components/ConfidenceBadge.tsx, components/VintageHeatmap.tsx, app/[locale]/best-value/page.tsx, app/[locale]/domaines/[id]/page.tsx, app/[locale]/vintages/page.tsx, app/api/vintages/wines/route.ts
- [S6-Menu] Page Menu (compose menu + wine pairing v1): MenuComposer client component lets users build a menu by adding courses (aperitif/entree/plat/fromage/dessert/other) with free-text dish descriptions + guests + optional total budget; "Propose pairings" POSTs to new /api/pairing/propose. Pairing engine in lib/pairing.ts is a transparent keyword-driven matcher — COURSE_COLOR_DEFAULTS gives each course type a base color score, DISH_KEYWORD_BOOSTS lists FR/EN dish-keyword regexes (boeuf/agneau/canard→red; saumon/poisson→white; chocolat→fortified; roquefort→sweet/fortified; etc.). scorePairing() returns full breakdown (colorMatch + inventoryBonus log-scaled + ratingScore + budgetPenalty), reused on both sides. API loads cellar inventory first (preferCellar=true), tops up from dim_wine if < 12 wines, joins fact_price + fact_rating for avg + distinct source counts, runs scorePairing per (course × candidate), returns top 5 picks per course with rationale[] strings. UI cards show producer/cuvée/vintage, color dot, score, inventory chip (mint "from cellar ×N" if owned, subtle "registry" otherwise), rating, price, ConfidenceBadge icon, and chevron rationale list. i18n: menu.* (15 new keys + courseTypes nested × 6 langs). npx tsc --noEmit clean. · files: lib/pairing.ts, app/api/pairing/propose/route.ts, components/MenuComposer.tsx, app/[locale]/menu/page.tsx, messages/{fr,en,nl,de,es,it}.json
- [S6-PairingTests] Tests vitest sur lib/pairing.ts (28 tests, 6 describes): course color defaults (apéritif↔sparkling, dessert↔sweet, plat↔red), dish-keyword boosts (boeuf/canard/saumon/chocolat/roquefort/steak/végétarien, additive stacking, case + accent), inventory bonus (zero/positive/monotonic/saturation at 30), rating score (null/clamp-at-70/linear-from-70), budget penalty (null/within/over/saturation at -40), total composition (sum identity + perfect-match >140 + mismatch =0). Tests caught 2 real regex bugs in lib/pairing.ts: `b(o|œ)uf` didn't match "boeuf" without ligature (fixed to `b(oe|œ|o)uf`), and `\btruffe\b`/`\bchampignon\b`/etc. didn't match plural forms (added `s?` to truffes/champignons/cèpes/morilles/girolles + fish/shellfish/meat plurals). Full suite (identity + gates + promoter + pairing): 66/66 passing. · files: tests/pairing.test.ts, lib/pairing.ts
- [GitHub] Project hosted at FibSol/AchillesWines. 108-file initial commit + merge of GitHub's auto LICENSE pushed to main. CI workflow (.github/workflows/ci.yml) runs `tsc --noEmit` + `vitest run` on push/PR — first run green (2m3s). PR template, CONTRIBUTING.md (role-based workflow). 12 labels created (role:* / priority:* / sprint-*). 10 GitHub issues opened from unchecked NEXT.md backlog (#1-5 Patroclus scrapers, #6-10 Hector deployment). · files: .github/workflows/ci.yml, .github/pull_request_template.md, CONTRIBUTING.md, .gitignore (added logs/, *.log, .claude/session-complete, .claude/settings.local.json)
- [S3-LogWriter] Per-batch log writer for scraper runner (closes #1). JobRunner now: generates batch_id at job-claim time (`<source_code>-YYYYMMDD-HHMMSS-<uuid8>`), pins it on ops_job_queue immediately so JobLogsDrawer can tail logs/<batch_id>.log from the start, opens the log file line-buffered (so the 3 s drawer poll picks up fresh lines), tees stdout + stderr + rich.Console.file to both terminal and file via _TeeWriter, restores streams + closes file in a finally block. Scraper accepts injected `self.batch_id` (set by runner before .run()), falls back to its own format if absent (preserves CLI standalone behavior). Smoke-tested import + ID format; TS clean; 66/66 vitest still green. · files: scraper/achilles_scraper/job_runner.py, scraper/achilles_scraper/scrapers/millesima.py
- [S7-Dockerfile] Multi-stage Dockerfiles for web + scraper containers (closes #6, ADR-007). Web `Dockerfile`: 3 stages on node:20-bookworm-slim — `deps` installs python3/make/g++ for better-sqlite3 native build, `builder` runs `next build` (next.config.ts already had output:"standalone"), `runner` copies only `.next/standalone` + static + public + db + drizzle.config.ts; tini in PID 1, non-root user achilles:1001, HEALTHCHECK via Node's native fetch on `/`. Scraper `scraper/Dockerfile`: 2 stages on python:3.12-slim-bookworm — `builder` produces wheels via `pip wheel`, `runner` installs from wheels (no toolchain in final image), HEALTHCHECK via `sqlite3 SELECT 1` on shared /data/achilles.db. Both arm64-compatible (RPi 5 target). `.dockerignore` at root and in scraper/ to keep build context lean. CI extended: new `docker-lint` job (hadolint, ignores DL3008/DL3013), new `docker-build` job (Buildx + GHA cache, builds both images on every push). ADR-007 documents the standalone+wheel-cache choices and rejected alternatives (single multi-process, Alpine base, distroless). TS clean. · files: Dockerfile, .dockerignore, scraper/Dockerfile, scraper/.dockerignore, .github/workflows/ci.yml, DECISIONS.md
- [S7-Backup] Encrypted backup script SQLite → GPG → NAS (closes #9, ADR-009). `scripts/backup.sh` snapshots via SQLite online-backup API (`sqlite3 ".backup"` — WAL-safe with concurrent writers), encrypts with GPG symmetric AES-256 reading passphrase from `ACHILLES_GPG_PASSPHRASE` via `--passphrase-fd 0` (never in argv/log), round-trip verifies the encrypted file decrypts before trusting it, retains 7 daily + 4 weekly (Sunday backups suffixed `-weekly` for predictable suffix-based pruning). Cron-friendly: every step `tee`d to logs/backup-YYYYMMDD.log, exits non-zero on any failure. Companion `scripts/restore.sh` decrypts → `PRAGMA integrity_check` → atomic mv, refuses overwrite without `--force`. `docs/BACKUP.md` documents env vars, cron + HA scheduling examples, filename convention. CI: new `shell-lint` job runs `bash -n` on all scripts/*.sh + shellcheck severity=warning. ADR-009 documents online-backup + GPG-symmetric + round-trip-verify + suffix-based-retention choices and rejected alternatives (raw cp under WAL, SQL dump, asymmetric GPG, Litestream). · files: scripts/backup.sh, scripts/restore.sh, docs/BACKUP.md, .github/workflows/ci.yml, DECISIONS.md
- [S7-Compose] docker-compose.yml orchestration (closes #7, ADR-008). 3 services on a bridge network `achilles`: `web` (built from ./Dockerfile), `scraper` (built from ./scraper/Dockerfile), `nginx:1.27-alpine` reverse proxy. 3 named volumes: `achilles-data` mounted at /data on both web+scraper for shared SQLite (WAL-safe), `achilles-logs` for nginx access/error + scraper per-batch logs, `achilles-raw` for HTML snapshots. Only nginx exposes a host port (ACHILLES_HTTP_PORT=8080 by default; web/scraper internal-only). scraper + nginx depend on web's healthcheck via `depends_on: condition: service_healthy`. Json-file logging with 10m × 3 rotation per service. New `nginx/nginx.conf`: upstream achilles_web:3000, gzip for HTML/JSON/SVG (Next already pre-compresses JS/CSS), 1-year immutable cache for /_next/static/, /health endpoint for compose healthcheck, 8m body limit for CSV imports, X-Forwarded-* headers propagated. `.env.example` updated with ACHILLES_HTTP_PORT. CI extended with `compose-validate` job (`docker compose config --quiet`). ADR-008 documents bridge network + named volume + nginx-only ingress choices and rejected alternatives (host network, Traefik, bind mounts). · files: docker-compose.yml, nginx/nginx.conf, .env.example, .github/workflows/ci.yml, DECISIONS.md

## 2026-05-21 — Sprint 2 & 3 (data foundations + scraper supervision) ✓

### Hector (Solution Architect)
- [S2-1] Python sidecar scaffolded: pyproject.toml (httpx/selectolax/playwright/apscheduler/rapidfuzz/pydantic/rich/click), config.py, db.py, identity.py (mirrors lib/identity.ts exactly), dlq.py, scrapers/__init__.py, scrapers/base.py · files: scraper/pyproject.toml, scraper/achilles_scraper/__init__.py, scraper/achilles_scraper/config.py, scraper/achilles_scraper/db.py, scraper/achilles_scraper/identity.py, scraper/achilles_scraper/dlq.py, scraper/achilles_scraper/scrapers/__init__.py, scraper/achilles_scraper/scrapers/base.py
- [S3-5] ops_job_queue table added to Drizzle schema + migration SQL (job_id PK, source_key FK, status enum queued/running/done/failed/cancelled, timestamps, row counts, error_message, batch_id, params JSON) · files: db/schema.ts, db/migrations/0001_ops_job_queue.sql, db/migrations/meta/_journal.json

### Patroclus (Backend)
- [S2-2/3/4] Import script burgundy-manager → dim_producer + dim_appellation: ~8 700 domaines with allowedAppellations reconstructed from cuvées, appellations with centroid coords and level mapping · files: scripts/import-from-burgundy-manager.ts
- [S3-1] Millesima scraper: pagination, card parser (_parse_cards), price EUR parser, ETag/content-hash via ops_content_hashes, producer upsert as pending_review on miss, staging_price_candidates insert, DLQ on parse_error/auth_error, graceful 403/429 handling, SAMPLE_HTML constant, 1s polite delay · files: scraper/achilles_scraper/scrapers/millesima.py
- [S3-2] CLI `achilles-scraper run --source millesima --limit N` + `run-jobs` command with rich table output · files: scraper/achilles_scraper/cli.py
- [S3-3] Batch promoter: staging_price_candidates → fact_price via tri-source rule ±15% median concordance · files: scraper/achilles_scraper/promoter.py
- [S3-9] Job runner Python: atomic claim (UPDATE status='running' WHERE status='queued'), dispatch to scraper, finish with status done/failed · files: scraper/achilles_scraper/job_runner.py
- [S3-6] API routes: POST /api/jobs (Zod validation, insert queued job, return jobId), GET /api/jobs (status+sourceKey filters, limit 200), POST /api/jobs/[jobId]/cancel (UPDATE queued→cancelled) · files: app/api/jobs/route.ts, app/api/jobs/[jobId]/cancel/route.ts

### Odysseus (Frontend)
- [S3-7/8/10/11] AdminJobs UI: JobsTable client component (auto-refresh 5s, launch panel with source select + limit input, status badges with pulse animation, duration, DLQ links to /qualite?batch_id=, ✋ cancel button on queued jobs, 5-row skeleton loading) · files: components/jobs-table.tsx
- [S3-7] Admin jobs page /admin/jobs with PageShell · files: app/[locale]/admin/jobs/page.tsx
- SiteNav updated: Settings2 icon added, /admin/jobs link in ADMIN_ITEMS · files: components/site-nav.tsx
- /qualite page updated: "🚀 Lancer un scraper" link button added at top · files: app/[locale]/qualite/page.tsx
- 6 messages files updated: adminJobs section (title/subtitle/launch/table columns) + nav.adminJobs key (FR/EN/NL/DE/ES/IT) · files: messages/{fr,en,nl,de,es,it}.json

### Cassandra (Data Steward)
- [S2-5] Unit tests identity.ts: normText (null/undefined/diacritics/punctuation/case), expandProducerPrefix (d/dom/ch prefixes), cleanCuveeTails (grand cru/1er cru/year/bottle sizes), computeWineKey (determinism/16-char hex/NV vs year/vintage diff), isAppellationAllowed, normalizeScoreTo100 (/100//20//5/stars) · files: tests/identity.test.ts
- [S2-6] Unit tests gates.ts: regionGate (pass/fail+error class), criticEnumGate (all 11 canonical codes + unknown), applyTriSourceRule (single→pending, 2 within 15%→promoted, 2 >15%→pending, 3 with outlier), normalizeRatingScore (pass/NaN/out-of-range//20 normalization) · files: tests/gates.test.ts
- [S3-4] Integration tests tri-source rule: concordant 2 sources, divergent >15%, mixed wines · files: tests/integration/promoter.test.ts
- Vitest config with @/ alias · files: vitest.config.ts

> Append-only log. Most recent day at top. One line per completed deliverable.
> Format: `- [HH:MM] [role] <description> · files: <comma-separated>`

## 2026-05-21 — Sprint 1 (foundations) ✓

### Helena (Business Analyst)
- Recueil exigences initiales : multilingue FR/EN/NL/DE/ES/IT, cellar 36×120, dashboard, best-value, vintage matrix, map, domaines, menu pairing · files: README.md
- User stories validées par 4 décisions structurantes via AskUserQuestion : fork burgundy-manager, design Dionysus, strict multi-source, Docker Compose RPi · files: DECISIONS.md
- Backlog priorisé en 5 sprints (P0 → P3) avec estimations effort · files: NEXT.md

### Hector (Solution Architect)
- ADR-001 à ADR-005 rédigés (fork, design, data strategy, deployment, wine_key) · files: DECISIONS.md
- Architecture documentée : containers web + scraper + nginx sur RPi 5 · files: docs/ARCHITECTURE.md
- Stack figé : Next.js 16.2.6 + React 19.2 + Drizzle 0.45 + better-sqlite3 12.10 + Tailwind v4 + next-intl 4 · files: package.json
- Scaffold projet : tsconfig, next.config, drizzle.config, postcss, .gitignore, .env.example · files: tsconfig.json, next.config.ts, drizzle.config.ts, postcss.config.mjs, .gitignore, .env.example
- Schéma Drizzle complet (16 tables) : dim_source/producer/appellation/variety/wine, bridge_wine_variety, fact_price/rating/vintage_rating, cellar_locations/inventory/consumption, ops_dead_letter/content_hashes/batch_log, staging_price_candidates · files: db/schema.ts, db/migrations/0000_woozy_fantastic_four.sql
- Migration appliquée à `data/achilles.db`, seed initial (13 sources + 36 emplacements + 7 appellations + 3 producteurs + 1 vin démo Coche-Dury Meursault Perrières 2020) · files: db/migrate.ts, db/seed.ts, db/index.ts

### Cassandra (Data Steward)
- 6 gates anti-hallucination spécifiés : producer registry pré-validé, hard region gate, tri-source rule ±15%, critic enum fermé, content-hash diff, DLQ visible · files: docs/ARCHITECTURE.md
- Helpers identity.ts : normText, expandProducerPrefix, cleanCuveeTails, computeWineKey (sha1[:16]), normalizeScoreTo100, isAppellationAllowed · files: lib/identity.ts
- Gates implémentées : regionGate, criticEnumGate, applyTriSourceRule, normalizeRatingScore · files: lib/quality/gates.ts
- Enum canonique des critiques figé : WA, Vinous, BH, JMIB, RVF, Decanter, JS, JG, WS, Hachette, CT · files: lib/quality/gates.ts, db/schema.ts
- Nomenclature canonique documentée (wine_key composite, allowed_appellations JSON) · files: docs/NOMENCLATURE.md

### Patroclus (Backend)
- Sources de données catalogées en tiers A/B/C/D/E/F avec cadences et politique tokens · files: docs/DATA_SOURCES.md

### Odysseus (Frontend)
- Thème Dionysus appliqué : palette aubergine/coral/mint/ivoire, fonts Migra+Geist, glass-card, gradient-border, stat-card, badge-verified/reviewed/needs-review · files: app/globals.css
- next-intl configuré pour FR/EN/NL/DE/ES/IT avec routing as-needed · files: i18n/routing.ts, i18n/request.ts, i18n/navigation.ts, middleware.ts
- 6 fichiers messages traduits intégralement (~50 clés × 6 langues = 300 traductions) · files: messages/{fr,en,nl,de,es,it}.json
- Layout racine + locale layout avec html/body html/lang dynamique · files: app/layout.tsx, app/[locale]/layout.tsx
- SiteNav : navigation desktop + mobile scrollable, lucide icons, état actif visible · files: components/site-nav.tsx
- LanguageSwitcher : <select> stylisé avec icône Globe · files: components/language-switcher.tsx
- Dashboard page : hero gradient, 6 stat cards live (bottles, unique wines, value EUR, producers, ratings, DLQ open), 4 quick access cards, status pipeline · files: app/[locale]/page.tsx
- PageShell + ComingSoon réutilisables · files: components/page-shell.tsx
- 8 pages stubs avec data réelle ou placeholder : best-value, vintages, map, domaines, cellar (36 emplacements live), menu, qualite (stats DLQ live), quarantaine (review queue) · files: app/[locale]/{best-value,vintages,map,domaines,cellar,menu,qualite,quarantaine}/page.tsx
- Utils : cn helper, formatCurrency, formatNumber, formatDate · files: lib/utils.ts

### Validation
- 11 routes testées HTTP 200 : `/`, `/domaines`, `/cellar`, `/best-value`, `/vintages`, `/map`, `/menu`, `/qualite`, `/quarantaine`, `/en`, `/nl/cellar`
- Locales vérifiées : FR (default, `lang="fr"`), EN (`lang="en"`, "no compromise"), NL (`lang="nl"`, "zonder compromis"), tagline NL trouvée à l'octet
- Palette Dionysus présente dans le CSS chunk
- Dev server tourne sur `http://localhost:3001` (Next.js 16.2.6 Turbopack)

### Skill achilles-progress
- Créé à `C:\Users\Nicolas\.claude\skills\achilles-progress\` · files: SKILL.md, reference/templates.md
- Sous-commandes : status (défaut), done, next, decided, block, unblock

## 2026-05-22

### Odysseus (Frontend)
- [Odysseus] Sprint 4 item 1: Best Value page built (ranked list + ScatterPlot, i18n 6 langs, DB cleanup removed burgundy-manager price rows) · files: app/[locale]/best-value/page.tsx, components/BestValueScatter.tsx, messages/{en,fr,nl,de,es,it}.json
- [Odysseus] Sprint 4 item 2: Vintages heatmap built — CSS grid heatmap (region × year), coral intensity = wine count / score, Recharts BarChart in detail panel (selected region vintage distribution), click-to-fetch wine list via /api/vintages/wines, i18n 6 langs, 0 TS errors, 0 console warnings · files: components/VintageHeatmap.tsx, app/[locale]/vintages/page.tsx, app/api/vintages/wines/route.ts, messages/{en,fr,nl,de,es,it}.json

## 2026-05-22 — Sprint 2 & 3 ✓

### Hector (Solution Architect)
- [06:00] Python sidecar scaffoldé : pyproject.toml + config.py + db.py + identity.py (miroir exact de lib/identity.ts) + dlq.py + scrapers/base.py · files: scraper/pyproject.toml, scraper/achilles_scraper/__init__.py, scraper/achilles_scraper/config.py, scraper/achilles_scraper/db.py, scraper/achilles_scraper/identity.py, scraper/achilles_scraper/dlq.py, scraper/achilles_scraper/scrapers/__init__.py, scraper/achilles_scraper/scrapers/base.py
- [06:15] Table `ops_job_queue` ajoutée au schéma Drizzle (17e table, ADR-006) + migration 0001 appliquée · files: db/schema.ts, db/migrations/0001_ops_job_queue.sql

### Patroclus (Backend)
- [06:05] Script d'import burgundy-manager écrit + exécuté : 201 appellations + 8 701 producteurs importés dans dim_appellation + dim_producer, avec allowed_appellations reconstruit depuis les cuvées et coords lat/lng interpolées · files: scripts/import-from-burgundy-manager.ts
- [06:20] Scraper Millesima : paginateur httpx, parser selectolax, ETag/content-hash dedup via ops_content_hashes, DLQ sur 403/429/parse errors, SAMPLE_HTML fixture, délai 1s poli · files: scraper/achilles_scraper/scrapers/millesima.py
- [06:22] CLI rich `achilles-scraper run --source millesima --limit N` + commande `run-jobs` · files: scraper/achilles_scraper/cli.py
- [06:23] Promoteur batch Python : staging.price_candidates → fact_price via règle médiane ±15%, claim atomique · files: scraper/achilles_scraper/promoter.py
- [06:24] Job runner Python : poll toutes les 5 s, claim atomique UPDATE…WHERE status='queued', dispatch scraper, update status final · files: scraper/achilles_scraper/job_runner.py
- [06:25] API `/api/jobs` : POST (Zod v4, UUID, insert queued) + GET (filtres status/sourceKey) · files: app/api/jobs/route.ts
- [06:25] API `/api/jobs/[jobId]/cancel` : POST cancel si status=queued · files: app/api/jobs/[jobId]/cancel/route.ts

### Cassandra (Data Steward)
- [06:10] 38 tests Vitest : 23 tests identity.ts (normText/expandProducerPrefix/cleanCuveeTails/computeWineKey/isAppellationAllowed/normalizeScoreTo100) + 12 tests gates.ts (regionGate/criticEnumGate/applyTriSourceRule/normalizeRatingScore) + 3 tests intégration promoteur · files: tests/identity.test.ts, tests/gates.test.ts, tests/integration/promoter.test.ts, vitest.config.ts
- [06:18] 38/38 tests passent · commande: npx vitest run

### Odysseus (Frontend)
- [06:26] Page `/admin/jobs` : tableau live jobs + auto-refresh 5s + badges status (queued/running/done/failed/cancelled) + panel Launch scraper + bouton Cancel queued + DLQ link filtré batch_id · files: components/jobs-table.tsx, app/[locale]/admin/jobs/page.tsx
- [06:26] SiteNav mis à jour : lien /admin/jobs (Settings2 icon) dans ADMIN_ITEMS · files: components/site-nav.tsx
- [06:26] Bouton "🚀 Lancer un scraper" ajouté en haut de /qualite · files: app/[locale]/qualite/page.tsx
- [06:26] Clés adminJobs + nav.adminJobs ajoutées aux 6 fichiers messages (FR/EN/NL/DE/ES/IT) · files: messages/{fr,en,nl,de,es,it}.json

### Validation
- `npx tsc --noEmit` : 0 erreurs
- `npx vitest run` : 38/38 tests passent (3 fichiers)
- Import DB : 201 appellations + 8 701 producteurs dans achilles.db
- Python sidecar : venv créé + `pip install -e .` OK · commande: achilles-scraper run --source millesima --limit 100
