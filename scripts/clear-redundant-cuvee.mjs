#!/usr/bin/env node
/**
 * When cuvee_name === appellation_name, the cuvée is redundant (it just
 * restates the AOC). Common pattern for négociants (Bouchard "Mercurey",
 * Wm Fèvre "Chablis", Drouhin "Pommard", etc.) where the bottling has no
 * vineyard / climat distinction beyond the appellation.
 *
 * Action: clear cuvee_name + cuvee_norm, rebuild canonical_name as
 * "<producer> <vintage>" (skip cuvée).
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

const rows = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage, p.producer_name
  FROM dim_wine w
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  JOIN dim_producer p   ON p.producer_key   = w.producer_key
  WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name <> ''
    AND w.cuvee_name = a.appellation_name
`).all();

console.log(`Wines with cuvee_name === appellation_name : ${rows.length}\n`);

const upd = db.prepare(`UPDATE dim_wine SET cuvee_name='', cuvee_norm='', canonical_name=? WHERE wine_key=?`);

const sample = rows.slice(0, 12);
for (const r of sample) {
  console.log(`  [${r.wine_key}] ${r.producer_name} · ${r.vintage ?? 'NV'} · cuvée="${r.cuvee_name}" → ""`);
}

if (APPLY) {
  const tx = db.transaction(() => {
    for (const r of rows) {
      const canonical = `${r.producer_name}${r.vintage ? ' ' + r.vintage : ''}`;
      upd.run(canonical, r.wine_key);
    }
  });
  tx();
  console.log(`\nApplied: cleared cuvée on ${rows.length} wines.`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
