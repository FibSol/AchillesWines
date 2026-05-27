#!/usr/bin/env node
/**
 * Dedupe dim_wine: collapse rows that share (producer_key, cuvee_norm, vintage, bottle_ml).
 *
 * Strategy:
 *  - Group rows by (producer_key, cuvee_norm, vintage, bottle_ml).
 *  - In each group, pick a SURVIVOR:
 *      1. most specific appellation (level: iconic > grand_cru > premier_cru > village > regional)
 *      2. then non-null classification wins
 *      3. then earliest first_seen_at
 *  - Re-point FK references (fact_price, fact_rating, bridge_wine_variety,
 *    cellar_inventory, cellar_consumption, staging_price_candidates) from dupes → survivor.
 *  - Promote survivor's classification/appellation if the dupe had a more specific one.
 *  - Delete dupe dim_wine rows.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 *
 *   node scripts/dedupe-wines.mjs                  # dry-run summary
 *   node scripts/dedupe-wines.mjs --filter cheval  # show only matching groups
 *   node scripts/dedupe-wines.mjs --apply          # mutate
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const FILTER = (() => {
  const i = argv.indexOf('--filter');
  return i >= 0 ? (argv[i + 1] || '').toLowerCase() : null;
})();
const SAMPLE_LIMIT = (() => {
  const i = argv.indexOf('--limit');
  return i >= 0 ? parseInt(argv[i + 1], 10) || 20 : 20;
})();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
// FK constraints need to be OFF during deduplication because we re-point child rows
// from dupe wine_keys to the survivor before deleting dupes.
db.pragma('foreign_keys = OFF');

const LEVEL_RANK = { iconic: 5, grand_cru: 4, premier_cru: 3, village: 2, regional: 1 };

// Two kinds of safe merges:
//   (A) exact cuvee_norm match — including empty (grand vin) and non-empty (same cuvée).
//       Must also share producer_key, vintage, bottle_ml.
//       For non-empty cuvee_norm we additionally require same appellation_key so we
//       don't merge a negociant's Mercurey with their Chablis.
//   (B) empty cuvee_norm across different appellations — these are the grand-vin
//       duplicates from the user's screenshot (Saint-Emilion vs Saint-Emilion Grand
//       Cru Classé on the same producer/vintage).
const groupsA = db.prepare(`
  SELECT producer_key,
         cuvee_norm,
         COALESCE(vintage,-1) AS vintage,
         bottle_ml,
         appellation_key,
         COUNT(*) AS n,
         GROUP_CONCAT(wine_key, '|') AS keys
  FROM dim_wine
  WHERE COALESCE(cuvee_norm,'') <> ''
  GROUP BY producer_key, cuvee_norm, COALESCE(vintage,-1), bottle_ml, appellation_key
  HAVING COUNT(*) > 1
`).all();

const groupsB = db.prepare(`
  SELECT producer_key,
         '' AS cuvee_norm,
         COALESCE(vintage,-1) AS vintage,
         bottle_ml,
         COUNT(*) AS n,
         GROUP_CONCAT(wine_key, '|') AS keys
  FROM dim_wine
  WHERE COALESCE(cuvee_norm,'') = ''
  GROUP BY producer_key, COALESCE(vintage,-1), bottle_ml
  HAVING COUNT(*) > 1
`).all();

const groups = [...groupsA, ...groupsB];

console.log(`Found ${groups.length} duplicate groups covering ${groups.reduce((a,g)=>a+g.n,0)} wine_key rows.`);

const fetchRow = db.prepare(`
  SELECT w.*, p.producer_name, a.appellation_name, a.level AS appellation_level
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  WHERE w.wine_key = ?
`);

function pickSurvivor(rows) {
  return rows.slice().sort((a, b) => {
    const la = LEVEL_RANK[a.appellation_level] || 0;
    const lb = LEVEL_RANK[b.appellation_level] || 0;
    if (lb !== la) return lb - la;
    const ca = a.classification ? 1 : 0;
    const cb = b.classification ? 1 : 0;
    if (cb !== ca) return cb - ca;
    return (a.first_seen_at || 0) - (b.first_seen_at || 0);
  })[0];
}

const stmts = {
  reptPrice:   db.prepare('UPDATE fact_price            SET wine_key = ? WHERE wine_key = ?'),
  reptRating:  db.prepare('UPDATE fact_rating           SET wine_key = ? WHERE wine_key = ?'),
  reptCellInv: db.prepare('UPDATE cellar_inventory      SET wine_key = ? WHERE wine_key = ?'),
  reptCellCon: db.prepare('UPDATE cellar_consumption    SET wine_key = ? WHERE wine_key = ?'),
  reptStaging: db.prepare('UPDATE OR IGNORE staging_price_candidates SET wine_key = ? WHERE wine_key = ?'),
  delStaging:  db.prepare('DELETE FROM staging_price_candidates WHERE wine_key = ?'),
  // bridge has PK (wine_key, variety_key); INSERT OR IGNORE then DELETE.
  bridgeInsert: db.prepare(`
    INSERT OR IGNORE INTO bridge_wine_variety (wine_key, variety_key, share_pct, source_confidence)
    SELECT ?, variety_key, share_pct, source_confidence FROM bridge_wine_variety WHERE wine_key = ?
  `),
  bridgeDelete: db.prepare('DELETE FROM bridge_wine_variety WHERE wine_key = ?'),
  updateSurvivor: db.prepare(`
    UPDATE dim_wine
    SET appellation_key = ?, classification = COALESCE(classification, ?)
    WHERE wine_key = ?
  `),
  deleteDupe: db.prepare('DELETE FROM dim_wine WHERE wine_key = ?'),
};

let collapseCount = 0;
let rerouteRows = { price: 0, rating: 0, inv: 0, con: 0, staging: 0, bridge: 0 };
const samples = [];

function normApp(s) { return (s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim(); }

// Split a group of empty-cuvée rows into appellation-containment clusters.
// Two rows belong together only if their appellation names are equal OR one is
// a substring of the other (Saint-Emilion ⊂ Saint-Emilion Grand Cru Classé).
function clusterByAppellationChain(rows) {
  const clusters = [];
  for (const r of rows) {
    const rn = normApp(r.appellation_name);
    let placed = false;
    for (const c of clusters) {
      const compatible = c.every(other => {
        const on = normApp(other.appellation_name);
        return rn === on || rn.includes(on) || on.includes(rn);
      });
      if (compatible) { c.push(r); placed = true; break; }
    }
    if (!placed) clusters.push([r]);
  }
  return clusters;
}

const plan = [];
for (const g of groups) {
  const keys = g.keys.split('|');
  const rows = keys.map(k => fetchRow.get(k)).filter(Boolean);
  if (rows.length < 2) continue;
  // For empty-cuvée groups (group B), enforce appellation-containment clustering.
  const isEmptyCuvee = !g.cuvee_norm || g.cuvee_norm === '';
  const subGroups = isEmptyCuvee ? clusterByAppellationChain(rows) : [rows];
  for (const sub of subGroups) {
    if (sub.length < 2) continue;
    const survivor = pickSurvivor(sub);
    const dupes = sub.filter(r => r.wine_key !== survivor.wine_key);
    plan.push({ survivor, dupes });

    const filterHit = !FILTER ||
      survivor.producer_name.toLowerCase().includes(FILTER) ||
      (survivor.cuvee_name || '').toLowerCase().includes(FILTER);

    if (filterHit && samples.length < SAMPLE_LIMIT) {
      samples.push({
        survivor: {
          wine_key: survivor.wine_key, producer: survivor.producer_name,
          cuvee: survivor.cuvee_name, vintage: survivor.vintage,
          appellation: survivor.appellation_name, classification: survivor.classification,
        },
        dupes: dupes.map(d => ({
          wine_key: d.wine_key, appellation: d.appellation_name, classification: d.classification,
        })),
      });
    }
  }
}

const tx = db.transaction(() => {
  for (const { survivor, dupes } of plan) {
    const bestClass = survivor.classification || dupes.map(d => d.classification).find(Boolean) || null;
    stmts.updateSurvivor.run(survivor.appellation_key, bestClass, survivor.wine_key);
    for (const d of dupes) {
      rerouteRows.price   += stmts.reptPrice.run(survivor.wine_key, d.wine_key).changes;
      rerouteRows.rating  += stmts.reptRating.run(survivor.wine_key, d.wine_key).changes;
      rerouteRows.inv     += stmts.reptCellInv.run(survivor.wine_key, d.wine_key).changes;
      rerouteRows.con     += stmts.reptCellCon.run(survivor.wine_key, d.wine_key).changes;
      rerouteRows.staging += stmts.reptStaging.run(survivor.wine_key, d.wine_key).changes;
      stmts.delStaging.run(d.wine_key);
      stmts.bridgeInsert.run(survivor.wine_key, d.wine_key);
      rerouteRows.bridge += stmts.bridgeDelete.run(d.wine_key).changes;
      stmts.deleteDupe.run(d.wine_key);
    }
    collapseCount += dupes.length;
  }
});

console.log(`\n--- Sample of ${samples.length} groups ---\n`);
for (const s of samples) {
  console.log(`SURVIVOR  [${s.survivor.wine_key}]  ${s.survivor.producer} ${s.survivor.cuvee ? '· ' + s.survivor.cuvee : ''} ${s.survivor.vintage ?? 'NV'}`);
  console.log(`          appellation="${s.survivor.appellation}"  classification="${s.survivor.classification ?? ''}"`);
  for (const d of s.dupes) {
    console.log(`  dupe    [${d.wine_key}]  appellation="${d.appellation}"  classification="${d.classification ?? ''}"`);
  }
  console.log('');
}

if (APPLY) {
  tx();
  console.log(`Collapsed ${collapseCount} duplicate rows.`);
  console.log(`Re-pointed: price=${rerouteRows.price}  rating=${rerouteRows.rating}  cellar_inv=${rerouteRows.inv}  cellar_con=${rerouteRows.con}  staging=${rerouteRows.staging}  bridge_deleted=${rerouteRows.bridge}`);
} else {
  console.log(`(Dry-run — would collapse ${groups.reduce((a,g)=>a+g.n-1,0)} dupe rows. Re-run with --apply to mutate.)`);
}

db.close();
