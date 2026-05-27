#!/usr/bin/env node
/**
 * Targeted SQL fixes for wave-2 residuals — items too complex for the
 * automated cleanup scripts.
 *
 * 1. Cuvée-name fixes for the remaining cuvee_appellation_tail entries
 * 2. Delete non-French wines still in the DB (Craggy Range, Cepa 21)
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const db = new Database(DB_PATH, APPLY ? undefined : { readonly: true });
if (APPLY) db.pragma('foreign_keys = OFF');

// ── 1. Cuvée-name targeted fixes ────────────────────────────────────────────

const CUVEE_FIXES = [
  // "Petit Chablis - Chablis" → "Petit Chablis" (strip the " - Chablis" region suffix)
  { key: '06bc992632e03f98', newName: 'Petit Chablis', newNorm: 'petit chablis' },

  // "Jean et Sébastien Dauvissat - Chablis Vaillons" → "Vaillons"
  { key: 'f9717aa45b67e355', newName: 'Vaillons', newNorm: 'vaillons' },

  // "Jean et Sébastien Dauvissat - Chablis Vaillons Vieilles Vignes" → "Vaillons Vieilles Vignes"
  { key: '542440e0e6e0c0f3', newName: 'Vaillons Vieilles Vignes', newNorm: 'vaillons vieilles vignes' },

  // "Demi Bouteille - Chablis - William Fevre" → clear (format variant, not a named cuvée)
  { key: 'b89f0211cbafe2f3', newName: '', newNorm: '' },

  // "Demi-bouteille - Chablis Vaillons - William Fevre" → "Vaillons"
  { key: '547374d9981cbbac', newName: 'Vaillons', newNorm: 'vaillons' },

  // "Aromes de Pavie, Saint Emilion" → "Aromes de Pavie" (second wine of Château Pavie)
  { key: 'da9d168fb60d02a4', newName: 'Aromes de Pavie', newNorm: 'aromes de pavie' },

  // "Canon-Fronsac" cuvée = appellation → clear (appellation-only entry)
  { key: '079486c759f47ea3', newName: '', newNorm: '' },
];

// ── 2. Non-French wine deletions ─────────────────────────────────────────────
// Cepa 21 (Spain, Ribera del Duero) and Craggy Range (NZ) — false positives of
// SHOP_CODE_RE; these wines should not be in the French-wine database.
const NON_FRENCH_KEYS = [
  '0e9103159d407ad7',  // Cepa 21 "C21" NV
  'bb8ad59df3916f4d',  // Cepa 21 "C21 (Ribera del Duero)" 2010
  '91d784d06f4f3233',  // Craggy Range "C3 Kidnappers Vineyard" NV
  '1781aaa848d40c0f',  // Craggy Range "C3 Kidnappers Vineyard Chardonnay (Hawke's Bay)" 2008
];

const CHILD_TABLES = [
  'fact_price', 'fact_rating', 'cellar_inventory', 'cellar_consumption',
  'bridge_wine_variety', 'staging_price_candidates',
];

// ── Preview ──────────────────────────────────────────────────────────────────

const fetchWine = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, p.producer_name, w.vintage
  FROM dim_wine w JOIN dim_producer p ON p.producer_key = w.producer_key
  WHERE w.wine_key = ?
`);

console.log('=== Cuvée name fixes ===');
for (const f of CUVEE_FIXES) {
  const w = fetchWine.get(f.key);
  if (!w) { console.log(`  [${f.key}] NOT FOUND`); continue; }
  console.log(`  [${f.key}] ${w.producer_name} · ${w.vintage ?? 'NV'}`);
  console.log(`    "${w.cuvee_name}"  →  "${f.newName}"`);
}

console.log('\n=== Non-French wine deletions ===');
for (const key of NON_FRENCH_KEYS) {
  const w = fetchWine.get(key);
  if (w) console.log(`  DELETE [${key}] ${w.producer_name} "${w.cuvee_name}" ${w.vintage ?? 'NV'}`);
  else    console.log(`  [${key}] already gone`);
}

// ── Apply ────────────────────────────────────────────────────────────────────

if (APPLY) {
  const updCuvee = db.prepare(
    'UPDATE dim_wine SET cuvee_name = ?, cuvee_norm = ? WHERE wine_key = ?'
  );
  const delChild = (table) => db.prepare(`DELETE FROM ${table} WHERE wine_key = ?`);
  const delWine  = db.prepare('DELETE FROM dim_wine WHERE wine_key = ?');
  const cleanupOrphanProducers = db.prepare(`
    DELETE FROM dim_producer
    WHERE producer_key IN (
      SELECT producer_key FROM dim_producer p
      WHERE NOT EXISTS (SELECT 1 FROM dim_wine w WHERE w.producer_key = p.producer_key)
    )
  `);

  const tx = db.transaction(() => {
    // Cuvée fixes
    for (const f of CUVEE_FIXES) {
      const r = updCuvee.run(f.newName, f.newNorm, f.key);
      if (r.changes) console.log(`  Updated [${f.key}] → "${f.newName}"`);
    }
    // Delete non-French wines
    for (const key of NON_FRENCH_KEYS) {
      for (const tbl of CHILD_TABLES) delChild(tbl).run(key);
      const r = delWine.run(key);
      if (r.changes) console.log(`  Deleted [${key}]`);
    }
    // Clean up orphaned producers
    const orphans = cleanupOrphanProducers.run();
    if (orphans.changes) console.log(`  Removed ${orphans.changes} orphaned producers`);
  });
  tx();
  console.log('\nDone.');
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
