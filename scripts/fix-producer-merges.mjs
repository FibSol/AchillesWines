/**
 * fix-producer-merges.mjs
 *
 * Handles Section 5 failures from fix-manual-review-issues.mjs:
 * When renaming a bad producer_name to the correct one fails because the
 * correct producer already exists, we instead:
 * 1. Re-point all dim_wine rows from the bad producer_key to the existing correct one
 * 2. Delete the now-empty bad dim_producer row
 *
 * Run: node scripts/fix-producer-merges.mjs [--dry-run]
 */

import Database from 'better-sqlite3';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dbPath = join(__dirname, '..', 'data', 'achilles.db');
const DRY_RUN = process.argv.includes('--dry-run');

const db = new Database(dbPath);
if (!DRY_RUN) {
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = OFF');
}

let merged = 0;
let deleted = 0;
let errors = 0;

console.log(`\n=== fix-producer-merges.mjs ${DRY_RUN ? '[DRY RUN]' : '[LIVE]'} ===\n`);

// For each bad producer_key, attempt:
//   1. Update producer_name (simple rename) — if it fails due to UNIQUE…
//   2. Find the existing producer with that norm+country, re-point wines, delete bad row
const MERGES = [
  { badKey: 31536, targetNorm: 'chateau mont redon',         targetName: 'Château Mont-Redon' },
  { badKey: 31787, targetNorm: 'domaine bachey legros',       targetName: 'Domaine Bachey-Legros' },
  { badKey: 32714, targetNorm: 'brochet',                     targetName: 'Brochet' },
  { badKey: 33250, targetNorm: 'brochet',                     targetName: 'Brochet' },
  { badKey: 33255, targetNorm: 'ampelidae',                   targetName: 'Ampelidae' },
  { badKey: 33753, targetNorm: 'langlois chateau',            targetName: 'Langlois-Château' },
  { badKey: 34071, targetNorm: 'ampelidae',                   targetName: 'Ampelidae' },
  { badKey: 33801, targetNorm: 'chateau clarke',              targetName: 'Château Clarke' },
  { badKey: 32069, targetNorm: 'joseph perrier',              targetName: 'Joseph Perrier' },
  { badKey: 32102, targetNorm: '1890',                        targetName: '1890' },
  { badKey: 32138, targetNorm: 'champagne pannier',           targetName: 'Champagne Pannier' },
  { badKey: 32154, targetNorm: 'champagne pannier',           targetName: 'Champagne Pannier' },
  { badKey: 32423, targetNorm: 'joseph perrier',              targetName: 'Joseph Perrier' },
  { badKey: 32715, targetNorm: 'baron philippe de rothschild',targetName: 'Baron Philippe de Rothschild' },
  { badKey: 32768, targetNorm: 'aix',                         targetName: 'AIX' },
  { badKey: 32862, targetNorm: 'poyet',                       targetName: 'Poyet' },
  { badKey: 33552, targetNorm: 'louis jadot',                 targetName: 'Louis Jadot' },
  { badKey: 33572, targetNorm: 'louis jadot',                 targetName: 'Louis Jadot' },
  { badKey: 33597, targetNorm: 'louis jadot',                 targetName: 'Louis Jadot' },
  { badKey: 33944, targetNorm: 'champagne ayala',             targetName: 'Champagne Ayala' },
  { badKey: 34300, targetNorm: 'champagne bollinger',         targetName: 'Champagne Bollinger' },
  { badKey: 34380, targetNorm: 'baron philippe de rothschild',targetName: 'Baron Philippe de Rothschild' },
  { badKey: 34389, targetNorm: 'champagne bollinger',         targetName: 'Champagne Bollinger' },
  { badKey: 34390, targetNorm: 'champagne bollinger',         targetName: 'Champagne Bollinger' },
  { badKey: 34400, targetNorm: 'champagne deutz',             targetName: 'Champagne Deutz' },
  { badKey: 35403, targetNorm: 'moet chandon',                targetName: 'Moët & Chandon' },
  { badKey: 35600, targetNorm: 'chateau troplong mondot',     targetName: 'Château Troplong Mondot' },
  { badKey: 40693, targetNorm: 'domaine raymond usseglio',    targetName: 'Domaine Raymond Usseglio' },
];

