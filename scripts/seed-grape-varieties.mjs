#!/usr/bin/env node
/**
 * Seed dim_variety with the canonical French grape varieties.
 *
 * Reference: ONIVINS — https://onivins.fr/vin-cepage/ and https://onivins.fr/cepage-bourgogne/
 * Cross-checked against the INAO list of cépages autorisés in French AOC/AOP.
 *
 * Each row: official French name, normalized form, color family.
 * Color enum (matches schema): "red", "white", "rosé", "other"
 *   — Pinot Gris is filed as "white" since its juice produces white wine despite the grey skin.
 *
 * Idempotent: uses INSERT OR IGNORE on (variety_norm) unique index.
 *
 * Pass --apply to mutate. Defaults to dry-run.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const VARIETIES = [
  // ----- REDS (rouges) -----
  // Burgundy + Champagne
  ['Pinot Noir', 'red'],
  ['Pinot Meunier', 'red'],
  ['Gamay', 'red'],
  ['César', 'red'],

  // Bordeaux + Southwest
  ['Cabernet Sauvignon', 'red'],
  ['Merlot', 'red'],
  ['Cabernet Franc', 'red'],
  ['Petit Verdot', 'red'],
  ['Malbec', 'red'],         // a.k.a. Côt
  ['Carmenère', 'red'],
  ['Tannat', 'red'],         // Madiran
  ['Négrette', 'red'],       // Fronton
  ['Fer Servadou', 'red'],   // Marcillac

  // Rhône + Languedoc + Provence
  ['Syrah', 'red'],          // a.k.a. Shiraz
  ['Grenache', 'red'],       // a.k.a. Grenache Noir, Garnacha
  ['Mourvèdre', 'red'],      // a.k.a. Monastrell
  ['Cinsault', 'red'],
  ['Carignan', 'red'],
  ['Counoise', 'red'],
  ['Muscardin', 'red'],
  ['Vaccarèse', 'red'],
  ['Terret Noir', 'red'],

  // Loire
  ['Pineau d\'Aunis', 'red'],
  ['Grolleau', 'red'],

  // Savoie + Jura
  ['Mondeuse', 'red'],
  ['Poulsard', 'red'],
  ['Trousseau', 'red'],

  // ----- WHITES (blancs) -----
  // Burgundy + Champagne
  ['Chardonnay', 'white'],
  ['Aligoté', 'white'],
  ['Pinot Blanc', 'white'],
  ['Melon de Bourgogne', 'white'],   // Muscadet base
  ['Sacy', 'white'],                 // a.k.a. Tressallier (rare, Allier/St-Pourçain)

  // Bordeaux + Southwest
  ['Sauvignon Blanc', 'white'],
  ['Sémillon', 'white'],
  ['Muscadelle', 'white'],
  ['Sauvignon Gris', 'white'],
  ['Petit Manseng', 'white'],        // Jurançon
  ['Gros Manseng', 'white'],
  ['Courbu', 'white'],
  ['Petit Courbu', 'white'],
  ['Mauzac', 'white'],               // Limoux, Gaillac
  ['Len de l\'El', 'white'],         // Gaillac

  // Alsace
  ['Riesling', 'white'],
  ['Gewurztraminer', 'white'],
  ['Pinot Gris', 'white'],           // grey-skinned but vinified white
  ['Sylvaner', 'white'],
  ['Muscat Blanc à Petits Grains', 'white'],
  ['Muscat Ottonel', 'white'],
  ['Klevener de Heiligenstein', 'white'],   // a.k.a. Savagnin Rose

  // Rhône + Languedoc + Provence
  ['Viognier', 'white'],             // Condrieu
  ['Marsanne', 'white'],
  ['Roussanne', 'white'],
  ['Grenache Blanc', 'white'],
  ['Bourboulenc', 'white'],
  ['Clairette', 'white'],
  ['Picpoul', 'white'],              // a.k.a. Piquepoul (Picpoul de Pinet)
  ['Vermentino', 'white'],           // a.k.a. Rolle (Provence)
  ['Maccabeu', 'white'],             // Roussillon

  // Loire
  ['Chenin Blanc', 'white'],
  ['Folle Blanche', 'white'],        // Armagnac, Gros Plant
  ['Romorantin', 'white'],           // Cour-Cheverny

  // Cognac / Armagnac base + bulk
  ['Ugni Blanc', 'white'],           // a.k.a. Trebbiano
  ['Colombard', 'white'],

  // Jura
  ['Savagnin', 'white'],             // Vin Jaune
  ['Savagnin Rose', 'white'],

  // Savoie
  ['Jacquère', 'white'],
  ['Altesse', 'white'],              // Roussette de Savoie
  ['Roussanne', 'white'],            // duplicate intentional skipped — already above
  ['Chasselas', 'white'],            // Crépy, Pouilly-sur-Loire

  // Champagne (rare permitted varieties beyond the big 3)
  ['Arbane', 'white'],
  ['Petit Meslier', 'white'],
  ['Pinot Blanc Vrai', 'white'],     // Champagne synonym for Pinot Blanc
];

function normText(s) {
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

const existing = new Set(
  db.prepare('SELECT variety_norm FROM dim_variety').all().map(r => r.variety_norm)
);

const ins = db.prepare(`
  INSERT OR IGNORE INTO dim_variety (variety_name, variety_norm, color_family)
  VALUES (?, ?, ?)
`);

let added = 0;
let skipped = 0;
const plan = [];
const seen = new Set();

for (const [name, color] of VARIETIES) {
  const norm = normText(name);
  if (seen.has(norm)) continue;        // dedup the array itself
  seen.add(norm);
  if (existing.has(norm)) { skipped++; continue; }
  plan.push({ name, norm, color });
}

console.log(`Reference list size : ${VARIETIES.length}`);
console.log(`Already in dim_variety : ${skipped}`);
console.log(`Would insert        : ${plan.length}\n`);
for (const p of plan.slice(0, 20)) {
  console.log(`  + ${p.name.padEnd(34)} ${p.color}`);
}
if (plan.length > 20) console.log(`  … and ${plan.length - 20} more`);

if (APPLY) {
  const tx = db.transaction(() => {
    for (const p of plan) {
      const r = ins.run(p.name, p.norm, p.color);
      if (r.changes > 0) added++;
    }
  });
  tx();
  console.log(`\nApplied: inserted ${added} new varieties.`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
