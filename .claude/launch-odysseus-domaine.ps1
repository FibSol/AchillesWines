Set-Location "C:\Claude\achilles-wines"

$prompt = @"
You are Odysseus on the Achilles's Wines project at C:\Claude\achilles-wines.
IMPORTANT: Do NOT invoke any skills. Do actual code work only.
Stack: Next.js 16 + React 19 + Drizzle + better-sqlite3 + Tailwind v4 + next-intl 4 + Recharts.
Theme: Dionysus (aubergine #1A0B2E, coral #FF5C8A, ivory #FAF7F5). Use PageShell + glass-card + stat-card from globals.css.

Task -- P1 - 3h: Build Page Domaine/[id]
- Route: app/[locale]/domaines/[id]/page.tsx
- Fetch dim_producer row by id, plus all dim_wine rows linked to this producer
- For each wine: fact_price rows (latest per source) + fact_rating rows
- Display: producer header (name, region, appellation badges, allowed_appellations list)
- Cuvees table: wine name, appellation, best rating /100, price range, source count badges
- Recharts LineChart: price over time (x=scraped_at, y=price_eur, one line per source)
- Recharts BarChart: ratings by critic (x=critic_code, y=score_norm_100)
- Drinking window: if fact_rating has drink_from/drink_to, show a simple horizontal band (coral fill, ivory text)
- i18n: add domaine.* keys to all 6 messages/*.json files
- Run npx tsc --noEmit before finishing

When done:
- Append to PROGRESS.md under ## 2026-05-22 with role [Odysseus]
- Tick the item in NEXT.md: change [ ] to [x] and append the check mark and date 2026-05-22
- Write file .claude\session-complete with content: Odysseus
"@

& "C:\Users\Nicolas\AppData\Roaming\Claude\claude-code\2.1.146\claude.exe" --enable-auto-mode $prompt
