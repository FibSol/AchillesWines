#!/usr/bin/env node
/**
 * Normalize FR region labels in dim_producer.region and dim_appellation.region
 * to match the canonical names used by ONIVINS / INAO.
 *
 * Reference: https://onivins.fr/regions-viticoles-france/
 *   The 15 official French wine regions:
 *     Alsace · Bordeaux · Bourgogne · Bugey · Champagne · Corse · Jura ·
 *     Languedoc-Roussillon · Lorraine · Lyonnais · Provence · Savoie ·
 *     Sud-Ouest · Vallée de la Loire · Vallée du Rhône
 *
 * This DB keeps sub-region granularity (Côte de Beaune, Chablis, Mâconnais,
 * Rhône Nord/Sud, etc.) which is more useful for analysis than collapsing
 * everything to 15 buckets. We only fix spelling inconsistencies — the
 * sub-region structure stays.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

// Old → canonical mapping (only FR rows are touched).
const RENAMES = [
  ['Corsica', 'Corse'],
  ['Loire',   'Vallée de la Loire'],
  // Rhône is kept granular (Nord/Sud) but spelling normalised.
  ['Rhône Nord', 'Vallée du Rhône — Nord'],
  ['Rhône Sud',  'Vallée du Rhône — Sud'],
];

// "Languedoc-Roussillon" is too broad — when we have only 4 producers under
// it, they should be split. Leaving as-is for now (manual review needed).

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

const stmts = {
  countProd: db.prepare("SELECT COUNT(*) AS n FROM dim_producer WHERE country_code='FR' AND region = ?"),
  countApp:  db.prepare("SELECT COUNT(*) AS n FROM dim_appellation WHERE country_code='FR' AND region = ?"),
  updProd:   db.prepare("UPDATE dim_producer    SET region = ? WHERE country_code='FR' AND region = ?"),
  updApp:    db.prepare("UPDATE dim_appellation SET region = ? WHERE country_code='FR' AND region = ?"),
};

console.log('=== FR region normalisation ===\n');
let totalProd = 0, totalApp = 0;

const tx = db.transaction(() => {
  for (const [oldName, newName] of RENAMES) {
    const nP = stmts.countProd.get(oldName).n;
    const nA = stmts.countApp.get(oldName).n;
    if (nP === 0 && nA === 0) {
      console.log(`  · ${oldName.padEnd(20)} → ${newName.padEnd(28)}  (no rows, skip)`);
      continue;
    }
    console.log(`  · ${oldName.padEnd(20)} → ${newName.padEnd(28)}  producers=${nP}  appellations=${nA}`);
    if (APPLY) {
      stmts.updProd.run(newName, oldName);
      stmts.updApp.run(newName, oldName);
    }
    totalProd += nP;
    totalApp  += nA;
  }
});

tx();
console.log(`\nTotal: ${totalProd} producer rows + ${totalApp} appellation rows affected.`);
if (!APPLY) console.log('(Dry-run — re-run with --apply to mutate.)');

db.close();
