#!/usr/bin/env node
/**
 * Fix all-caps Belgian importer producer names that embed vintage, shop codes, and appellations.
 *
 * Examples:
 *   "SALES 2019 (CB6) POMEROL" → "SALES"
 *   "FONBEL 2020 C12 ST-EMILION" → "FONBEL"
 *   "CITRAN 2021 (C6) HAUT-MEDOC" → "CITRAN"
 *   "LAGRANGE 2019 (CB6) ST-JULIEN MAGNUM" → "LAGRANGE"
 *
 * Strategy:
 *   1. Find all dim_producer where:
 *      - producer_name is mostly uppercase
 *      - contains a vintage year (19XX or 20XX)
 *      - contains a shop code pattern (CB\d+, C\d{1,2}, etc.)
 *   2. Strip: vintage, shop code, appellation tail, color/size words
 *   3. If result >= 3 chars:
 *      - Try to find canonical producer (normalized match)
 *      - If found: merge all wines into canonical, delete polluted row
 *      - If not found: rename the producer to cleaned form
 *   4. Dry-run by default; --apply to mutate
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

function isAllCaps(s) {
  // Check if a string is mostly uppercase (>80% uppercase letters)
  const letters = s.match(/[a-z]/gi) || [];
  const upper = s.match(/[A-Z]/g) || [];
  if (letters.length === 0) return false;
  return upper.length / letters.length > 0.8;
}

// All-caps appellation words to strip.
// IMPORTANT: listed longest-first so that compound names (HAUT-MEDOC, LISTRAC-MEDOC)
// are matched and removed before their component words (MEDOC) are processed.
const APPELLATION_WORDS = [
  'SAINT-EMILION GRAND CRU CLASSE', 'SAINT-EMILION GRAND CRU',
  'MONTAGNE-SAINT-EMILION', 'LUSSAC-SAINT-EMILION',
  'PESSAC-LEOGNAN', 'MOULIS-EN-MEDOC',
  'HAUT-MEDOC', 'LISTRAC-MEDOC',
  'SAINT-EMILION', 'SAINT-JULIEN', 'SAINT-ESTEPHE',
  'ST-EMILION', 'ST EMILION', 'ST-JULIEN', 'ST JULIEN', 'ST-ESTEPHE', 'ST ESTEPHE',
  'PAUILLAC', 'MARGAUX', 'SAUTERNES', 'POMEROL', 'FRONSAC',
  'MOULIS', 'LISTRAC', 'GRAVES', 'CHABLIS', 'CHAMPAGNE',
  'HAUT MEDOC', 'MEDOC',
];

// Find all producers and filter in JS (better-sqlite3 doesn't support REGEXP)
const allProducers = db.prepare(`
  SELECT producer_key, producer_name, country_code, region
  FROM dim_producer
`).all();

const vintageRe = /\b(19|20)\d{2}\b/;
const shopCodeRe = /\(CB\d+\)|\bCB\d+\b|\bC\d{1,2}\b/i;

const candidates = allProducers.filter(p =>
  vintageRe.test(p.producer_name) && shopCodeRe.test(p.producer_name)
);

console.log(`Found ${candidates.length} potential all-caps Belgian importers\n`);

const plan = [];

for (const cand of candidates) {
  const pn = cand.producer_name;

  // Confirm it's all-caps
  if (!isAllCaps(pn)) continue;

  // Strip vintage year
  let cleaned = pn.replace(/\b(19|20)\d{2}\b/g, '').trim();

  // Strip shop code (CB6, (CB6), C6, (C6), etc.) — handle parens first so we
  // don't leave empty "()" behind when we strip just the inner code
  cleaned = cleaned.replace(/\(\s*CB\d+\s*\)/g, '').trim();   // (CB6)
  cleaned = cleaned.replace(/\(\s*C\d{1,2}\s*\)/g, '').trim(); // (C6)
  cleaned = cleaned.replace(/\bCB\d+\b/g, '').trim();
  cleaned = cleaned.replace(/\bC\d{1,2}\b/g, '').trim();
  // Clean up any leftover empty parens
  cleaned = cleaned.replace(/\(\s*\)/g, '').trim();

  // Strip appellation words
  for (const app of APPELLATION_WORDS) {
    const re = new RegExp(`\\b${app.replace(/[-]/g, '[-\\s]')}\\b`, 'gi');
    cleaned = cleaned.replace(re, '').trim();
  }

  // Strip color/size words and abbreviations used by Belgian importers
  cleaned = cleaned.replace(/\b(ROUGE|BLANC|ROSE|ROSÉ|MAGNUM|JEROBOAM|MATHUSALEM|SALMANAZAR|BALTHAZAR|NABUCHODONOSOR|IMPERIALE)\b/g, '').trim();
  // Strip trailing bare "CH" abbreviation (artifact of "CH MARGAUX" after MARGAUX strip)
  cleaned = cleaned.replace(/\s+CH\s*$/, '').trim();

  // Collapse multiple spaces
  cleaned = cleaned.replace(/\s+/g, ' ').trim();

  // Skip if too short after cleaning
  if (cleaned.length < 3) {
    console.log(`  ⊘ [${cand.producer_key}] "${pn}" → too short after cleaning`);
    continue;
  }

  // Count wines
  const wineCount = db.prepare(`
    SELECT COUNT(*) as cnt FROM dim_wine WHERE producer_key = ?
  `).get(cand.producer_key).cnt;

  // Try to find canonical producer
  const cleanNorm = normText(cleaned);
  const allOtherProducers = db.prepare(`
    SELECT producer_key, producer_name
    FROM dim_producer
    WHERE producer_key <> ?
  `).all(cand.producer_key);

  let canonical = null;
  for (const other of allOtherProducers) {
    if (normText(other.producer_name) === cleanNorm) {
      canonical = other;
      break;
    }
  }

  if (canonical) {
    plan.push({
      action: 'merge',
      pollutedKey: cand.producer_key,
      pollutedName: pn,
      cleanName: cleaned,
      canonicalKey: canonical.producer_key,
      canonicalName: canonical.producer_name,
      wineCount,
    });
  } else {
    plan.push({
      action: 'rename',
      pollutedKey: cand.producer_key,
      pollutedName: pn,
      cleanName: cleaned,
      wineCount,
    });
  }
}

console.log(`Planned: ${plan.length} actions\n`);
plan.slice(0, 15).forEach((p, i) => {
  if (p.action === 'merge') {
    console.log(`  [${i}] MERGE: "${p.pollutedName}" (${p.wineCount} wines)`);
    console.log(`       → into "${p.canonicalName}"`);
  } else {
    console.log(`  [${i}] RENAME: "${p.pollutedName}" (${p.wineCount} wines)`);
    console.log(`       → to "${p.cleanName}"`);
  }
});

if (APPLY) {
  const updateWineProducerKey = db.prepare(`UPDATE dim_wine SET producer_key = ? WHERE producer_key = ?`);
  const deleteProducer = db.prepare(`DELETE FROM dim_producer WHERE producer_key = ?`);
  const renameProducer = db.prepare(`UPDATE dim_producer SET producer_name = ? WHERE producer_key = ?`);

  const tx = db.transaction(() => {
    let mergeCount = 0, renameCount = 0;
    for (const p of plan) {
      if (p.action === 'merge') {
        // Re-point all wines to the canonical producer
        updateWineProducerKey.run(p.canonicalKey, p.pollutedKey);
        // Delete the polluted producer
        deleteProducer.run(p.pollutedKey);
        mergeCount++;
      } else if (p.action === 'rename') {
        // Rename the producer to the clean name
        renameProducer.run(p.cleanName, p.pollutedKey);
        renameCount++;
      }
    }
    console.log(`\nApplied: ${mergeCount} merges + ${renameCount} renames`);
  });

  tx();
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
