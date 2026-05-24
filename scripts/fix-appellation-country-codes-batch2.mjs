/**
 * Batch 2 country code fixes — regions not covered by batch 1.
 * Pass --apply to write.
 */
import Database from 'better-sqlite3';
import { argv } from 'process';

const APPLY = argv.includes('--apply');
const db = new Database('data/achilles.db');

const REGION_COUNTRY = {
  // Italian — region name is the Italian sub-region or appellation itself
  'Chianti': 'IT', 'Chianti Colli Senesi': 'IT', 'Abruzzes': 'IT',
  'Prosecco': 'IT', 'Puglia': 'IT', 'Dolcetto d\'Alba': 'IT',
  'Basilicate': 'IT', 'Primitivo di Manduria': 'IT',
  'Valpolicella Classico': 'IT', 'Noto': 'IT', 'Sicilia Menfi': 'IT',
  'Rosso Piceno': 'IT', 'San Severo': 'IT', 'Monica di Sardegna': 'IT',
  'Monferrato': 'IT', 'Lambrusco Grasparossa': 'IT', 'Lambrusco Reggiano': 'IT',
  'Taurasi Riserva': 'IT', 'Bolgheri Sassicaia': 'IT',
  'Amarone della Valpolicella': 'IT',
  // Spanish
  'Jumilla': 'ES', 'Carinena': 'ES', 'La Mancha': 'ES', 'Calatayud': 'ES',
  'Valencia': 'ES', 'Utiel-Requena': 'ES', 'Cebreros': 'ES',
  'Sierra de Gredos': 'ES', 'Manchuela': 'ES', 'Yecla': 'ES',
  'Mallorca': 'ES', 'Valle de la Orotava': 'ES',
  // Argentine
  'Luján de Cuyo': 'AR', 'Cafayate': 'AR', 'Aconcagua': 'AR',
  'Tulum Valle': 'AR',
  // Chilean
  'Coquimbo': 'CL', 'Peumo': 'CL', 'Puente Alto': 'CL',
  'Atacama': 'CL', 'Aconcagua Valle': 'CL',
  // Greek
  'Péloponnèse': 'GR', 'Cyclades': 'GR', 'Macédoine et Thrace': 'GR',
  'Pitsilia Mountains': 'CY', 'Lemesos': 'CY', 'Pafos': 'CY',
  'Slopes of Aigialia': 'GR',
  // Hungarian
  'Tokaj': 'HU', 'tokaj': 'HU', 'Tokay': 'HU',
  'Somlói Vándor': 'HU',
  // Australian
  'SOUTH_AUSTRALIA': 'AU', 'South Australia': 'AU',
  // Other
  'Jiri Valley': 'AF',
  'Lake Skadar Valley': 'ME',
  'Mirditë': 'AL',
  'Mostar': 'BA',
  'Progreso': 'UY',
  'Tunisia': 'TN',
};

const suspects = db.prepare(`
  SELECT a.appellation_key, a.appellation_name, a.country_code, a.region,
         COUNT(w.wine_key) as n_wines
  FROM dim_appellation a
  LEFT JOIN dim_wine w ON w.appellation_key = a.appellation_key
  WHERE a.country_code = 'FR'
  GROUP BY a.appellation_key
`).all();

const toFix = suspects
  .filter(a => REGION_COUNTRY[a.region] && REGION_COUNTRY[a.region] !== 'FR')
  .map(a => ({ ...a, correct_cc: REGION_COUNTRY[a.region] }));

const byCC = {};
for (const r of toFix) byCC[r.correct_cc] = (byCC[r.correct_cc] || 0) + 1;
console.log(`Batch 2 fixes: ${toFix.length} appellations`);
Object.entries(byCC).sort((a,b)=>b[1]-a[1]).forEach(([cc,n]) => console.log(`  ${cc}: ${n}`));
console.log('\nTop 15 by wine count:');
[...toFix].sort((a,b)=>b.n_wines-a.n_wines).slice(0,15).forEach(r =>
  console.log(`  [${r.n_wines}w] ${r.correct_cc} <- ${r.appellation_name} (region: ${r.region})`)
);

if (APPLY) {
  const update = db.prepare('UPDATE dim_appellation SET country_code=? WHERE appellation_key=?');
  db.transaction(() => { for (const r of toFix) update.run(r.correct_cc, r.appellation_key); })();
  console.log(`\nApplied ${toFix.length} updates.`);
} else {
  console.log('\n--- DRY RUN. Pass --apply to write. ---');
}
db.close();
