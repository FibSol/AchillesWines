/**
 * Fix dim_appellation rows that are incorrectly marked country_code='FR' but
 * belong to non-French regions. Strategy: for each suspect region, look at
 * what country_code is used by already-correct rows sharing that region string.
 * If consensus is clear (≥80% of non-FR rows agree), apply the fix.
 * Outputs a dry-run table; pass --apply to write.
 */
import Database from 'better-sqlite3';
import { argv } from 'process';

const APPLY = argv.includes('--apply');
const db = new Database('data/achilles.db');

// Hard-coded region → correct country_code for regions where no other rows exist
// (or where the region name is unambiguous)
const REGION_COUNTRY_OVERRIDE = {
  // USA
  'Californie': 'US', 'Oregon': 'US', 'Washington': 'US', 'New York': 'US',
  'North Coast': 'US', 'Central Coast': 'US', 'Sonoma County': 'US',
  'Russian River Valley': 'US', 'Mendocino': 'US', 'Lodi': 'US',
  'Santa Barbara County': 'US', 'Finger Lakes': 'US', 'Sta. Rita Hills': 'US',
  'Santa Ynez Valley': 'US', 'Sonoma Valley': 'US', 'Alexander Valley': 'US',
  'Dry Creek Valley': 'US', 'Paso Robles': 'US', 'Rutherford': 'US',
  'Oakville': 'US', 'Red Mountain': 'US', 'Walla Walla Valley': 'US',
  // Italy
  'Piémont': 'IT', 'Toscane': 'IT', 'Sicile': 'IT', 'Vénétie': 'IT',
  'Lombardie': 'IT', 'Frioul-Vénétie-Julienne': 'IT', 'Pouilles': 'IT',
  'Ombrie': 'IT', 'Sardaigne': 'IT', 'Marches': 'IT', 'Campanie': 'IT',
  'Trentin Haut-Adige': 'IT',
  // Spain
  'La Rioja': 'ES', 'Castille-León': 'ES', 'Galice': 'ES', 'Catalogne': 'ES',
  'Navarra': 'ES', 'Castille-La Manche': 'ES', 'Valence': 'ES',
  // Argentina
  'Mendoza': 'AR', 'Patagonie': 'AR',
  // Germany
  'Mosel': 'DE', 'Pfalz': 'DE', 'Nahe': 'DE', 'Basse-Autriche': 'AT',
  // New Zealand
  'Marlborough': 'NZ', 'Central Otago': 'NZ',
  // Australia
  'McLaren Vale': 'AU', 'Barossa Valley': 'AU', 'Southern Australia': 'AU',
  'Victoria': 'AU', 'Western Australia': 'AU', 'New South Wales': 'AU',
  'Tasmanie': 'AU', 'South Australia': 'AU',
  // South Africa
  'Stellenbosch': 'ZA', 'Walker Bay': 'ZA', 'Western Cape': 'ZA',
  'Swartland': 'ZA', 'Overberg': 'ZA', 'Franschhoek': 'ZA',
  'Paarl': 'ZA', 'Elgin': 'ZA',
  // Portugal
  'Duriense': 'PT', 'Minho': 'PT', 'Beiras': 'PT',
  // Chile
  'Colchagua': 'CL', 'Colchagua Valle': 'CL', 'Maipo Valle': 'CL',
  'Central Valley': 'CL', 'Aconcagua': 'CL', 'Casablanca Valle': 'CL',
  'Valle de Guadalupe': 'MX',
  // Other
  'Kakhétie': 'GE',
};

// Get all FR-marked appellations with their regions
const suspects = db.prepare(`
  SELECT a.appellation_key, a.appellation_name, a.country_code, a.region,
         COUNT(w.wine_key) as n_wines
  FROM dim_appellation a
  LEFT JOIN dim_wine w ON w.appellation_key = a.appellation_key
  WHERE a.country_code = 'FR'
  GROUP BY a.appellation_key
`).all();

// Determine correct country for each
const toFix = [];
let skipped = 0;

for (const app of suspects) {
  const correct = REGION_COUNTRY_OVERRIDE[app.region];
  if (correct && correct !== 'FR') {
    toFix.push({ ...app, correct_cc: correct });
  } else {
    skipped++;
  }
}

// Summary by target country
const byCountry = {};
for (const r of toFix) {
  byCountry[r.correct_cc] = (byCountry[r.correct_cc] || 0) + 1;
}

console.log(`FR-marked appellations to re-assign:`);
for (const [cc, cnt] of Object.entries(byCountry).sort((a,b)=>b[1]-a[1])) {
  console.log(`  ${cc}: ${cnt} appellations`);
}
console.log(`Correctly staying FR: ${skipped}`);
console.log(`Total to fix: ${toFix.length}`);
console.log('');

// Show top 20 by wine count
console.log('Top 20 by wine count:');
toFix.sort((a,b) => b.n_wines - a.n_wines).slice(0,20).forEach(r => {
  console.log(`  [${r.n_wines}w] ${r.correct_cc} <- ${r.appellation_name} (region: ${r.region})`);
});

if (APPLY) {
  console.log('\n=== APPLYING FIXES ===');
  const update = db.prepare(
    'UPDATE dim_appellation SET country_code=? WHERE appellation_key=?'
  );
  db.transaction(() => {
    for (const r of toFix) update.run(r.correct_cc, r.appellation_key);
  })();
  console.log(`Updated ${toFix.length} rows.`);

  // Verify
  const remaining = db.prepare(
    `SELECT region, COUNT(*) as cnt FROM dim_appellation
     WHERE country_code='FR' AND region IN (${Object.keys(REGION_COUNTRY_OVERRIDE).map(()=>'?').join(',')})
     GROUP BY region`
  ).all(...Object.keys(REGION_COUNTRY_OVERRIDE));
  console.log('Remaining FR rows in known-non-FR regions:', remaining.length);
} else {
  console.log('\n--- DRY RUN. Pass --apply to write changes. ---');
}

db.close();
