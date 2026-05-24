#!/usr/bin/env node
/**
 * Fix dim_producer rows where the name embeds a full wine spec in colon or
 * pipe format AND the audit flags them as producer_classification_tail:
 *
 *   "Château Fuissé : Pouilly-Fuissé 1er cru "Le Clos" Monopole"  → "Château Fuissé"
 *   "Larmandier-Bernier : Les Chemins d'Avize Grand Cru Extra Brut" → "Larmandier-Bernier"
 *   "Pol Roger : Coffret Brut Réserve & 2 Flûtes Lehmann Absolus"  → "Pol Roger"
 *   "Saint-Aubin 1er Cru Rouge ... | Wijnpakket"                    → skip (wine name before pipe)
 *
 * For colon format: producer = text before first " : ".
 * For pipe format: skip (the part before " | " is the wine name, not the producer).
 *
 * Strategy:
 *   1. Query dim_producer rows that have CLASSIFICATION_RE match AND colon format
 *   2. Extract producer name from before " : "
 *   3. Build a normalized lookup map of ALL producers (one pass, avoids O(n²))
 *   4. If canonical found: re-point wines, delete polluted row
 *   5. If not found: create new producer row, re-point wines, delete polluted row
 *   6. Also handles Champagne packaging rows (coffret format same colon pattern)
 *
 * Dry-run by default; pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

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

const CLASSIFICATION_RE = /\b(grand\s+cru(\s+class[ée])?|1\s*er\s+cru(\s+class[ée])?|premier\s+grand\s+cru|cru\s+bourgeois|cru\s+artisan|cru\s+class[ée]|premier\s+cru)\b/i;

// Build a single normalized lookup map for all producers (one DB read, O(1) per lookup)
const allProducers = db.prepare('SELECT producer_key, producer_name, country_code FROM dim_producer').all();
// Map: normalizedName → producer row (prefer lower key = older record)
const normMap = new Map();
const prefixMap = new Map();
for (const p of allProducers) {
  const n = normText(p.producer_name);
  const exp = expandPrefix(n);
  if (!normMap.has(n) || p.producer_key < normMap.get(n).producer_key) normMap.set(n, p);
  if (!prefixMap.has(exp) || p.producer_key < prefixMap.get(exp).producer_key) prefixMap.set(exp, p);
}

function findCanonical(name, excludeKey) {
  const n = normText(name);
  const exp = expandPrefix(n);
  const stripped = exp.replace(/^(chateau|domaine|maison|bodega|tenuta|cantina|weingut|quinta|casa)\s+/, '');
  let found = normMap.get(n) || normMap.get(exp) || prefixMap.get(exp) || normMap.get(stripped) || prefixMap.get(stripped);
  if (found && found.producer_key === excludeKey) found = null;
  return found || null;
}

// Find target producers: colon format + classification in name
const targetProducers = allProducers.filter(p => {
  if (!p.producer_name.includes(' : ')) return false;
  if (!CLASSIFICATION_RE.test(p.producer_name)) return false;
  return true;
});

// Also find packaging (coffret) colon format rows
const packagingProducers = allProducers.filter(p => {
  if (!p.producer_name.includes(' : ')) return false;
  if (!/\b(coffret|en\s+coffret|gift\s+set)\b/i.test(p.producer_name)) return false;
  return true;
});

const combined = [...new Map([...targetProducers, ...packagingProducers].map(p => [p.producer_key, p])).values()];
console.log(`Colon-format classification/packaging producers: ${combined.length}\n`);

const plan = [];

for (const prod of combined) {
  const pn = prod.producer_name;
  const colonIdx = pn.indexOf(' : ');
  if (colonIdx < 0) continue;

  const cleanName = pn.slice(0, colonIdx).trim();
  if (!cleanName || cleanName.length < 3) {
    console.log(`  ⊘ [${prod.producer_key}] "${pn}" → extracted name too short`);
    continue;
  }

  const wineCount = db.prepare('SELECT COUNT(*) as cnt FROM dim_wine WHERE producer_key = ?').get(prod.producer_key).cnt;
  const canonical = findCanonical(cleanName, prod.producer_key);

  plan.push({
    pollutedKey: prod.producer_key,
    pollutedName: pn,
    cleanName,
    canonical,
    wineCount,
  });
}

console.log(`Planned: ${plan.length} actions\n`);
plan.slice(0, 20).forEach((p, i) => {
  if (p.canonical) {
    console.log(`  [${i}] MERGE: "${p.pollutedName}" (${p.wineCount} wines) → into "${p.canonical.producer_name}"`);
  } else {
    console.log(`  [${i}] RENAME: "${p.pollutedName}" (${p.wineCount} wines) → to "${p.cleanName}"`);
  }
});

if (APPLY) {
  const insertProducer = db.prepare(`
    INSERT OR IGNORE INTO dim_producer (producer_name, producer_norm, country_code, allowed_appellations, aliases, status)
    VALUES (?, ?, ?, '[]', '[]', 'pending_review')
  `);
  const updateWines = db.prepare('UPDATE dim_wine SET producer_key = ? WHERE producer_key = ?');
  const deleteProducer = db.prepare('DELETE FROM dim_producer WHERE producer_key = ?');
  const renameProducer = db.prepare('UPDATE dim_producer SET producer_name = ?, producer_norm = ? WHERE producer_key = ?');

  let merges = 0, renames = 0, creates = 0;

  const tx = db.transaction(() => {
    for (const p of plan) {
      if (p.canonical) {
        // Merge: re-point wines, delete polluted
        updateWines.run(p.canonical.producer_key, p.pollutedKey);
        deleteProducer.run(p.pollutedKey);
        merges++;
      } else {
        // If cleanName already exists in DB (from a previous iteration in this tx), rename
        // Otherwise try rename first; if norm collision, insert new then repoint
        try {
          renameProducer.run(p.cleanName, normText(p.cleanName), p.pollutedKey);
          renames++;
        } catch (e) {
          if (e.code === 'SQLITE_CONSTRAINT_UNIQUE') {
            // Another producer with same norm already exists — find it and merge
            const existing = normMap.get(normText(p.cleanName));
            if (existing && existing.producer_key !== p.pollutedKey) {
              updateWines.run(existing.producer_key, p.pollutedKey);
              deleteProducer.run(p.pollutedKey);
              merges++;
            }
          } else { throw e; }
        }
      }
    }
  });

  tx();
  console.log(`\nApplied: ${merges} merges + ${renames} renames + ${creates} creates`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
