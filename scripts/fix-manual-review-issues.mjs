/**
 * fix-manual-review-issues.mjs
 *
 * Applies all corrections identified via manual research of data/manual-review.csv.
 * Research conducted 2026-05-27: web-verified every ambiguous entry against
 * Wine-Searcher, Vivino, Decanter and producer websites.
 *
 * Run: node scripts/fix-manual-review-issues.mjs [--dry-run]
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
  // Disable FK constraints for this bulk-cleanup run.
  // We handle referential integrity explicitly by deleting child rows first.
  db.pragma('foreign_keys = OFF');
}

let deleted = 0;
let updated = 0;
let errors = 0;

function run(sql, params = []) {
  if (DRY_RUN) {
    console.log('[DRY]', sql.replace(/\s+/g, ' ').slice(0, 120));
    return { changes: 0 };
  }
  try {
    const stmt = db.prepare(sql);
    const r = Array.isArray(params[0]) ? null : stmt.run(...params);
    return r;
  } catch (e) {
    console.error('ERROR:', e.message, '| SQL:', sql.slice(0, 80));
    errors++;
    return { changes: 0 };
  }
}

function del(table, keyCol, keyVal) {
  const r = run(`DELETE FROM ${table} WHERE ${keyCol} = ?`, [keyVal]);
  if (r?.changes) deleted += r.changes;
  return r?.changes ?? 0;
}

function upd(table, set, where, params) {
  const r = run(`UPDATE ${table} SET ${set} WHERE ${where}`, params);
  if (r?.changes) updated += r.changes;
  return r?.changes ?? 0;
}

// ─────────────────────────────────────────────────────────────
// APPELLATION KEY CONSTANTS (verified from dim_appellation)
// ─────────────────────────────────────────────────────────────
const APX = {
  VIN_DE_FRANCE:               305,
  SAINT_EMILION_GRAND_CRU:     804,
  SAINT_EMILION:               214,
  PAUILLAC:                      5,
  PESSAC_LEOGNAN:              210,
  POMEROL:                     215,
  MARGAUX:                     212,
  CHABLIS:                     226,
  GEVREY_CHAMBERTIN:           294,
  MEURSAULT:                     1,
  SANTENAY:                    334,
  GIVRY:                       278,
  CASTILLON_COTES_BORDEAUX:    225,
  CORBIERES:                   309,
  SAUMUR:                      397,
  CHAMPAGNE:                     6,
  MONTAGNE_SAINT_EMILION:      227,
  SAINTE_CROIX_DU_MONT:       1030,
  POUILLY_FUISSE:              150,
  NUITS_SAINT_GEORGES:         259,
  VOSNE_ROMANEE:                 3,
  MOREY_SAINT_DENIS:            33,
  BOURGOGNE:                   230,
  CABARDES:                    780,
  COTES_DU_RHONE:              242,
  ANJOU:                       416,
  BORDEAUX:                    224,
  ENTRE_DEUX_MERS:             917,
};

console.log(`\n=== fix-manual-review-issues.mjs ${DRY_RUN ? '[DRY RUN]' : '[LIVE]'} ===\n`);

// ─────────────────────────────────────────────────────────────
// SECTION 1: DELETE non-French dim_wine entries (appellation_vin_de_france_mixed_portfolio)
// Research confirmed these are non-French wines incorrectly in the French DB.
// ─────────────────────────────────────────────────────────────
console.log('--- SECTION 1: Delete non-French wine entries from dim_wine ---');

const NON_FRENCH_WINE_KEYS = [
  // Antinori (Italian, Tuscany) — 4 vintages 2010/2011/2015/2019
  '2fe7f2fefb0c0e72', 'e96e2118db563457', '7f3ba6570a3ff8d2', 'b1e3590235b5560d',
  // Au Bon Climat (California, Santa Barbara) — 2020/2021
  '02090be33cd1bce2', 'fe90c1596b2624da',
  // C.V.N.E. / CVNE (Spanish, Rioja) — 2019/2020
  '37707978405e2be4', '955005dd218a0d16',
  // Craggy Range (New Zealand) — 2020/2023
  'dba5690956acb89c', 'b110b9a86d533307',
  // AALTO (Spanish, Ribera del Duero) — 2001
  '92971d3e99b6e9f9',
  // Penfolds (Australian) — 2020/2021
  '8c42208d0c096b8e', 'fbb87711e946d999',
  // Quinta da Romaneira (Portuguese, Douro) — 2015/2016/2017/2018
  '79ed5a447a16ed24', '48cbc9cff9b0184e', '788a439ad9d3b026', '479a4650eead9437',
  // Roberto Voerzio (Italian, Barolo/La Morra) — 2016/2018
  '5c512b41df1c1a31', '2fb94598ae386090',
  // Seghesio (Italian, Barolo / OR Sonoma) — not French either way — 2015/2021
  '8be41cd0b0c2854a', '66e1b36e50de1492',
  // Tenuta Dell'Ornellaia (Italian, Bolgheri) — 2021
  '0adc40e2119b049d',
  // Terrazas de Los Andes (Argentine) — 2022
  '7b94f880dea30bba',
  // Zuccardi (Argentine) — 2017
  'e7d63896a2bc84a0',
  // Nicolas Catena Zapata (Argentine) — 2019
  '348a9e85bbcb1c0b',
  // Doga Delle Clavule (Italian, Morellino di Scansano) — 2021/2023
  '99d7f3d8f5f0c1e7', 'cb74e2e275f9d20b',
  // PASSO DELLE TORTORE (Italian) — 2020/2023/2024
  '68a89a1f767563c2', 'd5e6ace65df5a599', '9f8575abafc4f610',
  // Joseph Phelps (Californian, Napa) — 2018
  '657a9c740630e721',
  // Domaine Petrolo (Italian, Valdarno di Sopra) — 2018/2020/2021
  'b92efac99334b026', 'a8b997a54de9ec2f', 'c4f42e8bdb8a1124',
  // Rhum (rum products, not wine) — 2003/2010
  'bb3c8f2a493d32fb', '4d1fb0a507a984a5',
  // Ulysses (Christian Moueix's Napa Valley project) — 2013/2014/2015/2019/2020/2021
  'ddda84e08a80ecc2', '4915e16e54ea028d', '3cc6807d26ddc685',
  'b26570175ebc86e2', '331d365c1cc83d91', '2368d8c4fb8883fa',
  // Maya / Dalla Valle (Napa Valley, California) — 2020
  '7f76e76c8c822811',
  // Mazzei (Italian, Chianti Classico) — 2019/2020
  'fcea6dad5690839f', '75256afda45001cc',
  // Giodo (Italian, Brunello di Montalcino, Carlo Ferrini) — 2019
  'c5d90c34f01952c4',
  // Giacosa Bruno (Italian, Barbaresco/Barolo) — 2020
  'c160eb6a40aed31c',
  // Domaine Drouhin (Oregon winery, not French Maison Joseph Drouhin) — 2019/2021
  'f25a86d632ce479b', '328b202c4747b2fe',
];

const placeholders1 = NON_FRENCH_WINE_KEYS.map(() => '?').join(',');
if (DRY_RUN) {
  console.log(`[DRY] DELETE child rows + dim_wine for ${NON_FRENCH_WINE_KEYS.length} non-French wine_keys`);
} else {
  // Delete child rows referencing these wine_keys first
  for (const childTable of ['fact_price', 'fact_rating', 'cellar_inventory', 'cellar_consumption', 'bridge_wine_variety', 'staging_price_candidates']) {
    try {
      const r = db.prepare(`DELETE FROM ${childTable} WHERE wine_key IN (${placeholders1})`).run(...NON_FRENCH_WINE_KEYS);
      if (r.changes) console.log(`  Deleted ${r.changes} rows from ${childTable}`);
    } catch (e) {
      // table may not have wine_key column — skip silently
    }
  }
  const stmt = db.prepare(`DELETE FROM dim_wine WHERE wine_key IN (${placeholders1})`);
  const r = stmt.run(...NON_FRENCH_WINE_KEYS);
  deleted += r.changes;
  console.log(`Deleted ${r.changes} non-French wine rows from dim_wine`);
}

// ─────────────────────────────────────────────────────────────
// SECTION 2: FIX appellation_key for French wines wrongly tagged as Vin de France
// ─────────────────────────────────────────────────────────────
console.log('\n--- SECTION 2: Fix appellation_key for misclassified French wines ---');

const VDF_APPELLATION_FIXES = [
  // → Saint-Émilion Grand Cru (804)
  { akey: APX.SAINT_EMILION_GRAND_CRU, keys: [
    // Château Beauséjour Bécot — 4 vintages 2018/2021/2023/2024
    '353f3f03892147be', '7d23a8f0520c2eb6', '1e0b5fb4c466a188', '8f74a8055bd1d2b4',
    // Château Beauséjour — 2020/2025
    'de4ba3922bedca0a', '75fd3b7956535272',
    // Château Croix Cardinale — 2019/2022
    '27da00dd0f4d3621', '5057d876897bc08d',
    // Château Lamarzelle Cormey — 2019
    'b4bd1c960f48f00f',
    // Château Montlisse — 2022/2023
    'be5aa9405af39cbc', '2c2cedfd19f85ddc',
  ]},
  // → Pauillac (5)
  { akey: APX.PAUILLAC, keys: [
    // Réserve de la Comtesse (2nd wine Pichon Lalande) — 2016/2019
    'e807fafeb9734928', 'c08ba6ba0ddbae53',
    // Forts de Latour (2nd wine Château Latour) — 2018
    'f13b81f8b7659744',
  ]},
  // → Pessac-Léognan (210)
  { akey: APX.PESSAC_LEOGNAN, keys: [
    // Château Tour Léognan (2nd wine Château Carbonnieux) — 2019/2022/2023
    '204dd9a4efeb88fa', '4dd2b1e8df90bb81', '078f64898612d88b',
    // Château Coucheroy (Carbonnieux sibling) — 2020/2021/2023
    '64d9652fb3c56804', 'dec185cd365af12a', '71f347cd6052a1b8',
    // Château Le Thil — 2020/2021/2025
    'f3b40642a576f8d8', '4658b45d4a470207', '1cec689dca6d1982',
    // Château Haut-Nouchet — 2010
    '195f2c5e661590cf',
    // L'Esprit de Chevalier Blanc (Domaine de Chevalier) — 2025
    '2d01672cd081c33c',
  ]},
  // → Pomerol (215)
  { akey: APX.POMEROL, keys: [
    // Espérance de Trotanoy (2nd wine Trotanoy) — 2018/2022/2023
    'ad7308bfebed0ee3', '697d184c112a02b9', 'f27251a08a2940f1',
    // Le Carillon de Rouget (2nd wine Château Rouget) — 2020
    '935a898489414618',
  ]},
  // → Margaux (212)
  { akey: APX.MARGAUX, keys: [
    // Château des Graviers (Arsac, Margaux) — 2019
    'fb7db5d88332b206',
  ]},
  // → Chablis (226)
  { akey: APX.CHABLIS, keys: [
    // Domaine Long-Depaquit — 2022/2023
    '8a05adcac59cc096', '7f41bc2703249d42',
  ]},
  // → Gevrey-Chambertin (294)
  { akey: APX.GEVREY_CHAMBERTIN, keys: [
    // Domaine Trapet — 2014
    '9ec0bdf45a6143e4',
    // Domaine Drouhin-Laroze — 2021/2022/2023/2024
    'a9af90e17274a53e', '7c4c1d1e761b8ec4', 'fb8153a030640294', 'f1b41faa99f96cbc',
  ]},
  // → Meursault (1)
  { akey: APX.MEURSAULT, keys: [
    // Domaine du Pavillon (Albert Bichot) — 2022/2023
    '5e4ab5e0cdcb9b1b', '3a7f322d9c9b5f53',
  ]},
  // → Santenay (334)
  { akey: APX.SANTENAY, keys: [
    // Domaine Bachey-Legros — 2023/2024
    '95f5926f8cbc076f', '7f18be5abf6dc701',
  ]},
  // → Givry (278)
  { akey: APX.GIVRY, keys: [
    // Domaine Chofflet-Valdenaire — 2018/2019/2020/2023
    '9c0f72abed333932', 'e0e34578871ea805', '31a0f930662d0813', '1d2b2a792ded99b0',
  ]},
  // → Castillon Côtes de Bordeaux (225)
  { akey: APX.CASTILLON_COTES_BORDEAUX, keys: [
    // Château Montlanderie / Montlandrie (Denis Durantou) — 2015
    '3cbea0c05769bac3',
  ]},
  // → Corbières (309)
  { akey: APX.CORBIERES, keys: [
    // Château d'Aussières (Rothschild + Domaines Barons) — 2020
    'cb29b3c4ae5b34db',
  ]},
  // → Saumur (397)
  { akey: APX.SAUMUR, keys: [
    // Château de Fosse-Sèche (Brossay, Loire) — 2022
    'e92069456e544a6a',
  ]},
  // → Champagne (6)
  { akey: APX.CHAMPAGNE, keys: [
    // Billecart-Salmon NV — should not be VdF
    'afb0b461d505d65f',
  ]},
  // → Montagne-Saint-Émilion (227)
  { akey: APX.MONTAGNE_SAINT_EMILION, keys: [
    // Château Indépendance — 2022/2023/2024
    'a15881a851536ea5', 'e4311444a3789408', '6ac6c84831955a31',
    // Château Plaisance — 2015
    'fd41f04dac6530b1',
  ]},
  // → Sainte-Croix-du-Mont (1030)
  { akey: APX.SAINTE_CROIX_DU_MONT, keys: [
    // Château La Rame — 2021
    '07e686918cbca26b',
  ]},
  // → Pouilly-Fuissé (150)
  { akey: APX.POUILLY_FUISSE, keys: [
    // Domaine Denis Jeandeau — 2019
    'faae1d3de6a2c97c',
    // Domaine du Roc des Boutires — 2020/2021
    '9ad6d3464540274d', '2724c09e3843897a',
  ]},
  // → Nuits-Saint-Georges (259)
  { akey: APX.NUITS_SAINT_GEORGES, keys: [
    // Domaine Jean Chauvenet — 2022
    '5230e5f45552ffc5',
    // Domaine David Duband — 2011
    '55d6df074136e0b1',
  ]},
  // → Vosne-Romanée (3)
  { akey: APX.VOSNE_ROMANEE, keys: [
    // Domaine Sylvain Cathiard — 2016
    'f0db9624dd183f38',
    // Domaine Michel Noëllat — 2021
    '1b8f826e9c700f9d',
  ]},
  // → Morey-Saint-Denis (33)
  { akey: APX.MOREY_SAINT_DENIS, keys: [
    // Domaine Hubert Lignier — 2014
    '66adf4f663aa1c97',
    // Domaine Stéphane Magnien — 2020
    '8a9df427dc4b1ad5',
    // CLOS SAINT DENIS GRAND CRU JADOT — 5 vintages 2016–2021
    '8ae6ee90d14f9606', 'bd37c56f1ba8c099', '07e774c24ece6305',
    'd4f20e08bbdae79d', '3471518d5b6e025c',
  ]},
  // → Bourgogne (230)
  { akey: APX.BOURGOGNE, keys: [
    // Maison Joseph Drouhin — 2024 (VdF is wrong for this Burgundy house)
    'd0d2d77a7ed54827',
    // Domaine des Baumard 2017 (vintage wine, not their VdF Le Petit Paon)
    '9630eff6cb5cf88d',
  ]},
  // → Cabardès (780)
  { akey: APX.CABARDES, keys: [
    // Maison Lorgeril (Château de Pennautier) — 2022/2024
    'cfaf2221da9f3dd7', '87cb31161fed2e61',
  ]},
  // → Côtes du Rhône (242)
  { akey: APX.COTES_DU_RHONE, keys: [
    // Dauvergne Ranvier — 2018 (confirmed: no VdF wines, all Rhône AOC)
    '26c1a630bea52359',
  ]},
  // → Bordeaux (224)
  { akey: APX.BORDEAUX, keys: [
    // Château Bonnet (André Lurton, Entre-Deux-Mers) — 2019/2021
    '94bc71776b01007b', '6337f5942d184875',
  ]},
];

for (const { akey, keys } of VDF_APPELLATION_FIXES) {
  const ph = keys.map(() => '?').join(',');
  if (DRY_RUN) {
    console.log(`[DRY] UPDATE dim_wine SET appellation_key=${akey} WHERE wine_key IN (${keys.length} keys)`);
  } else {
    const stmt = db.prepare(`UPDATE dim_wine SET appellation_key = ? WHERE wine_key IN (${ph})`);
    const r = stmt.run(akey, ...keys);
    updated += r.changes;
    if (r.changes > 0) console.log(`Updated ${r.changes} wines → appellation_key=${akey}`);
  }
}

// ─────────────────────────────────────────────────────────────
// SECTION 3: Fix cuvée names (cuvee_classification, cuvee_size, cuvee_packaging)
// ─────────────────────────────────────────────────────────────
console.log('\n--- SECTION 3: Fix cuvée names ---');

// Cuvée classification fix: strip "Cru Classe " prefix from Château Sainte Roseline's Lampe de Méduse
upd('dim_wine', "cuvee_name = 'Lampe de Méduse', cuvee_norm = 'lampe de meduse'",
    "wine_key = ?", ['b7ae651ca9a7241d']);
console.log('Fixed: "Cru Classe Lampe de Meduse" → "Lampe de Méduse" (Château Sainte Roseline)');

// cuvee_packaging: strip "- en Etui" from Taylor's Porto
upd('dim_wine', "cuvee_name = 'Taylor\\'s - 10 Ans', cuvee_norm = 'taylors 10 ans'",
    "wine_key = ?", ['ca67b5cd0e734cdd']);
console.log('Fixed: Taylor\'s Porto cuvée name (removed gift box suffix)');

// cuvee_size: strip "Demi-bouteille - " prefix and set bottle_ml=375
const CUVEE_SIZE_FIXES = [
  // "Demi-bouteille - Belleruche Rouge - M. Chapoutier"
  { key: '3b960de65bb84be6', cuvee: 'Belleruche Rouge', norm: 'belleruche rouge' },
  // "Demi-Bouteille - Château Les Ormes de Pez"
  { key: 'b0cd18f49a0755b0', cuvee: 'Château Les Ormes de Pez', norm: 'chateau les ormes de pez' },
  // "Demi-bouteille - Morgon - Marcel Lapierre"
  { key: 'fc7caf207584e06c', cuvee: 'Morgon', norm: 'morgon' },
  // "Demi-bouteille - Pouilly Fuissé - Vieilles Vignes - Famille Perrachon"
  { key: '00dd1b1e2a48dbfd', cuvee: 'Vieilles Vignes', norm: 'vieilles vignes' },
];

for (const { key, cuvee, norm } of CUVEE_SIZE_FIXES) {
  upd('dim_wine', "cuvee_name = ?, cuvee_norm = ?, bottle_ml = 375",
      "wine_key = ?", [cuvee, norm, key]);
}
console.log(`Fixed ${CUVEE_SIZE_FIXES.length} demi-bouteille cuvée names + set bottle_ml=375`);

// DELETE cuvee_size for Spanish wine (CVNE Cune Crianza demi)
del('dim_wine', 'wine_key', 'f0d90c9268ab5fb5');
console.log('Deleted: CVNE Cune Crianza demi-bouteille (Spanish wine)');

// cuvee_shop_code: "C5 Stefani Vineyard" from Side Job winery (California) — DELETE
del('dim_wine', 'wine_key', '1630683aa9e8b7ec');
console.log('Deleted: C5 Stefani Vineyard / Side Job (California wine)');

// ─────────────────────────────────────────────────────────────
// SECTION 4: DELETE non-French / garbage dim_producer entries + their dim_wine rows
// ─────────────────────────────────────────────────────────────
console.log('\n--- SECTION 4: Delete non-French / garbage dim_producer entries ---');

// These dim_producer rows are scraped product names or non-French producers
// We delete their dim_wine children first, then the producer row.
const PRODUCER_DELETE_IDS = [
  // producer_packaging — all are gift sets masquerading as producers
  33793,  // "DEUTZ AMOUR COFFRET NACRE"
  33880,  // "DEUTZ AMOUR + COFFRET MAGN"
  34424,  // "#MOUTON CADET BIO COFFRET 2 V. + 1 BT"
  34463,  // "DEUTZ AMOUR COFFRET COMPLICITE + 2 VERRES"
  35489,  // "Coffret Cadeau Découverte Pessac-Léognan"
  38961,  // "Coffret Marie-Jeanne Château Les Carmes Haut-Brion"
  39441,  // "Château Haut Bailly coffret / /"
  39510,  // "Coffret Château Pontet Canet Caisse verticale 12-14-16"
  40138,  // "Château Beauregard Sous Coffret Avec Couteau Laguiole"
  40197,  // "Coffret 5 Etoiles - Premiers Crus Classés De Sauternes Millésime"
  // producer_appellation_tail — "Lalande-de-Pomerol" (appellation stored as producer)
  40228,
  // producer_shop_code — Spanish/Chilean wines
  32564,  // "CAVA VILARNAU DELICAT BRUT RESERVA ORGANIC-C6" (Spanish)
  33902,  // "ALMAVIVA -CB6" (Chilean, Concha y Toro + Rothschild)
  34455,  // "FINCA MONCLOA BARRELS SELECTION -C6" (Spanish, González Byass)
  34117,  // "BIB FRUITS AND WINE AU JUS PAMPLEMOUSSE-C4 7.5%" (flavoured drink)
  57389,  // "C5" (US producer)
  // producer_size — Italian, Portuguese, Australian, other garbage
  32107,  // "Amarone della Valpolicella Classico 37,5cl |"
  32126,  // "Soave Garganega Classico Montefoscarino 37,5cl"
  32158,  // "Valpolicella Classico 37,5cl"
  32187,  // "Ripasso Valpolicella Superiore 37,5cl"
  32304,  // "Ruby Port 37,5cl (half flesje)"
  32343,  // "White Port 37,5cl (half flesje)"
  33199,  // "REMOLE BIANCO FRESCOBALDI 37.5CL"
  34113,  // "REMOLE FRESCOBALDI 37.5CL"
  41995,  // "Magnum Vinhos" (Portuguese, country=PT, 28 wines)
  56747,  // "Balthazar of the Barossa" (Australian)
  32444,  // "Premium Rosé IMPERIALE | Born Bio" (Spanish, Costers del Segre)
  32689,  // "ELEMENTS TERRA 37.50CL" (Spanish Tempranillo)
  39935,  // "37,5cl" (bare size label — no producer name at all)
];

for (const pk of PRODUCER_DELETE_IDS) {
  if (DRY_RUN) {
    console.log(`[DRY] DELETE dim_wine WHERE producer_key=${pk}, then DELETE dim_producer id=${pk}`);
  } else {
    // First find wine_keys for this producer so we can clean up child rows
    const wineKeys = db.prepare('SELECT wine_key FROM dim_wine WHERE producer_key = ?').all(pk).map(r => r.wine_key);
    if (wineKeys.length > 0) {
      const ph = wineKeys.map(() => '?').join(',');
      for (const childTable of ['fact_price', 'fact_rating', 'cellar_inventory', 'cellar_consumption', 'bridge_wine_variety', 'staging_price_candidates']) {
        try { db.prepare(`DELETE FROM ${childTable} WHERE wine_key IN (${ph})`).run(...wineKeys); } catch (_) {}
      }
    }
    const w = db.prepare('DELETE FROM dim_wine WHERE producer_key = ?').run(pk);
    const p = db.prepare('DELETE FROM dim_producer WHERE producer_key = ?').run(pk);
    deleted += (w.changes + p.changes);
    if (p.changes) console.log(`Deleted producer_key=${pk} (+${w.changes} wines)`);
  }
}

// ─────────────────────────────────────────────────────────────
// SECTION 5: FIX producer names (producer_shop_code: extract real producer name)
// ─────────────────────────────────────────────────────────────
console.log('\n--- SECTION 5: Fix producer names ---');

// These dim_producer rows have shop codes or garbage appended to the real producer name
const PRODUCER_NAME_FIXES = [
  // producer_shop_code — strip -C6/-CB6/appellation prefixes
  { id: 31536, name: 'Château Mont-Redon',         norm: 'chateau mont redon' },
  { id: 31787, name: 'Domaine Bachey-Legros',       norm: 'domaine bachey legros' },
  { id: 32714, name: 'Brochet',                     norm: 'brochet' },
  { id: 33250, name: 'Brochet',                     norm: 'brochet' },
  { id: 33255, name: 'Ampelidae',                   norm: 'ampelidae' },
  { id: 33753, name: 'Langlois-Château',            norm: 'langlois chateau' },
  { id: 34071, name: 'Ampelidae',                   norm: 'ampelidae' },
  // producer_vintage|producer_size
  { id: 33801, name: 'Château Clarke',              norm: 'chateau clarke' },
  // producer_size — extract real producer from product name
  { id: 32069, name: 'Joseph Perrier',              norm: 'joseph perrier' },
  { id: 32102, name: '1890',                        norm: '1890' },
  { id: 32138, name: 'Champagne Pannier',           norm: 'champagne pannier' },
  { id: 32154, name: 'Champagne Pannier',           norm: 'champagne pannier' },
  { id: 32423, name: 'Joseph Perrier',              norm: 'joseph perrier' },
  { id: 32715, name: 'Baron Philippe de Rothschild',norm: 'baron philippe de rothschild' },
  { id: 32768, name: 'AIX',                         norm: 'aix' },
  { id: 32862, name: 'Poyet',                       norm: 'poyet' },
  { id: 33552, name: 'Louis Jadot',                 norm: 'louis jadot' },
  { id: 33572, name: 'Louis Jadot',                 norm: 'louis jadot' },
  { id: 33597, name: 'Louis Jadot',                 norm: 'louis jadot' },
  { id: 33944, name: 'Champagne Ayala',             norm: 'champagne ayala' },
  { id: 34300, name: 'Champagne Bollinger',         norm: 'champagne bollinger' },
  { id: 34380, name: 'Baron Philippe de Rothschild',norm: 'baron philippe de rothschild' },
  { id: 34389, name: 'Champagne Bollinger',         norm: 'champagne bollinger' },
  { id: 34390, name: 'Champagne Bollinger',         norm: 'champagne bollinger' },
  { id: 34400, name: 'Champagne Deutz',             norm: 'champagne deutz' },
  { id: 35403, name: 'Moët & Chandon',              norm: 'moet chandon' },
  { id: 35600, name: 'Château Troplong Mondot',     norm: 'chateau troplong mondot' },
  { id: 40693, name: 'Domaine Raymond Usseglio',    norm: 'domaine raymond usseglio' },
];

for (const { id, name, norm } of PRODUCER_NAME_FIXES) {
  upd('dim_producer', "producer_name = ?, producer_norm = ?",
      "producer_key = ?", [name, norm, id]);
}
console.log(`Updated ${PRODUCER_NAME_FIXES.length} producer names`);

// ─────────────────────────────────────────────────────────────
// SUMMARY
// ─────────────────────────────────────────────────────────────
console.log(`\n=== SUMMARY ===`);
console.log(`Deleted: ${deleted} rows`);
console.log(`Updated: ${updated} rows`);
console.log(`Errors:  ${errors}`);
if (DRY_RUN) console.log('\n[DRY RUN — no changes committed]');

db.close();
