#!/usr/bin/env node
/**
 * Re-attack the manual-review residue using producer-level inference from
 * the authoritative references we now have (INAO 2012, FranceAgriMer IGP,
 * Bordeaux guide).
 *
 * Three passes:
 *
 *  A. Vin de France ghosts (the 5 396 left over after merge-vin-de-france-
 *     ghosts.mjs collapsed the same-vintage twins). For each remaining VdF
 *     wine, infer the producer's canonical appellation from their OTHER
 *     wines. If ≥80% of the producer's non-VdF wines share a single
 *     appellation, re-point the VdF wine to that appellation key.
 *
 *  B. Producer-name "vintage" residue (175 rows the mutilation guard
 *     refused). Try to find a BARE-NAME twin (same producer minus vintage
 *     literal) already in dim_producer and merge.
 *
 *  C. Producer-name "packaging / size / shop_code" residue: same as B but
 *     for those pollution markers.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const LIMIT_SAMPLES = 12;
const VDF_CONFIDENCE = (() => {
  const i = argv.indexOf('--confidence');
  return i >= 0 ? parseFloat(argv[i + 1]) || 0.80 : 0.80;
})();
const VDF_MIN_TOP = (() => {
  const i = argv.indexOf('--min-top');
  return i >= 0 ? parseInt(argv[i + 1], 10) || 3 : 3;
})();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

const vdfRow = db.prepare("SELECT appellation_key FROM dim_appellation WHERE appellation_name = 'Vin de France' AND country_code='FR'").get();
if (!vdfRow) { console.log('Vin de France appellation not found.'); process.exit(0); }
const VDF_KEY = vdfRow.appellation_key;

// ---------- A. VdF ghost resolution by producer majority ----------

// Group wines by producer for FR producers that have at least one VdF wine.
const candidates = db.prepare(`
  SELECT w.wine_key, w.producer_key, w.vintage, w.bottle_ml, w.appellation_key, w.cuvee_name
  FROM dim_wine w
  WHERE w.appellation_key = ?
`).all(VDF_KEY);

const producerStats = db.prepare(`
  SELECT appellation_key, COUNT(*) AS n
  FROM dim_wine
  WHERE producer_key = ? AND appellation_key <> ?
  GROUP BY appellation_key
  ORDER BY n DESC
`);

const repointWines = db.prepare('UPDATE dim_wine SET appellation_key = ? WHERE wine_key = ?');

const planA = [];
const samplesA = [];

for (const c of candidates) {
  const other = producerStats.all(c.producer_key, VDF_KEY);
  if (other.length === 0) continue;          // producer has only VdF wines, can't infer
  const total = other.reduce((s, r) => s + r.n, 0);
  const top = other[0];
  const share = top.n / total;
  if (share < VDF_CONFIDENCE) continue;       // not confident enough
  if (top.n < VDF_MIN_TOP) continue;          // need a meaningful sample
  planA.push({ wineKey: c.wine_key, fromVdf: true, targetKey: top.appellation_key, share, top_n: top.n });
  if (samplesA.length < LIMIT_SAMPLES) {
    const info = db.prepare(`
      SELECT p.producer_name, a.appellation_name
      FROM dim_wine w JOIN dim_producer p ON p.producer_key=w.producer_key
      LEFT JOIN dim_appellation a ON a.appellation_key=?
      WHERE w.wine_key=?
    `).get(top.appellation_key, c.wine_key);
    samplesA.push(`[${c.wine_key}] ${info.producer_name} (${c.vintage ?? 'NV'})  →  "${info.appellation_name}"  (${top.n}/${total} = ${(share*100).toFixed(0)}%)`);
  }
}

console.log(`A. VdF ghost candidates with ≥${VDF_CONFIDENCE*100}% producer-appellation consensus : ${planA.length}\n`);
for (const s of samplesA) console.log(`   ${s}`);

if (APPLY) {
  const tx = db.transaction(() => {
    for (const p of planA) repointWines.run(p.targetKey, p.wineKey);
  });
  tx();
}

// ---------- B. Producer "vintage in name" residue → merge into bare twin ----------

const pollutedProducers = db.prepare(`
  SELECT producer_key, producer_name, producer_norm, country_code
  FROM dim_producer
  WHERE producer_name GLOB '*[0-9][0-9][0-9][0-9]*'
`).all();

const findByExpandedNorm = db.prepare(`
  SELECT producer_key, producer_name FROM dim_producer
  WHERE country_code = ? AND producer_norm = ?
`);

const repointProducer = db.prepare('UPDATE dim_wine SET producer_key = ? WHERE producer_key = ?');
const deleteProducer  = db.prepare('DELETE FROM dim_producer WHERE producer_key = ?');

const planB = [];
const samplesB = [];

for (const p of pollutedProducers) {
  // Strip 4-digit year from the name (and the resulting double spaces).
  const stripped = p.producer_name
    .replace(/\b(19|20)\d{2}\b/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/^\s*[-,–—:]+\s*/, '')
    .replace(/\s*[-,–—:]+\s*$/, '')
    .trim();
  if (!stripped || stripped === p.producer_name) continue;
  const strippedNorm = normText(stripped);
  if (!strippedNorm || strippedNorm.split(' ').length < 2) continue;
  // Try direct + Château/Domaine prefix expansion (mirror cleanup-producer-names logic).
  const candidates = [strippedNorm, `chateau ${strippedNorm}`, `domaine ${strippedNorm}`, strippedNorm.replace(/^chateau /, ''), strippedNorm.replace(/^domaine /, '')];
  let twin = null;
  for (const cand of candidates) {
    const r = findByExpandedNorm.get(p.country_code, cand);
    if (r && r.producer_key !== p.producer_key) { twin = r; break; }
  }
  if (!twin) continue;
  planB.push({ from: p, into: twin });
  if (samplesB.length < LIMIT_SAMPLES) {
    samplesB.push(`"${p.producer_name}"  →  "${twin.producer_name}"`);
  }
}

