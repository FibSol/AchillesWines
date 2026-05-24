/**
 * Fix specific appellation name mismatches vs INAO canonical names.
 * Pass --apply to write.
 */
import Database from 'better-sqlite3';
import { argv } from 'process';

const APPLY = argv.includes('--apply');
const db = new Database('data/achilles.db');

// Renames: [current DB name, canonical INAO name, reason]
const RENAMES = [
  ['Nuits-St.-Georges',     'Nuits-Saint-Georges',  'abbreviation St. → Saint'],
  ['Nuits-St.-Georges',     'Nuits-Saint-Georges',  'abbreviation St. → Saint'],  // guard duplicate
  ['Ermitage',              'Hermitage',             'alternative spelling'],
  ['Crozes-Ermitage',       'Crozes-Hermitage',      'alternative spelling'],
  ['Beaujolais Villages',   'Beaujolais-Villages',   'missing hyphen'],
  ['Côte de Beaune Villages','Côte de Beaune-Villages','missing hyphen'],
  ['Macon',                 'Mâcon',                 'missing accent'],
  ['Cotes du Rhone',        'Côtes du Rhône',        'missing accents'],
  ['Saint-Emilion',         'Saint-Émilion',         'missing accent on É'],
];

// Deduplicate by current name
const seen = new Set();
const uniq = RENAMES.filter(([from]) => { if (seen.has(from)) return false; seen.add(from); return true; });

let totalFixed = 0;
for (const [fromName, toName, reason] of uniq) {
  const rows = db.prepare(
    "SELECT appellation_key, appellation_name FROM dim_appellation WHERE appellation_name = ?"
  ).all(fromName);
  if (rows.length === 0) {
    console.log(`  SKIP "${fromName}" — not found`);
    continue;
  }
  console.log(`  ${rows.length} row(s): "${fromName}" → "${toName}" (${reason})`);
  if (APPLY) {
    db.prepare("UPDATE dim_appellation SET appellation_name = ? WHERE appellation_name = ?")
      .run(toName, fromName);
    totalFixed += rows.length;
  }
}

if (APPLY) {
  console.log(`\nApplied ${totalFixed} name updates.`);
} else {
  console.log('\n--- DRY RUN. Pass --apply to write. ---');
}
db.close();
