#!/usr/bin/env node
/**
 * Bordeaux appellation cleanup informed by the École du Vin de Bordeaux guide
 * (see docs/BORDEAUX-VALIDATION.md). Three operations:
 *
 *   A. Merge duplicate appellation rows that represent the same legal AOC
 *      (Listrac / Listrac-Médoc, Moulis / Moulis En Medoc, etc.).
 *   B. Re-point all wines from "Saint-Emilion Grand Cru Classé" — which is a
 *      CLASSIFICATION, not an AOC — to "Saint-Émilion Grand Cru" (the real
 *      appellation), then promote each affected wine's classification to
 *      "Grand Cru Classé" when blank (manual review for the few Premier Grand
 *      Cru Classé A/B cases is preserved).
 *   C. Upgrade dim_appellation.level from "regional" to "village" for the
 *      official commune-level Bordeaux AOCs.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// ---------- A. Appellation merges ----------

const APPELLATION_MERGES = [
  // [survivor canonical name, [list of dupe names to merge into it]]
  ['Listrac-Médoc',            ['Listrac']],
  ['Moulis-en-Médoc',          ['Moulis', 'Moulis En Medoc']],
  ['Puisseguin-Saint-Émilion', ['Puisseguin St Emilion', 'Puisseguin-Saint-Emilion']],
  ['Francs Côtes de Bordeaux', ['Bordeaux Côtes de Francs', 'Côtes de Bordeaux Francs']],
  ['Cadillac Côtes de Bordeaux', ['Premieres Côtes de Bordeaux']],
  ['Saint-Estèphe',            []], // already canonical, just here for clarity
  ['Cérons',                   ['Cerons']],
  ['Sainte-Croix-du-Mont',     ['Sainte Croix Du Mont']],
  ['Crémant de Bordeaux',      ['Cremant De Bordeaux']],
  ['Montagne-Saint-Émilion',   ['Montagne-Saint-Emilion']],
  ['Saint-Georges-Saint-Émilion', ['Saint-Georges-Saint-Emilion']],
  ['Lussac-Saint-Émilion',     ['Lussac Saint-Emilion']],
  ['Saint-Émilion',            ['Saint-Emilion']],
  ['Saint-Émilion Grand Cru',  ['Saint-Emilion Grand Cru']],
];

// ---------- C. Commune-level upgrades ----------

const COMMUNAL_AOCS = [
  // Médoc
  'Margaux', 'Pauillac', 'Saint-Julien', 'Saint-Estèphe',
  'Listrac-Médoc', 'Moulis-en-Médoc',
  // Graves
  'Pessac-Léognan',
  // Saint-Émilion + satellites
  'Saint-Émilion', 'Saint-Émilion Grand Cru',
  'Montagne-Saint-Émilion', 'Saint-Georges-Saint-Émilion',
  'Lussac-Saint-Émilion', 'Puisseguin-Saint-Émilion',
  // Pomerol
  'Pomerol', 'Lalande de Pomerol',
  // Fronsac
  'Fronsac', 'Canon-Fronsac',
  // Sauternes / sweet
  'Sauternes', 'Barsac', 'Cérons', 'Cadillac Côtes de Bordeaux',
  'Loupiac', 'Sainte-Croix-du-Mont',
];

// ---------- prepare statements ----------

const findApp = db.prepare("SELECT * FROM dim_appellation WHERE appellation_name = ? AND country_code = 'FR'");
const findAppByNorm = db.prepare("SELECT * FROM dim_appellation WHERE appellation_norm = ? AND country_code = 'FR'");
const insertApp = db.prepare(`
  INSERT INTO dim_appellation (country_code, region, appellation_name, appellation_norm, level)
  VALUES ('FR', ?, ?, ?, ?)
`);
const repointWines = db.prepare('UPDATE dim_wine SET appellation_key = ? WHERE appellation_key = ?');
const deleteApp = db.prepare('DELETE FROM dim_appellation WHERE appellation_key = ?');
const updateLevel = db.prepare('UPDATE dim_appellation SET level = ? WHERE appellation_key = ?');
const updateClassification = db.prepare(`
  UPDATE dim_wine
  SET classification = COALESCE(NULLIF(classification, ''), ?),
      appellation_key = ?
  WHERE appellation_key = ?
`);

function normText(s) {
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

// ---------- plan ----------

let mergedAppellations = 0;
let winesRepointed = 0;
let levelsUpgraded = 0;
let saintEmilionGCCRepointed = 0;
let saintEmilionGCCClassified = 0;

const samples = { merges: [], gcc: [], levels: [] };

function ensureSurvivor(name, sourceForRegion) {
  let row = findApp.get(name);
  if (!row) {
    // If a normalized match exists with different casing, use it.
    row = findAppByNorm.get(normText(name));
  }
  if (row) return row;
  if (!APPLY) {
    // Synthesize a placeholder so the dry-run logic can still flow.
    return { appellation_key: -1, appellation_name: name, appellation_norm: normText(name), level: 'regional' };
  }
  const info = insertApp.run(sourceForRegion.region || 'Bordeaux', name, normText(name), 'regional');
  return findApp.get(name);
}

const tx = db.transaction(() => {
  // ----- A. Appellation merges -----
  for (const [survivorName, dupeNames] of APPELLATION_MERGES) {
    if (dupeNames.length === 0) continue;
    let survivor = findApp.get(survivorName);
    if (!survivor) {
      // Pick first existing dupe to keep its region/level and rename to canonical.
      for (const dn of dupeNames) {
        const candidate = findApp.get(dn);
        if (candidate) {
          if (APPLY) {
            // Check if another row already holds the target norm — if so, that row
            // is the real survivor; merge this candidate INTO it instead of renaming.
            const targetNorm = normText(survivorName);
            const collision = findAppByNorm.get(targetNorm);
            if (collision && collision.appellation_key !== candidate.appellation_key) {
              repointWines.run(collision.appellation_key, candidate.appellation_key);
              deleteApp.run(candidate.appellation_key);
              survivor = collision;
            } else {
              db.prepare('UPDATE dim_appellation SET appellation_name = ?, appellation_norm = ? WHERE appellation_key = ?')
                .run(survivorName, targetNorm, candidate.appellation_key);
              survivor = findApp.get(survivorName);
            }
          } else {
            survivor = { ...candidate, appellation_name: survivorName, appellation_norm: normText(survivorName) };
          }
          break;
        }
      }
      if (!survivor) continue;
    }
    for (const dn of dupeNames) {
      if (dn === survivorName) continue;
      const dupe = findApp.get(dn);
      if (!dupe || dupe.appellation_key === survivor.appellation_key) continue;
      const moved = APPLY ? repointWines.run(survivor.appellation_key, dupe.appellation_key).changes : 0;
      winesRepointed += moved;
      if (APPLY) deleteApp.run(dupe.appellation_key);
      mergedAppellations++;
      if (samples.merges.length < 10) {
        samples.merges.push(`"${dn}" → "${survivorName}" (${moved} wines)`);
      }
    }
  }

  // ----- B. Saint-Émilion Grand Cru Classé split -----
  const gccApp = findApp.get('Saint-Emilion Grand Cru Classé') || findApp.get('Saint-Émilion Grand Cru Classé');
  const gcuApp = findApp.get('Saint-Émilion Grand Cru') || findApp.get('Saint-Emilion Grand Cru');
  if (gccApp && gcuApp) {
    // Re-point wines: appellation → Saint-Émilion Grand Cru, classification → "Grand Cru Classé" when empty.
    const winesToFix = db.prepare("SELECT wine_key, classification FROM dim_wine WHERE appellation_key = ?").all(gccApp.appellation_key);
    for (const w of winesToFix) {
      if (APPLY) {
        updateClassification.run('Grand Cru Classé', gcuApp.appellation_key, gccApp.appellation_key);
      }
      saintEmilionGCCRepointed++;
      if (!w.classification) saintEmilionGCCClassified++;
      if (samples.gcc.length < 5) {
        samples.gcc.push(`wine_key=${w.wine_key} class="${w.classification ?? ''}" → "Grand Cru Classé"`);
      }
    }
    if (APPLY) deleteApp.run(gccApp.appellation_key);
  }

  // ----- C. Commune-level upgrades -----
  for (const name of COMMUNAL_AOCS) {
    const row = findApp.get(name);
    if (!row) continue;
    if (row.level === 'village') continue;
    if (APPLY) updateLevel.run('village', row.appellation_key);
    levelsUpgraded++;
    if (samples.levels.length < 12) {
      samples.levels.push(`"${name}" : ${row.level} → village`);
    }
  }
});

if (APPLY) tx(); else tx(); // run in dry-run mode too to populate counts/samples

console.log('=== Bordeaux appellation cleanup ===\n');
console.log(`A. Appellation merges          : ${mergedAppellations} dupe rows  →  ${winesRepointed} wines re-pointed`);
for (const s of samples.merges) console.log(`     ${s}`);
console.log(`\nB. Saint-Émilion GCC split     : ${saintEmilionGCCRepointed} wines moved to Saint-Émilion Grand Cru, ${saintEmilionGCCClassified} got classification="Grand Cru Classé"`);
for (const s of samples.gcc) console.log(`     ${s}`);
console.log(`\nC. Commune-level upgrades      : ${levelsUpgraded} appellations promoted to level=village`);
for (const s of samples.levels) console.log(`     ${s}`);

if (!APPLY) {
  // We ran the tx but no writes — better-sqlite3 transactions outside an APPLY
  // block above didn't actually mutate because every write was guarded by APPLY.
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
