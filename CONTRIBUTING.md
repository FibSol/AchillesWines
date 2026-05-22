# Contributing — Achilles's Wines

This project is structured around five team roles (see `CLAUDE.md`):

| Role       | Responsibility                                  |
|------------|-------------------------------------------------|
| Helena     | Business Analyst — priorities, user stories     |
| Hector     | Solution Architect — schema, ADRs, infra        |
| Patroclus  | Backend — scrapers, API routes, Python sidecar  |
| Odysseus   | Frontend — Next.js pages, components, i18n      |
| Cassandra  | Data Steward — tests, gates, quality            |

Each commit / PR is attributed to one of these roles.

## Branches

- `main` is the integration branch and is protected (CI must pass).
- Feature branches: `<role>/<short-slug>`, e.g. `odysseus/cellar-csv-import`, `patroclus/scrapers-belgium`.
- Keep branches small enough to review in one sitting (< 400 LOC diff when possible).

## Definition of done (per role)

### Odysseus (frontend)
- `npx tsc --noEmit` clean.
- Any new UI key exists in all 6 `messages/*.json` files (FR/EN/NL/DE/ES/IT).
- Visual smoke test in `npm run dev` for the affected route.
- Uses `PageShell` + `glass-card` + `stat-card` from `globals.css` for new pages.

### Patroclus (backend)
- Scrapers respect `ops_content_hashes` (ETag / content hash) and write to `ops_dead_letter` on failure.
- `fact_price` rows must come from scraper sources only — never from the producer registry.
- API routes use Zod for input validation.

### Cassandra (QA)
- `npx vitest run` clean (full suite green, not just touched file).
- New gate / scoring logic gets unit tests with edge cases.

### Hector (infra)
- Each architectural change ships with an ADR in `DECISIONS.md`.

### Helena (BA)
- Backlog changes update `NEXT.md` (with priority and effort estimate).

## Workflow

1. Pick the highest-priority item from `NEXT.md` that matches your role.
2. Create a branch (`<role>/<slug>`).
3. Implement + tests.
4. Append to `PROGRESS.md` under today's date. Tick the `NEXT.md` item.
5. Open a PR using the template.
6. CI runs `npx tsc --noEmit` + `npx vitest run`. Must be green to merge.

## What never gets committed

- `data/`, `*.db`, `*.jsonl`, `dlq/`, `raw/`, `logs/`, `backups/`
- `.env*` (use `.env.example` as the source of truth for required vars)
- `.claude/session-complete`, `.claude/settings.local.json`
- Anything containing secrets, API tokens, or scraped HTML dumps

## Running locally

```powershell
npm install
npm run db:migrate
npm run db:seed
npm run dev            # Next.js at http://localhost:3000
npx vitest             # tests in watch mode
```

Python sidecar (scraping) lives in `scraper/` — see its own `pyproject.toml`.