for (const { badKey, targetNorm, targetName } of MERGES) {
  // First check if the bad key still exists
  const badRow = db.prepare('SELECT producer_key, producer_name FROM dim_producer WHERE producer_key = ?').get(badKey);
  if (!badRow) {
    console.log(`producer_key=${badKey}: already deleted, skipping`);
    continue;
  }

  // Try to find existing correct producer (same norm + country=FR)
  const existing = db.prepare(
    "SELECT producer_key, producer_name FROM dim_producer WHERE producer_norm = ? AND country_code = 'FR'"
  ).get(targetNorm);

  if (existing && existing.producer_key === badKey) {
    console.log(`producer_key=${badKey} ("${badRow.producer_name}") already has correct name — skipping`);
    continue;
  }

  if (!existing) {
    // No duplicate — just rename
    if (DRY_RUN) {
      console.log(`[DRY] RENAME producer_key=${badKey} → "${targetName}"`);
    } else {
      try {
        db.prepare('UPDATE dim_producer SET producer_name = ?, producer_norm = ? WHERE producer_key = ?')
          .run(targetName, targetNorm, badKey);
        console.log(`Renamed producer_key=${badKey}: "${badRow.producer_name}" → "${targetName}"`);
        merged++;
      } catch (e) {
        console.error(`ERROR renaming ${badKey}: ${e.message}`);
        errors++;
      }
    }
  } else {
    // Existing correct producer found — merge
    const wineCount = db.prepare('SELECT COUNT(*) as c FROM dim_wine WHERE producer_key = ?').get(badKey).c;
    if (DRY_RUN) {
      console.log(`[DRY] MERGE producer_key=${badKey} ("${badRow.producer_name}") → ${existing.producer_key} ("${existing.producer_name}"), re-pointing ${wineCount} wines`);
    } else {
      // Re-point all wines from bad producer to existing correct one
      const r = db.prepare('UPDATE dim_wine SET producer_key = ? WHERE producer_key = ?')
        .run(existing.producer_key, badKey);
      // Also re-point any fact_price / fact_rating rows that might reference by producer_key
      // (if those tables have a producer_key column)
      // Delete the bad producer row
      db.prepare('DELETE FROM dim_producer WHERE producer_key = ?').run(badKey);
      console.log(`Merged producer_key=${badKey} ("${badRow.producer_name}") → ${existing.producer_key} ("${existing.producer_name}"), re-pointed ${r.changes} wines`);
      merged++;
      deleted++;
    }
  }
}

// Fix Taylor's apostrophe issue (couldn't use JS escape in SET clause)
const taylorsKey = 'ca67b5cd0e734cdd';
const taylorsRow = db.prepare("SELECT wine_key, cuvee_name FROM dim_wine WHERE wine_key = ?").get(taylorsKey);
if (taylorsRow) {
  if (DRY_RUN) {
    console.log(`[DRY] Fix Taylor's cuvee_name: "${taylorsRow.cuvee_name}" → "Taylor's 10 Ans"`);
  } else {
    db.prepare("UPDATE dim_wine SET cuvee_name = ?, cuvee_norm = ? WHERE wine_key = ?")
      .run("Taylor's 10 Ans", "taylors 10 ans", taylorsKey);
    console.log(`Fixed Taylor's Porto cuvée name`);
    merged++;
  }
}

console.log(`\n=== SUMMARY ===`);
console.log(`Merged/renamed: ${merged}`);
console.log(`Deleted:        ${deleted}`);
console.log(`Errors:         ${errors}`);
if (DRY_RUN) console.log('\n[DRY RUN — no changes committed]');

db.close();
