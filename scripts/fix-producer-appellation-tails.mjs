#!/usr/bin/env node
/**
 * Fix producer names ending in " - Appellation" or appellation tails.
 *
 * Examples (from CSV):
 *   "Château Bel Air - Saint-Estèphe" → "Château Bel Air"
 *   "Château Gaillard - Saint-Emilion" → "Château Gaillard"
 *   "BARBE BLANCHE LUSSAC-SAINT-EMILION" → "BARBE BLANCHE"
 *   "Château L'Ermitage - Listrac-Médoc" → "Château L'Ermitage"
 *
 * These 8 producer rows are in the manual-review.csv with category "producer_appellation_tail".
 * We target them by their producer_key from the CSV and strip the appellation suffix.
 *
 * Strategy:
 *   1. Hard-code the 8 producer_keys from the CSV
 *   2. For each, strip the appellation tail (dash-separated or compound name)
 *   3. Try to find a canonical producer with the cleaned name
 *   4. If found: merge all wines, delete polluted row
 *   5. If not found: rename the producer to cleaned form
 *   6. Dry-run by default; --apply to mutate
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

// The 8 producer keys from the CSV (producer_appellation_tail category)
const TARGET_KEYS = [
  1323,   // Château Bel Air - Saint-Estèphe
  3783,   // Château Gaillard - Saint-Emilion
  4768,   // Château L'Ermitage - Listrac-Médoc
  5095,   // Château Lalande - Listrac-Médoc
  5522,   // Château Lestage - Listrac-Médoc
  6292,   // Château du Moulin - Fronsac
  31626,  // BARBE BLANCHE LUSSAC-SAINT-EMILION
];

// Common appellation patterns to strip.
// IMPORTANT: more-specific (compound) patterns must come BEFORE the generic
// " - Appellation" pattern, otherwise the generic one partially matches
// word-internal hyphens in compound names like "LUSSAC-SAINT-EMILION".
const APPELLATION_PATTERNS = [
  // Compound appellations first (all-caps + space before compound name)
  /\s+LUSSAC[- ]?SAINT[- ]?EMILION\s*$/i,
  /\s+LALANDE[- ]?DE[- ]?POMEROL\s*$/i,
  /\s+MOULIS[- ]?EN[- ]?MEDOC\s*$/i,
  /\s+LISTRAC[- ]?MEDOC\s*$/i,
  /\s+HAUT[- ]?MEDOC\s*$/i,
  /\s+PESSAC[- ]?LEOGNAN\s*$/i,
  /\s+SAINT[- ]?EMILION\s*$/i,
  /\s+SAINT[- ]?ESTEPHE\s*$/i,
  /\s+SAINT[- ]?JULIEN\s*$/i,
  // Generic " - Appellation" dash-separator pattern (require space before dash to
  // avoid matching word-internal hyphens)
  /\s+[-–—]\s*(Saint[- ]?Émilion|Saint[- ]?Emilion|Montagne[- ]Saint[- ]?Émilion|Montagne[- ]Saint[- ]?Emilion|Saint[- ]?Estèphe|Saint[- ]?Estephe|Saint[- ]?Julien|Pauillac|Margaux|Graves|Sauternes|Pomerol|Fronsac|Moulis|Listrac|Listrac[- ]?Médoc|Listrac[- ]?Medoc|Pessac[- ]?Léognan|Pessac[- ]?Leognan|Chablis|Champagne|Médoc|Medoc|Haut[- ]?Médoc|Haut[- ]?Medoc)\s*$/i,
];

const producers = db.prepare(`
  SELECT producer_key, producer_name, country_code, region
  FROM dim_producer
  WHERE producer_key IN (${TARGET_KEYS.join(',')})
`).all();

console.log(`Found ${producers.length} producer(s) to fix\n`);

const plan = [];

for (const prod of producers) {
  const pn = prod.producer_name;
  let cleanName = pn;

  // Try each appellation pattern
  for (const pattern of APPELLATION_PATTERNS) {
    if (pattern.test(cleanName)) {
      cleanName = cleanName.replace(pattern, '').trim();
      break;
    }
  }

  // Safety: skip if cleaning didn't change the name or left too short
  if (cleanName === pn || cleanName.length < 3) {
    console.log(`  ⊘ [${prod.producer_key}] "${pn}" → no change or too short`);
    continue;
  }

  // Count wines
  const wineCount = db.prepare(`
    SELECT COUNT(*) as cnt FROM dim_wine WHERE producer_key = ?
  `).get(prod.producer_key).cnt;

  // Try to find canonical producer
  const cleanNorm = normText(cleanName);
  const allOtherProducers = db.prepare(`
    SELECT producer_key, producer_name
    FROM dim_producer
    WHERE producer_key <> ?
  `).all(prod.producer_key);

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
      pollutedKey: prod.producer_key,
      pollutedName: pn,
      cleanName,
      canonicalKey: canonical.producer_key,
      canonicalName: canonical.producer_name,
      wineCount,
    });
  } else {
    plan.push({
      action: 'rename',
      pollutedKey: prod.producer_key,
      pollutedName: pn,
      cleanName,
      wineCount,
    });
  }
}

console.log(`Planned: ${plan.length} actions\n`);
plan.forEach((p, i) => {
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
