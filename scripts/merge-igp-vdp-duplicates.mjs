#!/usr/bin/env node
/**
 * Merge "Vin de Pays X" appellation rows into their post-2009 IGP equivalent.
 *
 * Reference: EU OCM 2009 reform — every "Vin de Pays" became an "Indication
 * Géographique Protégée" (IGP). Official list of 75 IGPs from FranceAgriMer
 * (Carte des IGP, 2022 ed.): docs/FR-IGP-REFERENCE.md.
 *
 * Each entry is { igp: <canonical IGP name>, aliases: [array of dim_appellation
 * names that should collapse into the IGP row]. When the canonical doesn't
 * exist in the DB yet, the first alias gets renamed to canonical and kept.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

// Mapping built from the FranceAgriMer 75-IGP list cross-referenced with the
// dim_appellation rows currently in the DB. "Vin de Pays" / "Pays" / "IGP"
// prefixes for the same area all collapse onto the canonical IGP name.
const IGP_MERGES = [
  // Régionales (6)
  { igp: 'IGP Pays d\'Oc',           region: 'Languedoc-Roussillon',
    aliases: ['Pays d\'Oc', 'Vin de Pays d\'Oc'] },
  { igp: 'IGP Méditerranée',         region: 'Méditerranée',
    aliases: ['Méditerranée', 'Vin de Pays de la Méditerranée', 'Vin de Pays des Portes de Méditerranée'] },
  { igp: 'IGP Comté Tolosan',        region: 'Sud-Ouest',
    aliases: ['Vin de Pays du Comté Tolosan', 'Comté Tolosan'] },
  { igp: 'IGP Comtés Rhodaniens',    region: 'Vallée du Rhône',
    aliases: ['Comtés Rhodaniens', 'Vin de Pays des Comtés Rhodaniens'] },
  { igp: 'IGP Val de Loire',         region: 'Vallée de la Loire',
    aliases: ['Val de Loire', 'Vin de Pays du Val de Loire', 'Vin de Pays du Jardin de la France', 'Pays de Loire'] },
  { igp: 'IGP Atlantique',           region: 'Sud-Ouest',
    aliases: ['Atlantique', 'Vin de Pays de l\'Atlantique'] },

  // Départementales (sample of the biggest by wine count)
  { igp: 'IGP Côtes de Gascogne',    region: 'Sud-Ouest',
    aliases: ['Vin de Pays des Côtes de Gascogne', 'Côtes de Gascogne'] },
  { igp: 'IGP Var',                  region: 'Provence',
    aliases: ['Vin de Pays Var', 'Vin de Pays du Var', 'Var'] },
  { igp: 'IGP Vaucluse',             region: 'Vallée du Rhône',
    aliases: ['Vin de Pays de Vaucluse', 'Vaucluse'] },
  { igp: 'IGP Pays d\'Hérault',      region: 'Languedoc-Roussillon',
    aliases: ['Pays d\'Hérault', 'Vin de Pays de L\'Herault', 'IGP Pays de l\'Hérault', 'Vin de Pays de l\'Hérault'] },
  { igp: 'IGP Gard',                 region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays du Gard', 'IGP Pays du Gard', 'Gard'] },
  { igp: 'IGP Aude',                 region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays de L\'Aude', 'Vin de Pays de l\'Aude', 'Aude'] },
  { igp: 'IGP Côtes du Lot',         region: 'Sud-Ouest',
    aliases: ['Vin de Pays du Lot', 'Côtes du Lot'] },
  { igp: 'IGP Aveyron',              region: 'Sud-Ouest',
    aliases: ['Vin de Pays de l\'Aveyron'] },
  { igp: 'IGP Île de Beauté',        region: 'Corse',
    aliases: ['Vin de Pays de l\'Île de Beauté', 'Île de Beauté'] },
  { igp: 'IGP Côtes Catalanes',      region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays des Côtes Catalanes', 'Côtes Catalanes'] },

  // Petites zones (sample)
  { igp: 'IGP Cévennes',             region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays des Cévennes', 'Cévennes'] },
  { igp: 'IGP Cité de Carcassonne',  region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays Cité de Carcassonne'] },
  { igp: 'IGP Alpilles',             region: 'Provence',
    aliases: ['Vin de Pays des Alpilles'] },
  { igp: 'IGP Collines Rhodaniennes', region: 'Vallée du Rhône',
    aliases: ['Vin de Pays des Collines Rhodaniennes'] },
  { igp: 'IGP Côtes de la Charité',  region: 'Vallée de la Loire',
    aliases: [] },
  { igp: 'IGP Vins des Allobroges',  region: 'Savoie',
    aliases: ['IGP Vin des Allobroges', 'Vins des Allobroges', 'Vin des Allobroges'] },
  { igp: 'IGP Haute Vallée de l\'Aude', region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays de la Haute Vallée de l\'Aude', 'IGP Haute Vallée de L\'Aude'] },
  { igp: 'IGP Val de Cesse',         region: 'Languedoc-Roussillon',
    aliases: ['Vin de Pays du Val de Cesse'] },

  // Generic "Vignobles de France" is now "Vin de France" (no GI) — leave the
  // 'Vin de France' rows untouched but collapse the legacy synonym onto it.
  { igp: 'Vin de France',            region: null,
    aliases: ['Vin de Pays Vignobles de France', 'Vignobles de France'] },
];

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

const findApp = db.prepare("SELECT * FROM dim_appellation WHERE appellation_name = ? AND country_code = 'FR'");
const findAppByNorm = db.prepare("SELECT * FROM dim_appellation WHERE appellation_norm = ? AND country_code = 'FR'");
const insertApp = db.prepare(`
  INSERT INTO dim_appellation (country_code, region, appellation_name, appellation_norm, level)
  VALUES ('FR', ?, ?, ?, 'regional')
`);
const renameApp = db.prepare('UPDATE dim_appellation SET appellation_name = ?, appellation_norm = ?, region = COALESCE(?, region) WHERE appellation_key = ?');
const repointWines = db.prepare('UPDATE dim_wine SET appellation_key = ? WHERE appellation_key = ?');
const deleteApp = db.prepare('DELETE FROM dim_appellation WHERE appellation_key = ?');

function normText(s) {
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

let mergedCount = 0;
let winesMoved = 0;
const samples = [];

const tx = db.transaction(() => {
  for (const entry of IGP_MERGES) {
    // 1. Find or create the survivor row.
    let survivor = findApp.get(entry.igp);
    if (!survivor) {
      // Try to promote one of the aliases.
      for (const alias of entry.aliases) {
        const cand = findApp.get(alias);
        if (cand) {
          // Avoid the rename UNIQUE collision: if another row already holds the
          // target norm, merge candidate into it instead of renaming.
          const targetNorm = normText(entry.igp);
          const collision = findAppByNorm.get(targetNorm);
          if (collision && collision.appellation_key !== cand.appellation_key) {
            survivor = collision;
            const moved = repointWines.run(survivor.appellation_key, cand.appellation_key).changes;
            winesMoved += moved;
            deleteApp.run(cand.appellation_key);
          } else {
            renameApp.run(entry.igp, targetNorm, entry.region, cand.appellation_key);
            survivor = findApp.get(entry.igp);
          }
          break;
        }
      }
    }
    if (!survivor) {
      // Nothing to merge.
      continue;
    }

    // 2. Re-point all other aliases into the survivor.
    for (const alias of entry.aliases) {
      const cand = findApp.get(alias);
      if (!cand || cand.appellation_key === survivor.appellation_key) continue;
      const moved = repointWines.run(survivor.appellation_key, cand.appellation_key).changes;
      winesMoved += moved;
      deleteApp.run(cand.appellation_key);
      mergedCount++;
      if (samples.length < 25) {
        samples.push(`"${alias}" → "${survivor.appellation_name}"  (${moved} wines)`);
      }
    }
  }
});

if (APPLY) tx();

console.log(`=== Vin de Pays → IGP merge ===\n`);
console.log(`Mergeable aliases collapsed : ${mergedCount}`);
console.log(`Wines re-pointed            : ${winesMoved}\n`);
console.log(`--- Sample ---`);
for (const s of samples) console.log(`  ${s}`);

if (!APPLY) console.log('\n(Dry-run — re-run with --apply to mutate.)');

db.close();