console.log(`\nB. Producer-vintage residue with existing bare-name twin : ${planB.length}\n`);
for (const s of samplesB) console.log(`   ${s}`);

let winesMovedB = 0;
if (APPLY) {
  const tx = db.transaction(() => {
    for (const item of planB) {
      winesMovedB += repointProducer.run(item.into.producer_key, item.from.producer_key).changes;
      try { deleteProducer.run(item.from.producer_key); } catch (_) { /* fk leftovers */ }
    }
  });
  tx();
  console.log(`   wines re-pointed: ${winesMovedB}`);
}

// ---------- C. Producer packaging / shop-code / size residue ----------

const pollutedC = db.prepare(`
  SELECT producer_key, producer_name, producer_norm, country_code
  FROM dim_producer
  WHERE producer_name LIKE '%COFFRET%' OR producer_name LIKE '%MAGNUM%'
     OR producer_name LIKE '%(CB%' OR producer_name LIKE '%(C%)%'
     OR producer_name LIKE '%75CL%' OR producer_name LIKE '%150CL%'
     OR producer_name LIKE '%EN ETUI%'
`).all();

const planC = [];
const samplesC = [];

for (const p of pollutedC) {
  // Aggressive strip: vintage, packaging, sizes, shop codes, classification tails.
  let stripped = p.producer_name
    .replace(/\b(19|20)\d{2}\b/g, ' ')
    .replace(/\s*\(CB?\d{1,2}\)/gi, ' ')
    .replace(/\s+CB?\d{1,2}\b/gi, ' ')
    .replace(/\s+\d+\s*(ml|cl|l)\b/gi, ' ')
    .replace(/\b(magnum|jeroboam|coffret(\s+(or|argent))?|en\s+etui|en\s+coffret|\+\s*coffret.*)$/gi, '')
    .replace(/\s+(ROUGE|BLANC|ROSE|ROSÉ|RED|WHITE)$/i, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!stripped || stripped.length < 4) continue;
  if (stripped === p.producer_name) continue;
  const strippedNorm = normText(stripped);
  if (strippedNorm.split(' ').length < 2) continue;
  const candidates = [strippedNorm, `chateau ${strippedNorm}`, `domaine ${strippedNorm}`, strippedNorm.replace(/^chateau /, ''), strippedNorm.replace(/^domaine /, '')];
  let twin = null;
  for (const cand of candidates) {
    const r = findByExpandedNorm.get(p.country_code, cand);
    if (r && r.producer_key !== p.producer_key) { twin = r; break; }
  }
  if (!twin) continue;
  planC.push({ from: p, into: twin });
  if (samplesC.length < LIMIT_SAMPLES) {
    samplesC.push(`"${p.producer_name}"  →  "${twin.producer_name}"`);
  }
}

console.log(`\nC. Producer packaging/size/shop-code residue with twin : ${planC.length}\n`);
for (const s of samplesC) console.log(`   ${s}`);

let winesMovedC = 0;
if (APPLY) {
  const tx = db.transaction(() => {
    for (const item of planC) {
      winesMovedC += repointProducer.run(item.into.producer_key, item.from.producer_key).changes;
      try { deleteProducer.run(item.from.producer_key); } catch (_) { /* */ }
    }
  });
  tx();
  console.log(`   wines re-pointed: ${winesMovedC}`);
}

console.log(`\n${APPLY ? 'Applied' : 'Dry-run summary'}: A=${planA.length} VdF ghosts, B=${planB.length} producer-vintage merges, C=${planC.length} packaging/size merges.`);
if (!APPLY) console.log('(Re-run with --apply to mutate.)');

db.close();
