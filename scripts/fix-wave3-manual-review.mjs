#!/usr/bin/env node
/**
 * Wave 3 manual-review cleanup.
 *
 * Categories handled:
 *  1. producer_vintage (49): "Producer : Appellation [Domaine/Maison] YYYY" → colon split,
 *     strip year, move wines to real producer, delete fake producer.
 *  2. producer_packaging (38): all coffret gift sets → DELETE (not wine products).
 *  3. producer_size (26): size-label producers → rescue wines to real producers, delete.
 *  4. cuvee_packaging (7): strip "EN ETUI"/"en Etui" from cuvée name.
 *  5. cuvee_size (5): strip "Demi-bouteille" etc., set bottle_ml=375, delete non-French.
 *  6. producer_classification_tail (2): SKIP (no producer identity in name).
 *  7. producer_appellation_tail (1): strip "(Pomerol)" from "Clos l'Église (Pomerol)".
 *  8. cuvee_classification (1): clear "Cru Classe" cuvée.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import fs from 'fs';
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const db = new Database(DB_PATH, APPLY ? undefined : { readonly: true });
if (APPLY) db.pragma('foreign_keys = OFF');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const fetchProd = db.prepare('SELECT producer_key, producer_name FROM dim_producer WHERE producer_key=?');
const fetchWines = db.prepare('SELECT w.wine_key, w.cuvee_name, w.vintage, w.bottle_ml, a.appellation_name FROM dim_wine w JOIN dim_appellation a ON a.appellation_key=w.appellation_key WHERE w.producer_key=?');
const champagneAppKey = db.prepare("SELECT appellation_key FROM dim_appellation WHERE appellation_name='Champagne' LIMIT 1").get()?.appellation_key;

// ── Plan storage ──────────────────────────────────────────────────────────────
const WINE_UPDATES = [];  // { wineKey, newPk, newCuvee, newBottleMl }
const PROD_DELETES = [];  // fakePk
const WINE_DELETES = [];  // wineKey (non-French etc.)
const PROD_UPDATES = [];  // { pk, newName, newNorm }
const CUVEE_UPDATES = []; // { wineKey, newCuvee, newCuveeNorm }

// ── 1. producer_vintage — hardcoded plan ─────────────────────────────────────
// Format: [fakePk, realProducerPk, extractedCuvee]
// Real producer pks from lookup session
const VINTAGE_FIXES = [
  // ALLCAPS standalone
  [33130, 'CREATE:Château Belle Croix', ''],        // BELLE CROIX 2023 ROUGE LALANDE DE POMEROL
  [33162, 58569, ''],                                // SAUMUR CHAMPIGNY DOM LANGLOIS CHATEAU 2018
  [37635, 458, 'Y'],                                 // Y 2017 → Château d'Yquem
  [39689, 33779, 'Baron de L'],                      // Domaine de Ladoucette 2022 Baron de L
  [39969, 6927, ''],                                 // Domaine des Pothiers Cuvée Domaine 2023
  [40039, 7332, ''],                                 // Domaine Des Roches Neuves Thierry Germain 2023
  // DELETE (non-French)
  [38604, 'DELETE', ''],                             // VIK 2022 (Chilean)
  [39896, 'DELETE', ''],                             // Epu 2020 (Chilean/Almaviva)
  // Colon-format + year
  [33663, 33603, ''],                                // Bouchard : Monthélie Village Domaine 2020
  [33811, 34811, ''],                                // Les Alexandrins : Crozes-Hermitage Maison 2023
  [34207, 33603, ''],                                // Bouchard : Pommard Village Domaine 2022
  [34211, 33603, ''],                                // Bouchard : Meursault Village Domaine 2022
  [34561, 33603, ''],                                // Bouchard : Aloxe-Corton Village Domaine 2022
  [35111, 34811, ''],                                // Les Alexandrins : Hermitage Maison 2022
  [35424, 34811, ''],                                // Les Alexandrins : Côte-Rôtie Maison 2023
  [35427, 34811, ''],                                // Les Alexandrins : Saint-Joseph Maison 2024
  [35505, 602, ''],                                  // Jean-Louis Chave : Hermitage Domaine 2023
  [35510, 294, ''],                                  // Domaine du Colombier : Crozes-Hermitage 2024
  [35538, 306, 'En Mortperay'],                      // A.F. Gros : Moulin-à-Vent "En Mortperay" 2022
  [35553, 58074, 'Clos du Château'],                 // Domaine du Château de Meursault 2023
  [36196, 33603, 'Les Clous'],                       // Bouchard : Meursault "Les Clous" 2022
  [36380, 491, 'Le Château'],                        // Vincent Pinard : Le Château 2023
  [36602, 306, ''],                                  // A.F. Gros : Bourgogne HCN Domaine 2024
  [36831, 602, ''],                                  // Jean-Louis Chave : Saint-Joseph Domaine 2023
  [36936, 40, ''],                                   // Méo-Camuzet : Vosne-Romanée Village 2019
  [37017, 6, ''],                                    // William Fèvre : Chablis Village 2023
  [37347, 58101, ''],                                // Poisot : Pernand-Vergelesses Village 2023
  [37439, 33977, 'Clos Latin'],                      // Gallety : Clos Latin Domaine 2017
  [37480, 492, 'Vintage'],                           // Krug : Vintage 2002
  [37635, 458, 'Y'],                                 // Y 2017 (already above, deduped later)
  [38142, 25, ''],                                   // Dujac : Morey-Saint-Denis Village 2023
  [38378, 33977, 'La Ligure'],                       // Gallety : La Ligure Domaine 2017
  [38484, 2697, 'Ma Vigne de 1955'],                 // Bruno Colin : Chassagne 2023
  [38525, 306, ''],                                  // A.F. Gros : Chambolle-Musigny Village 2023
  [38616, 33977, 'La Syrare'],                       // Gallety : La Syrare Domaine 2020
  [38836, 37, 'Les Vignots'],                        // Leroy : Pommard "Les Vignots" 2014
  [38845, 306, 'Signature Mathias Parent'],          // A.F. Gros : Signature Mathias Parent 2023
  [39088, 40, 'Cuvée Etienne Camuzet'],              // Méo-Camuzet : Cuvée Etienne Camuzet 2023
  [39123, 37, 'Les Genaivrières'],                   // Leroy : Vosne-Romanée "Les Genaivrières" 2006
  [39130, 37, ''],                                   // Leroy : Nuits-Saint-Georges Village 2008
  [39135, 37, 'Aux Allots'],                         // Leroy : Nuits-Saint-Georges "Aux Allots" 2011
  [59245, 33603, 'du Château'],                      // Bouchard : Beaune 1er "du Château" 2012
  [59850, 33603, ''],                                // Bouchard : Clos Vougeot Grand cru 2020
  [60004, 343, 'Clos des Mouches'],                  // Chanson : Beaune "Clos des Mouches" 2022
  [60251, 63386, 'Les Clous'],                       // Vignoble des Cabottes : Meursault "Les Clous" 2023
  [60465, 33603, ''],                                // Bouchard : Montrachet Grand cru 2019
  [61150, 33603, ''],                                // Bouchard : Chambertin Grand cru 2017
  [61163, 63386, 'Genevrières'],                     // Vignoble des Cabottes : Meursault 1er cru 2023
  [61244, 306, ''],                                  // A.F. Gros : Richebourg Grand cru 2023
  [61529, 63386, ''],                                // Vignoble des Cabottes : Montrachet Grand cru 2023
];
// Deduplicate (pk=37635 appears twice above)
const seenPv = new Set();
for (const [fakePk, realPk, cuvee] of VINTAGE_FIXES) {
  if (seenPv.has(fakePk)) continue;
  seenPv.add(fakePk);
  if (realPk === 'DELETE') {
    const ws = fetchWines.all(fakePk);
    ws.forEach(w => WINE_DELETES.push(w.wine_key));
    PROD_DELETES.push(fakePk);
  } else {
    const wines = fetchWines.all(fakePk);
    wines.forEach(w => WINE_UPDATES.push({ wineKey: w.wine_key, newPk: realPk, newCuvee: cuvee }));
    PROD_DELETES.push(fakePk);
  }
}

// ── 2. producer_packaging — all coffrets DELETE ───────────────────────────────
const COFFRET_PKS = [
  59306,59308,59392,59393,59394,59397,59463,59464,59472,59498,59553,59557,
  59582,59717,59800,59955,59957,60192,60225,60308,60470,60476,60525,60713,
  60938,60978,61021,61161,61178,61213,61336,61409,61439,61449,61544,61547,
  61567,61572,
];
for (const pk of COFFRET_PKS) {
  const ws = fetchWines.all(pk);
  ws.forEach(w => WINE_DELETES.push(w.wine_key));
  PROD_DELETES.push(pk);
}

// ── 3. producer_size fixes ────────────────────────────────────────────────────

// pk=621 "Domaine Franck Balthazar" — FALSE POSITIVE (Balthazar = winemaker surname)
// pk=63166 "Domaine FRANCK BALTHAZAR CUVEE" — also false positive
// These are real producers; skip them.

// Size-label producers with rescuable wines
// Format: [fakePk, wineKey, realProducerPkOrCreate, cuvee]
const SIZE_WINE_RESCUES = [
  // pk=61669 "Magnum"
  ['7a75d8038244ee8b', 61667, ''],                                         // Petit Chablis (Domaine Christophe & Fils pk=61667)
  ['878c503f955c1516', 33799, 'Les Closiers'],                           // Saumur
  ['fccf90ba3ecccc31', 33799, 'Les Coudraies'],                         // Saumur
  ['284d17a130823966', 33799, 'Les Trezellières'],                      // Saumur
  // ['f566e53fd69d37de', 'DELETE', ''],  // "Châteauneuf-du-Pape Rouge" — no producer info
  // ['5c8423684cfd82f6', 'DELETE', ''], // "Carte d'Or Brut" — no producer info
  // ['8f776f6b9a4b9c49', 'DELETE', ''], // "Rosé de Saignée" — no producer info
  ['5ef4e5200aa5bde9', 609, 'Cap Nord'],                                 // Combier, Hermitage
  ['ed24d97fc16a59b3', 7268, 'Cuvée Papillon'],                         // Gilles Robin, Hermitage
  ['c66c68d7139fd5d8', 1656, 'Kamaka'],                                  // Graeme et Julie Bott, IGP
  ['f36115f43db327b6', 61684, 'Roussanne vieilles vignes'],              // Clos des Centenaires, CdN

  // pk=61661 "37,5 cl"
  ['e76aa34a30f7d579', 39934, 'La Croix Des Moines'],                    // Trocard, Pomerol
  ['bda2a361d9168e75', 39934, 'Clos la Vieille Eglise'],                // Trocard, Pomerol
  ['fcd9c342d662d07e', 39934, 'Franc la Rose'],                         // Trocard, VdF

  // pk=61696 "50 cl"
  ['07c4f1aeb29d4e4d', 3403, 'Grenat'],                                  // Escaravailles, Rasteau
  ['888b0e1f602224c1', 35203, "L'Erme de Centeilles"],                  // Clos Centeilles, Minervois

  // pk=61710 "75 cl"
  ['7d5d4598d95a5b4f', 35203, 'Capitelle de Centeilles'],               // Clos Centeilles, Minervois

  // pk=61715 "50cl"
  ['13d224d7f56e03a0', 'CREATE:Domaine Marion Pla', ''],                // VdF
  ['2df1a7fae667b41a', 7048, 'Terrement Liquoreux'],                    // Château Puy-Servain, Montravel
  ['4d2a540c722e0bff', 41727, 'Vin de Liqueur Tannat Vintage'],         // Famille Laplace

  // pk=61728 "62cl"
  ['b142ac07a0084bfc', 672, ''],                                         // Berthet-Bondet, Château Chalon

  // pk=61749 "70 cl"
  ['bae3c667dae25e87', 521, ''],                                         // Drappier (cuvée IS producer name)
];

// Delete wines from size producers that can't be rescued (no producer info)
const SIZE_WINE_DELETES = [
  'f566e53fd69d37de',  // "Châteauneuf-du-Pape Rouge" Magnum — no producer info
  '5c8423684cfd82f6',  // "Carte d'Or Brut" Champagne — no producer info
  '8f776f6b9a4b9c49',  // "Rosé de Saignée" Champagne — no producer info
];
WINE_DELETES.push(...SIZE_WINE_DELETES);

for (const [wineKey, realPk, cuvee] of SIZE_WINE_RESCUES) {
  WINE_UPDATES.push({ wineKey, newPk: realPk, newCuvee: cuvee });
}

// Delete fake size-label producers after rescue
const SIZE_FAKE_PKS = [61669, 61661, 61696, 61710, 61715, 61728, 61749];
PROD_DELETES.push(...SIZE_FAKE_PKS);

// Other producer_size fixes (not pure size labels):
// Magnum/size embedded in producer name → move to real producer, strip size from cuvée
const SIZE_PROD_FIXES = [
  // [fakePk, realProdPk, cuvee]
  [60509, 1812, 'La Croisée des Chemins'],           // La Croisée des Chemins en Magnum - Le Brun de Neuville
  [60515, 'CREATE:Champagne Moussé', 'Eugène'],      // Eugène en Magnum - Champagne Moussé
  [60529, 'CREATE:Champagne Moussé', "L'Esquisse"],  // L'Esquisse - Magnum - Champagne Moussé
  [60544, 1812, 'Oenothèque n°04 Côte Brute'],       // Oenothèque n°04 en Magnum - Le Brun de Neuville
  [60567, 60497, 'Fleur de Craie'],                  // Champagne Barrat Masson Fleur de Craie - Magnum
  [60574, 1812, 'Autolyse Noirs et Blancs'],         // Autolyse Noirs et Blancs en Magnum - Le Brun de Neuville
  [60594, 4579, 'Cuvée 748'],                        // Champagne Jacquesson Cuvée 748 en Magnum
  [60636, 521, 'Brut nature'],                       // Brut nature - Magnum - Champagne Drappier
  [60653, 4579, 'Cuvée 749'],                        // Champagne Jacquesson Cuvée 749 - Magnum
  [60667, 4579, 'Cuvée 744 Dégorgement tardif'],     // Jacquesson n°744 Dégorgement tardif - Magnum
  [60796, 576, 'Pinot Gris Clos Jebsal SGN'],        // Zind-Humbrecht (demi bouteille)
  [61086, 6520, 'Brut Selection'],                   // Pannier Champagne Brut Selection 150cl
  [61087, 6520, 'Brut Selection'],                   // Pannier Champagne Brut Selection Salmanazar
  [61142, 'CREATE:Born Bio', 'Premium Rosé Impériale'],  // Premium Rosé IMPERIALE | Born Bio
  [61661, 39934, ''],                                // already handled above (37.5cl producer_key)
  [61778, 505, 'Brut Classic'],                      // Deutz Brut Classic Magnum
  [62243, 77, 'Clos de Malte Rouge'],                // Santenay Clos De Malte Rouge Jadot 37.5Cl
  [62359, 40392, 'Rosé'],                            // Bollinger Rose Jeroboam
  [61142, 'CREATE:Born Bio', 'Premium Rosé Impériale'],  // duplicate — skip
];
const seenSp = new Set();
for (const [fakePk, realPk, cuvee] of SIZE_PROD_FIXES) {
  if (seenSp.has(fakePk)) continue;
  seenSp.add(fakePk);
  const wines = fetchWines.all(fakePk);
  wines.forEach(w => WINE_UPDATES.push({ wineKey: w.wine_key, newPk: realPk, newCuvee: cuvee }));
  PROD_DELETES.push(fakePk);
}

// Also fix the "Born Bio DOUBLE" entry (pk=31727) — same pattern
WINE_UPDATES.push(...fetchWines.all(31727).map(w => ({ wineKey: w.wine_key, newPk: 'CREATE:Born Bio', newCuvee: 'Premium Rosé Double' })));
PROD_DELETES.push(31727);

// ── 4. cuvee_packaging — strip "EN ETUI"/"en Etui" ──────────────────────────
// Also fix Deutz VdF entries: fix producer + appellation + cuvée
// wine_key → { newCuvee, fixAppellation?, fixProducer? }
const CUVEE_PKG_FIXES = [
  // Veuve Clicquot — just strip etui from cuvée
  { wineKey: '16479cfb1e465439', newCuvee: 'Brut Carte Jaune' },
  { wineKey: 'd3171b25d6742825', newCuvee: 'Rosé Vintage' },
  // Taittinger
  { wineKey: '3dcebeaec2f15247', newCuvee: 'Brut Prestige Rosé' },
  // Deutz "EN ETUI" with VdF appellation → clear cuvée + fix appellation
  { wineKey: 'fa9da37fa9ef5da3', newCuvee: '', fixProducerPk: 505, fixAppKey: champagneAppKey },
  { wineKey: '746ce71dd373375a', newCuvee: '', fixProducerPk: 505, fixAppKey: champagneAppKey },
  { wineKey: '565499b97fc883db', newCuvee: '', fixProducerPk: 505, fixAppKey: champagneAppKey },
  // Champagne Deutz (correct appellation already)
  { wineKey: '334dbfc0f7ba7369', newCuvee: '' },
];
for (const fix of CUVEE_PKG_FIXES) {
  if (fix.fixProducerPk || fix.fixAppKey) {
    WINE_UPDATES.push({ wineKey: fix.wineKey, newPk: fix.fixProducerPk, newCuvee: fix.newCuvee, fixAppKey: fix.fixAppKey });
  } else {
    CUVEE_UPDATES.push({ wineKey: fix.wineKey, newCuvee: fix.newCuvee });
  }
}

// Also delete the fake "DEUTZ BRUT CLASSIC" and "Deutz Brut Rose" producers
// Their wines were just remapped above; delete the fake producers
const DEUTZ_FAKE_PKS_IN_DETAIL = db.prepare(`
  SELECT producer_key FROM dim_producer
  WHERE producer_name IN ('DEUTZ BRUT CLASSIC','Deutz Brut Rose','Deutz Brut Rose')
`).all().map(r => r.producer_key);
PROD_DELETES.push(...DEUTZ_FAKE_PKS_IN_DETAIL);

// ── 5. cuvee_size fixes ───────────────────────────────────────────────────────
// Non-French → DELETE
WINE_DELETES.push('0c257d7f9118fd28'); // Kracher (Austrian)
// Gift set variant → DELETE
WINE_DELETES.push('16e5b301d1f15d43'); // Billecart gift set demi-bouteille

// Guigal "Demi-bouteille - Brune et Blonde" → strip prefix, set bottle_ml=375
CUVEE_UPDATES.push({ wineKey: '5fbf0283a4f13b15', newCuvee: 'Brune et Blonde', newBottleMl: 375 });

// Clos des Fées "Passat Minor - Demi bouteille - Domaine du Clos des Fées" → fix cuvée
CUVEE_UPDATES.push({ wineKey: '1ce64687620a4aae', newCuvee: 'Passat Minor', newBottleMl: 375 });

// Champagne Haton "Demi Bouteille - Champagne Haton et Filles - Cadence Brut" → fix
CUVEE_UPDATES.push({ wineKey: '0528fc48a6a6c8f2', newCuvee: 'Cadence Brut', newBottleMl: 375 });

// ── 6. producer_appellation_tail (1) ─────────────────────────────────────────
// "Clos l'Église (Pomerol)" pk=58411 — clean version "Clos l'Eglise" already exists as pk=2606
// → move wines to pk=2606 and delete fake pk=58411
fetchWines.all(58411).forEach(w => WINE_UPDATES.push({ wineKey: w.wine_key, newPk: 2606, newCuvee: w.cuvee_name === 'n/a' ? '' : (w.cuvee_name || '') }));
PROD_DELETES.push(58411);

// ── 7. cuvee_classification (1) ──────────────────────────────────────────────
CUVEE_UPDATES.push({ wineKey: 'f1bc10ce715fda6f', newCuvee: '' });

// ── Preview ───────────────────────────────────────────────────────────────────
console.log(`=== Wave 3 Fix Plan ===`);
console.log(`  wine_updates: ${WINE_UPDATES.length}`);
console.log(`  wine_deletes: ${WINE_DELETES.length}`);
console.log(`  prod_deletes: ${PROD_DELETES.length}`);
console.log(`  prod_updates: ${PROD_UPDATES.length}`);
console.log(`  cuvee_updates: ${CUVEE_UPDATES.length}`);

// Show samples
const createNeeded = WINE_UPDATES.filter(u => typeof u.newPk === 'string' && u.newPk.startsWith('CREATE:'));
console.log(`\n  New producers to create: ${[...new Set(createNeeded.map(u => u.newPk))].join(', ')}`);

console.log('\n--- Wine update sample (10) ---');
WINE_UPDATES.slice(0, 10).forEach(u => {
  const w = db.prepare('SELECT wine_key, cuvee_name, vintage FROM dim_wine WHERE wine_key=?').get(u.wineKey);
  const p = db.prepare('SELECT producer_name FROM dim_producer WHERE producer_key=?').get(typeof u.newPk === 'number' ? u.newPk : null);
  console.log(`  [${u.wineKey}] "${w?.cuvee_name||''}" ${w?.vintage??'NV'} → pk=${u.newPk} "${p?.producer_name||'?'}" cuvée="${u.newCuvee}"`);
});

console.log('\n--- Cuvee updates ---');
CUVEE_UPDATES.forEach(u => {
  const w = db.prepare('SELECT wine_key, cuvee_name, vintage FROM dim_wine WHERE wine_key=?').get(u.wineKey);
  console.log(`  [${u.wineKey}] "${w?.cuvee_name||''}" → "${u.newCuvee}"${u.newBottleMl ? ` (${u.newBottleMl}ml)` : ''}`);
});

console.log('\n--- Prod updates ---');
PROD_UPDATES.forEach(u => {
  const p = fetchProd.get(u.pk);
  console.log(`  [pk=${u.pk}] "${p?.producer_name}" → "${u.newName}"`);
});

if (!APPLY) { console.log('\n(Dry-run — re-run with --apply to mutate.)'); db.close(); process.exit(0); }

// ── Apply ─────────────────────────────────────────────────────────────────────
const insertProd = db.prepare("INSERT INTO dim_producer (producer_name, producer_norm, country_code, allowed_appellations, aliases) VALUES (?, ?, 'FR', '[]', '[]')");
const updWine = db.prepare('UPDATE dim_wine SET producer_key=?, cuvee_name=?, cuvee_norm=?, canonical_name=? WHERE wine_key=?');
const updWineApp = db.prepare('UPDATE dim_wine SET producer_key=?, appellation_key=?, cuvee_name=?, cuvee_norm=? WHERE wine_key=?');
const updCuvee = db.prepare('UPDATE dim_wine SET cuvee_name=?, cuvee_norm=?, canonical_name=? WHERE wine_key=?');
const updCuveeWithMl = db.prepare('UPDATE dim_wine SET cuvee_name=?, cuvee_norm=?, bottle_ml=? WHERE wine_key=?');
const delWine = db.prepare('DELETE FROM dim_wine WHERE wine_key=?');
const delProd = db.prepare('DELETE FROM dim_producer WHERE producer_key=?');
const updProdName = db.prepare('UPDATE dim_producer SET producer_name=?, producer_norm=? WHERE producer_key=?');
const deleteChildrenAndProd = (pk) => {
  ['fact_price','fact_rating','cellar_inventory','cellar_consumption','bridge_wine_variety','staging_price_candidates'].forEach(t => {
    db.prepare(`DELETE FROM ${t} WHERE wine_key IN (SELECT wine_key FROM dim_wine WHERE producer_key=?)`).run(pk);
  });
};

const createdProds = new Map();
function resolveOrCreate(pkOrCreate) {
  if (typeof pkOrCreate === 'number') return pkOrCreate;
  const name = pkOrCreate.replace('CREATE:', '');
  if (createdProds.has(name)) return createdProds.get(name);
  const newPk = insertProd.run(name, normText(name)).lastInsertRowid;
  createdProds.set(name, newPk);
  console.log(`  Created [pk=${newPk}] "${name}"`);
  return newPk;
}

const tx = db.transaction(() => {
  // Wine updates
  for (const upd of WINE_UPDATES) {
    const realPk = resolveOrCreate(upd.newPk);
    const prodRow = fetchProd.get(realPk);
    const prodName = prodRow?.producer_name || '';
    const w = db.prepare('SELECT vintage FROM dim_wine WHERE wine_key=?').get(upd.wineKey);
    if (!w) continue;
    const canon = [prodName, upd.newCuvee, w.vintage].filter(x=>x!==null&&x!==undefined&&x!=='').join(' ').trim();
    if (upd.fixAppKey) {
      updWineApp.run(realPk, upd.fixAppKey, upd.newCuvee, normText(upd.newCuvee), upd.wineKey);
    } else {
      updWine.run(realPk, upd.newCuvee, normText(upd.newCuvee), canon, upd.wineKey);
    }
  }

  // Cuvee-only updates
  for (const upd of CUVEE_UPDATES) {
    const w = db.prepare('SELECT vintage, producer_key FROM dim_wine WHERE wine_key=?').get(upd.wineKey);
    if (!w) continue;
    if (upd.newBottleMl) {
      updCuveeWithMl.run(upd.newCuvee, normText(upd.newCuvee), upd.newBottleMl, upd.wineKey);
    } else {
      const prod = fetchProd.get(w.producer_key);
      const canon = [prod?.producer_name||'', upd.newCuvee, w.vintage].filter(x=>x!==null&&x!==undefined&&x!=='').join(' ').trim();
      updCuvee.run(upd.newCuvee, normText(upd.newCuvee), canon, upd.wineKey);
    }
  }

  // Producer name updates
  for (const upd of PROD_UPDATES) {
    updProdName.run(upd.newName, upd.newNorm, upd.pk);
  }

  // Wine deletes
  const wineDeleteSet = new Set(WINE_DELETES);
  for (const wineKey of wineDeleteSet) {
    ['fact_price','fact_rating','cellar_inventory','cellar_consumption','bridge_wine_variety','staging_price_candidates'].forEach(t => {
      db.prepare(`DELETE FROM ${t} WHERE wine_key=?`).run(wineKey);
    });
    delWine.run(wineKey);
  }

  // Producer deletes (all wines already moved)
  const prodDeleteSet = new Set(PROD_DELETES);
  for (const pk of prodDeleteSet) {
    delProd.run(pk);
  }

  // Clean orphan producers
  const orphans = db.prepare(`
    DELETE FROM dim_producer WHERE producer_key IN (
      SELECT producer_key FROM dim_producer p
      WHERE NOT EXISTS (SELECT 1 FROM dim_wine w WHERE w.producer_key = p.producer_key)
    )
  `).run();

  console.log(`\nWine updates: ${WINE_UPDATES.length}`);
  console.log(`Cuvee updates: ${CUVEE_UPDATES.length}`);
  console.log(`Wine deletes: ${wineDeleteSet.size}`);
  console.log(`Producer deletes: ${prodDeleteSet.size}`);
  console.log(`Producer name updates: ${PROD_UPDATES.length}`);
  console.log(`New producers created: ${createdProds.size}`);
  console.log(`Orphaned producers cleaned: ${orphans.changes}`);
});

tx();
console.log('\nDone. Run the cleanup pipeline next.');
db.close();
