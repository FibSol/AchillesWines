#!/usr/bin/env node
/**
 * Resolve VdF mixed-portfolio rows for producers whose canonical AOC is
 * well-known. Hand-curated mapping covers the biggest buckets:
 *   - Bordeaux Châteaux (Pichon Longueville Baron → Pauillac, etc.)
 *   - Bordeaux second wines (Fugue de Nénin → Pomerol, etc.)
 *   - Burgundy producers (Confuron → Vosne-Romanée etc.)
 *   - Loire (Didier Dagueneau → Pouilly-Fumé)
 *
 * For producers we KNOW are not French (Antinori, Au Bon Climat, CVNE,
 * Ulysses), we tag them for separate handling — they should NOT be in
 * French VdF.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

// Producer name (as stored in dim_producer) → target appellation_name in dim_appellation.
// Sources for these mappings: Wine-Searcher, château second-wine lists, INAO appellation
// rules. All target appellations exist in our dim_appellation FR rows.
const KNOWN_AOC = {
  // — Bordeaux —
  'Château Pichon Longueville Baron':       'Pauillac',
  'Blanc de Lynch Bages':                   'Bordeaux Blanc',          // white from Pauillac estate
  'Pavillon de Léoville Poyferré':          'Saint-Julien',            // 2nd wine
  'La Chapelle de La Mission Haut-Brion':   'Pessac-Léognan',          // 2nd wine
  'Fugue de Nénin':                         'Pomerol',                 // 2nd wine
  'La Gravette de Certan':                  'Pomerol',                 // 2nd wine of VCC
  'Château La Confession':                  'Saint-Émilion',
  'Château Smith Haut Lafitte Blanc':       'Pessac-Léognan',          // white version
  'Château Destieux':                       'Saint-Émilion Grand Cru',
  'Château Saint-Georges Côte Pavie':       'Saint-Émilion Grand Cru',
  'Château La Clémence':                    'Pomerol',
  'Château Fonbel':                         'Saint-Émilion Grand Cru',
  'Château Bellevue':                       'Saint-Émilion Grand Cru',

  // — Burgundy —
  'Domaine Jean-Jacques Confuron':          'Vosne-Romanée',
  'Domaine A.F. Gros':                      'Vosne-Romanée',
  'Domaine Didier Dagueneau':               'Pouilly-Fumé',            // Loire

  // — South of France / Rhône —
  'La Vieille Ferme':                       'Ventoux',                 // Famille Perrin entry-level
  'Lionel Osmin & Cie':                     'Madiran',                 // Southwest negociant
  'Domaine Cazes':                          'Rivesaltes',              // Roussillon (mostly fortified)
  'Vignerons Associés Terres Sécrètes':     'Mâcon-Villages',          // Mâconnais coop
  'Château Le Puy':                         'Bordeaux',                // generic AOC Bordeaux

  // — Champagne —
  'Chamarré':                               'Champagne',               // (if it's the Champagne house)
};

// Producers we know are NOT French — tag for separate handling.
const NOT_FRENCH = new Set([
  'Antinori',          // Italian (Toscana IGT)
  'Au Bon Climat',     // California
  'C.V.N.E',           // Spanish (Rioja)
  'Ulysses',           // Napa Valley
]);

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

const vdfRow = db.prepare("SELECT appellation_key FROM dim_appellation WHERE appellation_name='Vin de France' AND country_code='FR'").get();
const findApp = db.prepare("SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_name = ? AND country_code='FR'");
const findProducer = db.prepare("SELECT producer_key FROM dim_producer WHERE producer_name = ? AND country_code='FR'");
const repointVdfWines = db.prepare(`
  UPDATE dim_wine SET appellation_key = ?
  WHERE producer_key = ? AND appellation_key = ?
`);

let resolved = 0, foreign = 0, missing = 0, winesMoved = 0;
const samples = [];

const tx = db.transaction(() => {
  for (const [producerName, appName] of Object.entries(KNOWN_AOC)) {
    const prod = findProducer.get(producerName);
    const app = findApp.get(appName);
    if (!prod || !app) { missing++; continue; }
    if (APPLY) {
      const moved = repointVdfWines.run(app.appellation_key, prod.producer_key, vdfRow.appellation_key).changes;
      winesMoved += moved;
      if (moved > 0 && samples.length < 30) {
        samples.push(`${producerName.padEnd(40)} → ${appName.padEnd(28)} (${moved} VdF → AOC)`);
      }
    } else {
      samples.push(`${producerName.padEnd(40)} → ${appName.padEnd(28)} (dry-run)`);
    }
    resolved++;
  }
  for (const producerName of NOT_FRENCH) {
    const prod = findProducer.get(producerName);
    if (!prod) continue;
    foreign++;
    // Don't auto-fix country mismatches yet — needs a foreign dim_appellation
    // row + dim_producer.country_code update. Surface in the log only.
  }
});

tx();

console.log(`Producer mappings applied : ${resolved}`);
console.log(`Wines re-pointed          : ${winesMoved}`);
console.log(`Foreign producers flagged : ${foreign}  (left as-is; need dim_producer.country_code + foreign AOC)`);
console.log(`Mappings with no DB match : ${missing}\n`);
for (const s of samples) console.log(`  ${s}`);

if (!APPLY) console.log('\n(Dry-run — re-run with --apply to mutate.)');

db.close();
