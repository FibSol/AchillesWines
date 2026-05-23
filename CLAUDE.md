# Achilles's Wines — Claude Code Instructions

## Project overview

Full-stack home wine cellar. Multilingual FR/EN/NL/DE/ES/IT.
Working dir: `C:\Claude\achilles-wines` (Windows 11, PowerShell).

**Stack:** Next.js 16.2.6 · React 19 · Drizzle + better-sqlite3 · Tailwind v4 · next-intl 4 · Recharts  
**Python sidecar:** `scraper/` — httpx · selectolax · apscheduler · pydantic · rich · click  
**Theme:** Athena — noir `#0F0E17`, magenta vin `#A53860`, crème `#F7F4EA`, or champagne `#E5B25D`  
**DB:** `data/achilles.db` (SQLite, never commit)

## Roles

| Handle     | Responsibility                                 |
|------------|------------------------------------------------|
| Helena     | Business Analyst — priorities, user stories    |
| Hector     | Solution Architect — schema, ADRs, infra       |
| Patroclus  | Backend — scrapers, API routes, Python sidecar |
| Odysseus   | Frontend — Next.js pages, components, i18n     |
| Cassandra  | Data Steward — tests, gates, quality           |

## Rules (all agents must follow)

- **Never invoke skills** — do NOT call the Skill tool. Do actual code work.
- **GitHub Issues are the single source of truth for all tasks.** Every item in NEXT.md must have a corresponding GitHub issue on [FibSol/AchillesWines](https://github.com/FibSol/AchillesWines/issues). When starting a task, move the issue to "In Progress". When a task is completed: close the GitHub issue (`gh issue close <number>`) and tick the item in NEXT.md. Never mark a task done in NEXT.md without closing its GitHub issue.
- TypeScript: strict, no `type: any` anywhere.
- Run `npx tsc --noEmit` before finishing any frontend task.
- Run `npx vitest run` before finishing any Cassandra task.
- Never commit `.env`, `data/`, `*.db`, `*.jsonl`.
- Use `PageShell` + `glass-card` + `stat-card` from `globals.css`.
- i18n: any new UI key must be added to all 6 `messages/*.json` files.
- Data integrity: `fact_price` rows must come from scrapers only (`source_key` = scraper name). Never import prices from burgundy-manager.
- Naming hygiene: scrapers MUST wrap raw producer / cuvée strings with `clean_producer_display()` and `clean_cuvee_display()` from `scraper/achilles_scraper/identity.py` before insert. The post-batch cleanup pipeline (`scripts/cleanup-producer-names.mjs` → `cleanup-cuvee-noise.mjs` → `cleanup-cuvee-names.mjs` → `dedupe-wines.mjs` → `merge-vin-de-france-ghosts.mjs`) is a safety net, not a substitute. See [docs/NAMING-CLEANUP.md](docs/NAMING-CLEANUP.md) for the convention and ordering.

## Auto-session launcher

After completing a sprint step, the next Claude session launches automatically.

### How it works

1. Agent finishes its task and writes `.claude/session-complete` containing its role name (e.g. `Odysseus`).
2. Claude exits → the **Stop hook** (`scripts/next-session.ps1`) fires.
3. The script reads `NEXT.md`, finds the first unchecked `[ ]` item, builds the full agent prompt, and opens a **new PowerShell window** running `claude --enable-auto-mode`.

### What every agent must do at the end of its task

```
- Append to PROGRESS.md under ## YYYY-MM-DD with role [RoleName]:
    - [RoleName] <what was built> · files: <comma-separated>
- Tick the item in NEXT.md: change [ ] to [x] and append: ✓ YYYY-MM-DD
- Commit and push all changed files to GitHub (see below)
- Write file .claude/session-complete with content: RoleName
```

The last step is what triggers the next auto-session. If you omit it, the chain stops (which is useful if you want to pause between steps).

### Git commit + push after every task

Every agent must commit and push at the end of its task, immediately after updating PROGRESS.md and NEXT.md.

```powershell
cd C:\Claude\achilles-wines

# Stage everything that changed (never stage .env, data/, *.db, *.jsonl)
git add -A
git reset HEAD .env data/ *.db *.jsonl logs/ raw/

# Commit — write a concise conventional-commit subject line
git commit -m "feat(role): short description of what was built"

# Push
git push origin main
```

Rules:
- **Never commit** `.env`, `data/`, `*.db`, `*.jsonl`, `logs/`, `raw/` — these are gitignored but double-check.
- Use conventional-commit prefixes: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`.
- Scope is the role handle in lowercase: `feat(odysseus)`, `feat(patroclus)`, `fix(cassandra)`, etc.
- If `git config user.email` is not set, run first:
  ```powershell
  git config user.email "nicolas.vandenbroeck@vcfcigars.com"
  git config user.name "Nicolas"
  ```

### Disabling auto-launch

Simply don't write `.claude/session-complete` at the end of your task. The Stop hook exits silently if the file is absent.

### Manual launch (without auto-session)

To start a step manually, use the pattern from the original sprint commands:

```powershell
claude --enable-auto-mode "You are Odysseus on the Achilles's Wines project at C:\Claude\achilles-wines.
IMPORTANT: Do NOT invoke any skills. Do actual code work only.
Stack: Next.js + React 19 + Drizzle + Tailwind v4 + next-intl 4 + Recharts.
Theme: Athena (noir #0F0E17, magenta vin #A53860, crème #F7F4EA, or champagne #E5B25D).

Task — <priority> · <effort>: <description from NEXT.md>

When done:
- Append to PROGRESS.md under ## $(Get-Date -Format 'yyyy-MM-dd') with role [Odysseus]
- Tick the item in NEXT.md
- Write .claude\session-complete with content: Odysseus"
```

## Key files

| Path | Purpose |
|------|---------|
| `NEXT.md` | Prioritised backlog — source of truth for next steps |
| `PROGRESS.md` | Append-only delivery log |
| `DECISIONS.md` | ADRs and architectural decisions |
| `db/schema.ts` | Drizzle schema (16 tables + ops_job_queue) |
| `db/index.ts` | Drizzle client export |
| `lib/identity.ts` | normText, computeWineKey, isAppellationAllowed |
| `lib/quality/gates.ts` | regionGate, criticEnumGate, applyTriSourceRule |
| `app/globals.css` | Athena theme, utility classes |
| `messages/{lang}.json` | i18n strings (6 languages) |
| `scripts/next-session.ps1` | Auto-session launcher (Stop hook) |
| `.claude/settings.json` | Claude Code project settings (Stop hook config) |

## Database tables (summary)

```
dim_source          — scraper registry
dim_producer        — ~8 700 wine producers
dim_appellation     — AOC with lat/lng
dim_variety         — grape varieties
dim_wine            — canonical wine entity (wine_key PK)
bridge_wine_variety — wine ↔ variety M:N
fact_price          — scraped prices (scraper sources only)
fact_rating         — critic scores normalised to /100
fact_vintage_rating — vintage-level ratings by region × year
cellar_locations    — 36 storage locations × 120 capacity
cellar_inventory    — bottle stock per (wine, vintage, location)
cellar_consumption  — drink log
ops_dead_letter     — DLQ for failed/rejected records
ops_content_hashes  — ETag/content-hash dedup
ops_batch_log       — scraper run metadata
ops_job_queue       — async job queue (queued/running/done/failed/cancelled)
staging_price_candidates — pre-promotion price buffer
```
