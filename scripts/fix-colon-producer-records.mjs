#!/usr/bin/env node
/**
 * Fix producer names that embed full wine specs (colon format or pipe format).
 *
 * Patterns:
 *   "Larmandier-Bernier : Les Chemins d'Avize Grand Cru Extra Brut" → producer="Larmandier-Bernier"
 *   "Saint-Aubin 1er Cru Rouge 'Sur le Sentier du Clou' | Wijnpakket" → producer="Saint-Aubin..."
 *   "Pol Roger : Coffret Brut Réserve & 2 Flûtes" → producer="Pol Roger"
 *   "VOSNE-ROMANEE 1er CRU LES CHAUMES JADOT" → skip (no clean producer name available)
 *
 * Strategy:
 *   1. Find all dim_producer rows where producer_name LIKE '% : %' or '% | %'
 *   2. Extract the "clean" producer name (text before the separator)
 *   3. Try to find a canonical producer with that name (case-insensitive, accent-normalized)
 *   4. If found: re-point all dim_wine.producer_key → canonical producer, delete polluted row
 *   5. If not found: create new dim_producer with cleaned name and update wines
 *   6. Dry-run by default; --apply to mutate
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

// Find all producers with colon or pipe separators
const pollutedProducers = db.prepare(`
  SELECT producer_key, producer_name, country_code, region
  FROM dim_producer
  WHERE producer_name LIKE '% : %' OR producer_name LIKE '% | %'
`).all();

console.log(`Found ${pollutedProducers.length} polluted producer names\n`);

const plan = [];

for (const polluted of pollutedProducers) {
  const pn = polluted.producer_name;
  let cleanName = '';

  // Determine separator and extract clean name
  if (pn.includes(' : ')) {
    cleanName = pn.split(' : ')[0].trim();
  } else if (pn.includes(' | ')) {
    cleanName = pn.split(' | ')[0].trim();
  }

  // Safety: skip if clean name is too short or empty
  if (!cleanName || cleanName.length < 3) {
    console.log(`  ⊘ [${polluted.producer_key}] "${pn}" → too short after cleaning`);
    continue;
  }

  // Try to find a canonical producer with the clean name (normalized match)
  const cleanNorm = normText(cleanName);
  const allOtherProducers = db.prepare(`
    SELECT producer_key, producer_name
    FROM dim_producer
    WHERE producer_key <> ?
  `).all(polluted.producer_key);

  let canonical = null;
  for (const other of allOtherProducers) {
    if (normText(other.producer_name) === cleanNorm) {
      canonical = other;
      break;
    }
  }

  // Count wines pointing to this polluted producer
  const wineCount = db.prepare(`
    SELECT COUNT(*) as cnt FROM dim_wine WHERE producer_key = ?
  `).get(polluted.producer_key).cnt;

  if (canonical) {
    // Merge into canonical producer
    plan.push({
      action: 'merge',
      pollutedKey: polluted.producer_key,
      pollutedName: pn,
      cleanName,
      canonicalKey: canonical.producer_key,
      canonicalName: canonical.producer_name,
      wineCount,
    });
  } else {
    // Rename the polluted producer to the clean name
    plan.push({
      action: 'rename',
      pollutedKey: polluted.producer_key,
      pollutedName: pn,
      cleanName,
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
