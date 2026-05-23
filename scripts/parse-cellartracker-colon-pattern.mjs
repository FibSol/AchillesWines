#!/usr/bin/env node
/**
 * Many FR dim_producer rows are actually full CellarTracker wine names that
 * the scraper failed to decompose. Format:
 *
 *   <Producer> : <Appellation> <Classification> "<Climat>" [Domaine|Monopole] [Vintage]
 *
 * Example:
 *   "Bouchard Père & Fils : Beaune 1er cru 'du Château' Domaine 2012"
 *     producer       = "Bouchard Père & Fils"
 *     appellation    = "Beaune Premier Cru"  (1er cru → moved to classification + appellation suffix per INAO convention)
 *     classification = "1er Cru"
 *     cuvée          = "du Château"
 *     vintage        = 2012
 *
 *   "Jean-Marc Brocard : Chablis 1er cru 'Montmains'"
 *     producer       = "Domaine Jean-Marc Brocard"  (lookup adds prefix if existing)
 *     appellation    = "Chablis Premier Cru"
 *     classification = "1er Cru"
 *     cuvée          = "Montmains"
 *
 * For each parsed row:
 *   1. Find or create the real producer in dim_producer (prefix-expansion lookup).
 *   2. Find or create the appellation row.
 *   3. For every dim_wine still pointing at the messy producer, update its
 *      producer_key + appellation_key + cuvee_name + classification + canonical_name.
 *   4. Delete the now-orphan messy producer row.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const SAMPLE_LIMIT = (() => { const i = argv.indexOf('--limit'); return i >= 0 ? (parseInt(argv[i + 1], 10) || 25) : 25; })();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}
function expandPrefix(norm) {
  if (/^ch\s+/.test(norm))    return 'chateau ' + norm.slice(3);
  if (/^d\s+/.test(norm))     return 'domaine ' + norm.slice(2);
  if (/^dom\s+/.test(norm))   return 'domaine ' + norm.slice(4);
  return norm;
}

// ---------- 1. Find the colon-pattern producers ----------

const pollutedProducers = db.prepare(`
  SELECT producer_key, producer_name
  FROM dim_producer
  WHERE country_code='FR'
    AND producer_name LIKE '% : %'
    AND (producer_name LIKE '%1er cru%' OR producer_name LIKE '%Grand cru%'
         OR producer_name LIKE '%Premier cru%' OR producer_name LIKE '%1er Cru%')
`).all();

console.log(`Colon-pattern producers found : ${pollutedProducers.length}\n`);

// ---------- 2. Parser ----------

const APPELLATION_HEADS = [
  // Burgundy
  'Beaune', 'Volnay', 'Pommard', 'Meursault', 'Puligny-Montrachet',
  'Chassagne-Montrachet', 'Savigny-Les-Beaune', 'Savigny-lès-Beaune',
  'Aloxe-Corton', 'Corton', 'Saint-Aubin', 'Saint-Romain',
  'Auxey-Duresses', 'Monthélie', 'Santenay', 'Ladoix',
  'Pernand-Vergelesses', 'Chorey-lès-Beaune', 'Marsannay',
  'Fixin', 'Gevrey-Chambertin', 'Morey-Saint-Denis',
  'Chambolle-Musigny', 'Vougeot', 'Vosne-Romanée', 'Vosne-Romanee',
  'Nuits-Saint-Georges', 'Mercurey', 'Rully', 'Givry', 'Montagny',
  'Pouilly-Fuissé', 'Saint-Véran', 'Chablis',
  // Champagne (Grand cru and Premier cru villages)
  'Blanc de Blancs', 'Blanc de Noirs',
];

function parseRow(name) {
  // Producer is everything before the first " : ".
  const colonIdx = name.indexOf(' : ');
  if (colonIdx < 0) return null;
  const producer = name.slice(0, colonIdx).trim();
  const rest = name.slice(colonIdx + 3).trim();

  // Extract climat in quotes (single or double, English / typographic).
  let climat = '';
  const quoteMatch = rest.match(/["'""]([^"'""]+)["'""]/);
  if (quoteMatch) climat = quoteMatch[1].trim();

  // Detect classification.
  let classification = null;
  if (/grand\s+cru/i.test(rest)) classification = 'Grand Cru';
  else if (/(1er|premier)\s+cru/i.test(rest)) classification = '1er Cru';

  // Detect vintage (4-digit year).
  const vintageMatch = rest.match(/\b(19|20)\d{2}\b/);
  const vintage = vintageMatch ? parseInt(vintageMatch[0], 10) : null;

  // Detect appellation head — first known appellation token before classification.
  let appellation = null;
  for (const head of APPELLATION_HEADS) {
    const reHead = new RegExp(`^\\s*${head.replace(/[-]/g, '[- ]')}\\b`, 'i');
    if (reHead.test(rest)) { appellation = head; break; }
  }

  return { producer, appellation, classification, climat, vintage };
}

// ---------- 3. Lookups ----------

const findProducer = db.prepare("SELECT * FROM dim_producer WHERE country_code='FR' AND producer_norm = ?");
const findAppByName = db.prepare("SELECT * FROM dim_appellation WHERE country_code='FR' AND appellation_name = ?");
const findAppByNorm = db.prepare("SELECT * FROM dim_appellation WHERE country_code='FR' AND appellation_norm = ?");
const insertProducer = db.prepare(`
  INSERT INTO dim_producer (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
  VALUES (?, ?, 'FR', '[]', '[]', 'pending_review')
`);
const insertApp = db.prepare(`
  INSERT INTO dim_appellation (country_code, region, appellation_name, appellation_norm, level)
  VALUES ('FR', ?, ?, ?, 'village')
`);
const updateWine = db.prepare(`
  UPDATE dim_wine
  SET producer_key = ?, appellation_key = ?,
      cuvee_name = ?, cuvee_norm = ?,
      classification = COALESCE(NULLIF(classification, ''), ?),
      canonical_name = ?
  WHERE producer_key = ?
`);
const deleteProducer = db.prepare('DELETE FROM dim_producer WHERE producer_key = ?');
const countWines = db.prepare('SELECT COUNT(*) AS n FROM dim_wine WHERE producer_key = ?');

// Appellation tier lookup: 1er Cru / Grand Cru appellations need the suffix.
function appellationCanonicalName(head, classification) {
  if (classification === '1er Cru')   return `${head} Premier Cru`;
  if (classification === 'Grand Cru') return `${head} Grand Cru`;
  return head;
}

// Burgundy region inference from appellation head.
const BURGUNDY_HEADS_NUITS = new Set(['Marsannay','Fixin','Gevrey-Chambertin','Morey-Saint-Denis','Chambolle-Musigny','Vougeot','Vosne-Romanée','Vosne-Romanee','Nuits-Saint-Georges']);
const BURGUNDY_HEADS_BEAUNE = new Set(['Beaune','Volnay','Pommard','Meursault','Puligny-Montrachet','Chassagne-Montrachet','Savigny-Les-Beaune','Savigny-lès-Beaune','Aloxe-Corton','Corton','Saint-Aubin','Saint-Romain','Auxey-Duresses','Monthélie','Santenay','Ladoix','Pernand-Vergelesses','Chorey-lès-Beaune']);
const BURGUNDY_HEADS_CHALON = new Set(['Mercurey','Rully','Givry','Montagny']);
const BURGUNDY_HEADS_MACON = new Set(['Pouilly-Fuissé','Saint-Véran']);
function inferRegion(head) {
  if (BURGUNDY_HEADS_NUITS.has(head))   return 'Côte de Nuits';
  if (BURGUNDY_HEADS_BEAUNE.has(head))  return 'Côte de Beaune';
  if (BURGUNDY_HEADS_CHALON.has(head))  return 'Côte Chalonnaise';
  if (BURGUNDY_HEADS_MACON.has(head))   return 'Mâconnais';
  if (head === 'Chablis')               return 'Chablis';
  return null;
}

// ---------- 4. Plan + apply ----------

let parsed = 0, skipped = 0, applied = 0, winesMoved = 0;
const samples = [];
const failures = [];

const tx = db.transaction(() => {
  for (const p of pollutedProducers) {
    const parts = parseRow(p.producer_name);
    if (!parts || !parts.appellation || !parts.producer) { skipped++; failures.push(p.producer_name); continue; }
    parsed++;

    const appName = appellationCanonicalName(parts.appellation, parts.classification);
    const region = inferRegion(parts.appellation);

    // Find or create the appellation.
    const appNorm = normText(appName);
    let app = findAppByName.get(appName) || findAppByNorm.get(appNorm);
    if (!app) {
      if (APPLY) insertApp.run(region || 'Bourgogne', appName, appNorm);
      app = findAppByName.get(appName) || findAppByNorm.get(appNorm);
    }
    if (!app) { failures.push(`no-app:${appName}`); continue; }

    // Find the canonical producer (prefix-expansion against existing rows).
    const pNorm = normText(parts.producer);
    let realProd = findProducer.get(pNorm)
                 || findProducer.get(expandPrefix(pNorm))
                 || findProducer.get(pNorm.replace(/^(chateau|domaine|maison)\s+/, ''));
    if (!realProd) {
      if (APPLY) insertProducer.run(parts.producer, pNorm);
      realProd = findProducer.get(pNorm);
    }
    if (!realProd || realProd.producer_key === p.producer_key) { failures.push(`no-prod:${parts.producer}`); continue; }

    // Build canonical_name from clean components.
    const canonical = [
      realProd.producer_name,
      parts.climat,
      parts.vintage ?? '',
    ].filter(Boolean).join(' ');

    if (APPLY) {
      const moved = updateWine.run(
        realProd.producer_key,
        app.appellation_key,
        parts.climat,
        normText(parts.climat),
        parts.classification,
        canonical,
        p.producer_key,
      ).changes;
      winesMoved += moved;
      if (countWines.get(p.producer_key).n === 0) {
        deleteProducer.run(p.producer_key);
      }
      applied++;
    } else {
      applied++;  // dry-run still increments for stats
    }

    if (samples.length < SAMPLE_LIMIT) {
      samples.push({
        from: p.producer_name,
        producer: realProd.producer_name,
        appellation: app.appellation_name,
        classification: parts.classification ?? '',
        cuvee: parts.climat,
        vintage: parts.vintage ?? '',
        wines: countWines.get(p.producer_key).n,
      });
    }
  }
});

tx();

console.log(`Parsed successfully : ${parsed}`);
console.log(`Skipped (parser couldn't extract appellation+producer) : ${skipped}`);
console.log(`${APPLY ? 'Applied' : 'Would apply'} : ${applied}  ·  wines re-pointed: ${winesMoved}\n`);
console.log(`--- Sample of ${samples.length} ---\n`);
for (const s of samples) {
  console.log(`FROM: "${s.from}"  (${s.wines} wines)`);
  console.log(`  → producer="${s.producer}"  appellation="${s.appellation}"  class="${s.classification}"  cuvée="${s.cuvee}"  vintage=${s.vintage}`);
}
if (failures.length > 0 && !APPLY) {
  console.log(`\nFirst 8 parser failures:`);
  for (const f of failures.slice(0, 8)) console.log(`  ${f}`);
}

if (!APPLY) console.log('\n(Dry-run — re-run with --apply to mutate.)');

db.close();
