# Architecture — Achilles's Wines

## Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Raspberry Pi 5 (8 GB RAM) · Home Assistant OS · Docker Compose addon     │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─── container: web ──────┐    ┌─── container: scraper ────────────┐    │
│  │                         │    │                                   │    │
│  │  Next.js 15 standalone  │    │  Python 3.12 + APScheduler        │    │
│  │  · App Router           │    │  · httpx + selectolax (fast)      │    │
│  │  · tRPC + Zod           │    │  · Playwright (DOM fallback)      │    │
│  │  · next-intl (6 langues)│    │  · ETag/Last-Modified cache       │    │
│  │  · Drizzle ORM          │    │  · Content-hash diff              │    │
│  │  · shadcn/ui + Tailwind │    │  · DLQ writer                     │    │
│  │  · React-Leaflet        │    │  · cron : mensuel + hebdo promo   │    │
│  │  · Recharts             │    │                                   │    │
│  │  · next-pwa             │    └──────────────┬────────────────────┘    │
│  └──────────────┬──────────┘                   │                         │
│                 │                              │                         │
│                 └──────┬───────────────────────┘                         │
│                        ▼                                                 │
│         ┌──────────────────────────────────────┐                         │
│         │  SHARED VOLUMES                      │                         │
│         │  · /data/achilles.db (SQLite WAL)    │                         │
│         │  · /data/raw/        (HTML snapshots │                         │
│         │                       gzipped)       │                         │
│         │  · /data/dlq/        (JSONL rejects) │                         │
│         │  · /data/backups/    (daily zips)    │                         │
│         └──────────────────────────────────────┘                         │
│                                                                          │
│  ┌─── container: nginx ─────────────────────────────────────────────┐    │
│  │  Reverse proxy → web · TLS via HAOS · cache /static · gzip       │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
            phones / laptops              NAS local (NFS backup)
            (PWA installable)             (zip quotidien)
```

## Pourquoi ce split web/scraper

Le scraping a un cycle de vie différent du serving :
- **Serving** = always-on, latence < 100 ms, sensible aux crashes (refus de service).
- **Scraping** = batch mensuel/hebdo, CPU-bound, Playwright peut planter, peut être désactivé sans impacter l'UX.

Mettre Playwright dans le process Next.js mélange ces deux profils. Container séparé = isolation crash + possibilité d'éteindre le scraper si CPU saturé.

## Stack frontend

- **Next.js 15** App Router, mode `output: 'standalone'` pour Docker minimal
- **TypeScript** strict
- **Tailwind v4** + tokens custom (palette Dionysus)
- **shadcn/ui** components, customisés avec le thème
- **next-intl** pour FR/EN/NL/DE/ES/IT, routing `/[locale]/...`
- **TanStack Query** pour le cache client
- **React-Leaflet** + tiles dark (Carto Dark Matter ou Stadia AlidadeSmoothDark)
- **Recharts** avec palette corail/mint sur grille discrète
- **next-pwa** pour installabilité + offline cellar browsing
- **tRPC** + Zod pour le typage end-to-end client ↔ serveur

## Stack backend

- **Next.js API routes** (App Router `route.ts`) pour le CRUD UI
- **Drizzle ORM** + `better-sqlite3` driver (changeable pour libSQL/Turso plus tard)
- **SQLite WAL** avec `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-64000;`
- **Zod** sur tous les bords (API in/out, scraper output → DB in)

## Stack scraping (sidecar Python)

- **Python 3.12** + `uv` ou `pip` + venv
- **httpx** (HTTP/2, async) pour les sources statiques
- **selectolax** (lexbor parser, 10× plus rapide que BeautifulSoup) pour le HTML
- **Playwright** + `chromium-headless-shell` pour les sites JS-rendered (fallback uniquement)
- **APScheduler** pour les jobs cron interne (mensuel/hebdo)
- **tenacity** pour les retry avec backoff exponentiel
- **rapidfuzz** pour le fuzzy matching identité
- **pydantic v2** pour la validation des outputs
- **rich** pour les logs développeur lisibles

## Flux ETL (par source)

```
                ┌─────────────────────────────────────────────────┐
                │ 1. extract                                      │
                │    ├ check ETag/Last-Modified → 304 = skip      │
                │    ├ fetch HTML → compute content-hash          │
                │    └ if hash unchanged → skip parsing           │
                ├─────────────────────────────────────────────────┤
                │ 2. land raw                                     │
                │    └ /data/raw/{source}/dt={date}/{hash}.html.gz│
                ├─────────────────────────────────────────────────┤
                │ 3. parse (CSS selectors versionnés)             │
                │    ├ if parser fails → DLQ (parse_error)        │
                │    └ output : list[ScrapedRecord]               │
                ├─────────────────────────────────────────────────┤
                │ 4. normalize                                    │
                │    ├ producer_norm, cuvee_norm                  │
                │    ├ vintage parse, bottle_ml normalize         │
                │    └ currency → EUR                             │
                ├─────────────────────────────────────────────────┤
                │ 5. validate (Cassandra's gates)                 │
                │    ├ region_gate : appellation ∈ allowed?       │
                │    ├ critic_enum : code ∈ canonical?            │
                │    └ if fail → DLQ (validation_error)           │
                ├─────────────────────────────────────────────────┤
                │ 6. match identity                               │
                │    ├ compute wine_key (sha1 composite)          │
                │    ├ if wine_key exists → link                  │
                │    ├ else fuzzy match against dim_wine          │
                │    │  ├ score ≥ 0.85 → auto-link                │
                │    │  ├ 0.70-0.85 → review queue                │
                │    │  └ < 0.70 → create new wine_key            │
                ├─────────────────────────────────────────────────┤
                │ 7. apply tri-source rule (prix only)            │
                │    ├ if ≥ 2 sources concordent ±15%             │
                │    │  → INSERT INTO fact_price                  │
                │    ├ else                                       │
                │    │  → INSERT INTO staging.price_candidates    │
                │    │     with needs_review = true               │
                ├─────────────────────────────────────────────────┤
                │ 8. commit batch                                 │
                │    └ ops_batch_log row with stats               │
                └─────────────────────────────────────────────────┘
```

## Sécurité & vie privée

- **Aucune authentification externe** au démarrage (usage personnel sur LAN HA).
- **Phase 2** : passphrase via env var ou NextAuth + Resend magic link (si exposé Internet).
- **Pas de PII** dans le scraping : pas de scraping de reviewers user (CellarTracker), seulement scores numériques publics.
- **Robots.txt** respecté par tous les scrapers. Crawl-delay honoré. User-Agent identifié.
- **Backup** : zip quotidien chiffré GPG vers NAS.

## Performance attendue (RPi 5 cibles)

- DB SQLite : ≤ 500 MB après 1 an d'ingestion mensuelle
- Cold start Next.js : ≤ 8 s
- Latence API typique : 50-150 ms (lecture indexée)
- Scraping mensuel total : ≤ 2 h sur 10 sources, ≤ 100 MB de HTML downloadé (grâce au content-hash diff)
- Mémoire : ≤ 1 GB pour web, ≤ 2 GB pour scraper (pic Playwright)
