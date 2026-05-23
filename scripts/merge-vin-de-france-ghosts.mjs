#!/usr/bin/env node
/**
 * Merge "Vin de France" ghost rows into their real-appellation twin.
 *
 * Heuristic: for every dim_wine row with appellation_name='Vin de France'
 * whose producer ALSO has another row at the same vintage+bottle_ml with
 * a real appellation, the VdF row is treated as a scraper fallback and is
 * merged into the real-appellation row (FK references re-pointed, dupe deleted).
 *
 * If a producer has ONLY a VdF row for that vintage, the row is left alone
 * (it might be a genuine declassified cuvée).
 *
 * Defaults to DRY-RUN; pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const FILTER = (() => { const i = argv.indexOf('--filter'); return i>=0 ? (argv[i+1]||'').toLowerCase() : null; })();
const SAMPLE_LIMIT = (() => { const i = argv.indexOf('--limit'); return i>=0 ? (parseInt(argv[i+1],10)||20) : 20; })();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// Find all VdF rows grouped by (producer_key, vintage, bottle_ml, cuvee_norm).
// For each group, if there's a non-VdF row in the same identity tuple, merge.
const vdfKey = db.prepare("SELECT appellation_key FROM dim_appellation WHERE appellation_name = 'Vin de France'").get();
if (!vdfKey) {
  console.log('No Vin de France appellation found — nothing to do.');
  db.close(); process.exit(0);
}

const groups = db.prepare(`
  SELECT w1.wine_key AS vdf_key,
         w1.producer_key, w1.vintage, w1.bottle_ml, COALESCE(w1.cuvee_norm,'') AS cuvee_norm,
         GROUP_CONCAT(w2.wine_key, '|') AS real_keys
  FROM dim_wine w1
  JOIN dim_wine w2 ON w2.producer_key = w1.producer_key
                  AND COALESCE(w2.vintage,-1) = COALESCE(w1.vintage,-1)
                  AND w2.bottle_ml = w1.bottle_ml
                  AND COALESCE(w2.cuvee_norm,'') = COALESCE(w1.cuvee_norm,'')
                  AND w2.appellation_key <> ?
                  AND w2.wine_key <> w1.wine_key
  WHERE w1.appellation_key = ?
  GROUP BY w1.wine_key
`).all(vdfKey.appellation_key, vdfKey.appellation_key);

const fetchRow = db.prepare(`
  SELECT w.*, p.producer_name, a.appellation_name, a.level AS app_level
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  WHERE w.wine_key = ?
`);

const LEVEL_RANK = { iconic: 5, grand_cru: 4, premier_cru: 3, village: 2, regional: 1 };

const stmts = {
  reptPrice:    db.prepare('UPDATE fact_price            SET wine_key = ? WHERE wine_key = ?'),
  reptRating:   db.prepare('UPDATE fact_rating           SET wine_key = ? WHERE wine_key = ?'),
  reptCellInv:  db.prepare('UPDATE cellar_inventory      SET wine_key = ? WHERE wine_key = ?'),
  reptCellCon:  db.prepare('UPDATE cellar_consumption    SET wine_key = ? WHERE wine_key = ?'),
  reptStaging:  db.prepare('UPDATE OR IGNORE staging_price_candidates SET wine_key = ? WHERE wine_key = ?'),
  delStaging:   db.prepare('DELETE FROM staging_price_candidates WHERE wine_key = ?'),
  bridgeInsert: db.prepare(`
    INSERT OR IGNORE INTO bridge_wine_variety (wine_key, variety_key, share_pct, source_confidence)
    SELECT ?, variety_key, share_pct, source_confidence FROM bridge_wine_variety WHERE wine_key = ?
  `),
  bridgeDelete: db.prepare('DELETE FROM bridge_wine_variety WHERE wine_key = ?'),
  deleteDupe:   db.prepare('DELETE FROM dim_wine WHERE wine_key = ?'),
};

const plan = [];
const samples = [];

for (const g of groups) {
  const vdf = fetchRow.get(g.vdf_key);
  const realKeys = (g.real_keys || '').split('|').filter(Boolean);
  if (realKeys.length === 0) continue;
  const reals = realKeys.map(k => fetchRow.get(k)).filter(Boolean);
  // Pick the survivor: most specific appellation level, then non-null classification.
  const survivor = reals.slice().sort((a, b) => {
    const la = LEVEL_RANK[a.app_level] || 0;
    const lb = LEVEL_RANK[b.app_level] || 0;
    if (lb !== la) return lb - la;
    const ca = a.classification ? 1 : 0;
    const cb = b.classification ? 1 : 0;
    if (cb !== ca) return cb - ca;
    return (a.first_seen_at || 0) - (b.first_seen_at || 0);
  })[0];
  plan.push({ vdf, survivor });

  const matchesFilter = !FILTER ||
    vdf.producer_name.toLowerCase().includes(FILTER) ||
    survivor.producer_name.toLowerCase().includes(FILTER);
  if (matchesFilter && samples.length < SAMPLE_LIMIT) {
    samples.push({ vdf, survivor });
  }
}

console.log(`Vin de France ghosts with a real-appellation twin : ${plan.length}\n`);
console.log(`--- Sample of ${samples.length} ---\n`);
for (const s of samples) {
  console.log(`MERGE  [${s.vdf.wine_key}] VdF  →  [${s.survivor.wine_key}] "${s.survivor.appellation_name}"`);
  console.log(`       ${s.vdf.producer_name} · ${s.vdf.vintage ?? 'NV'} · class="${s.survivor.classification ?? ''}"`);
}

if (APPLY) {
  let rerouted = { price: 0, rating: 0, inv: 0, con: 0, staging: 0 };
  const tx = db.transaction(() => {
    for (const { vdf, survivor } of plan) {
      rerouted.price   += stmts.reptPrice.run(survivor.wine_key, vdf.wine_key).changes;
      rerouted.rating  += stmts.reptRating.run(survivor.wine_key, vdf.wine_key).changes;
      rerouted.inv     += stmts.reptCellInv.run(survivor.wine_key, vdf.wine_key).changes;
      rerouted.con     += stmts.reptCellCon.run(survivor.wine_key, vdf.wine_key).changes;
      rerouted.staging += stmts.reptStaging.run(survivor.wine_key, vdf.wine_key).changes;
      stmts.delStaging.run(vdf.wine_key);
      stmts.bridgeInsert.run(survivor.wine_key, vdf.wine_key);
      stmts.bridgeDelete.run(vdf.wine_key);
      stmts.deleteDupe.run(vdf.wine_key);
    }
  });
  tx();
  console.log(`\nApplied: collapsed ${plan.length} VdF ghosts.`);
  console.log(`Re-pointed: price=${rerouted.price}  rating=${rerouted.rating}  cellar_inv=${rerouted.inv}  cellar_con=${rerouted.con}  staging=${rerouted.staging}`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
