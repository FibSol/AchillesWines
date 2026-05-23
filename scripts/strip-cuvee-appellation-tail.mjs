#!/usr/bin/env node
/**
 * Strip the trailing " - <appellation>" suffix from cuvee_name when:
 *   - it matches the wine's actual appellation_name (or a token of it), AND
 *   - removing it leaves at least 2 characters.
 *
 * Common pattern from Vinatis / Charly Nicolle / Wm Fèvre / Brocard scrapers
 * that append the appellation to the cuvée display:
 *   "Trio - Saint-Émilion"     →  "Trio"
 *   "Per Aspera - Chablis"     →  "Per Aspera"
 *   "Bougros - Chablis"        →  "Bougros"  (Chablis Grand Cru, climat name)
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

const rows = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage, p.producer_name, a.appellation_name
  FROM dim_wine w
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  JOIN dim_producer p   ON p.producer_key   = w.producer_key
  WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name <> ''
`).all();

const plan = [];

for (const r of rows) {
  const cn = r.cuvee_name;
  const app = r.appellation_name || '';
  // Build a list of appellation-derived suffixes to try, longest first.
  const appTokens = new Set();
  if (app) {
    appTokens.add(app);                            // full name
    // First word group ("Chablis" from "Chablis Grand Cru" or "Chablis 1er Cru")
    const firstWord = app.split(/\s+/)[0];
    if (firstWord && firstWord.length >= 5) appTokens.add(firstWord);
    // Common Bordeaux: "Saint-Émilion" from "Saint-Émilion Grand Cru"
    const m = app.match(/^(Saint-[ÉE]milion|Saint-Estèphe|Saint-Julien|Pessac-Léognan|Médoc|Haut-Médoc|Pauillac|Margaux)/i);
    if (m) appTokens.add(m[1]);
  }
  // Also strip generic "- Chablis" / "- Saint-Émilion" when appellation contains the token.
  let newCuvee = cn;
  let matched = false;
  for (const token of [...appTokens].sort((a,b) => b.length - a.length)) {
    // Build regex that matches " - <token>" or "- <token>" at the end of the cuvée
    // (with optional trailing decorators like "à Prix Malin").
    const escToken = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`\\s*[-–—]\\s*${escToken}(\\s+[à\\s\\w]+)?\\s*$`, 'i');
    if (re.test(newCuvee)) {
      newCuvee = newCuvee.replace(re, '').trim();
      matched = true;
      break;
    }
  }
  if (!matched) continue;
  if (!newCuvee || newCuvee.length < 2) continue;   // safety: don't blank everything
  if (newCuvee === cn) continue;
  plan.push({ wineKey: r.wine_key, oldCuvee: cn, newCuvee, newNorm: normText(newCuvee), producer: r.producer_name, vintage: r.vintage, app });
}

console.log(`Cuvée-appellation tail strips planned : ${plan.length}\n`);
const sample = plan.slice(0, 14);
for (const s of sample) {
  console.log(`  [${s.wineKey}] ${s.producer} · ${s.vintage ?? 'NV'} · "${s.app}"`);
  console.log(`     "${s.oldCuvee}"  →  "${s.newCuvee}"`);
}

if (APPLY) {
  const upd = db.prepare(`UPDATE dim_wine SET cuvee_name=?, cuvee_norm=?, canonical_name=? WHERE wine_key=?`);
  const tx = db.transaction(() => {
    for (const p of plan) {
      const canonical = `${p.producer}${p.newCuvee ? ' ' + p.newCuvee : ''}${p.vintage ? ' ' + p.vintage : ''}`;
      upd.run(p.newCuvee, p.newNorm, canonical, p.wineKey);
    }
  });
  tx();
  console.log(`\nApplied ${plan.length} cuvée-tail strips.`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
