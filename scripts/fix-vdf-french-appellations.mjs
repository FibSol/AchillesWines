#!/usr/bin/env node
/**
 * Fix dim_wine rows that are tagged as "Vin de France" but whose cuvée name
 * contains a French appellation name — meaning the scraper assigned the wrong
 * appellation_key.
 *
 * Strategy per wine:
 *   1. Update appellation_key to the correct appellation.
 *   2. Strip the appellation name from the cuvée (prefix or suffix).
 *   3. Rebuild canonical_name and cuvee_norm.
 *
 * Groups handled:
 *   A. Côte-Rôtie (84 wines)   → appellation_key = 299
 *   B. Saint-Joseph (5 wines)  → appellation_key = 270
 *   C. Crozes-Hermitage (1)    → appellation_key = 240
 *   D. Côtes du Rhône (1)      → appellation_key = 242
 *   E. Alsace (1)              → appellation_key = 376
 *   F. Saint-Émilion (4)       → appellation_key = 214 or 804
 *   G. Pouilly-Fumé (2)        → appellation_key = 302
 *   H. Pouilly-Fuissé (1)      → appellation_key = 150
 *   I. Mâcon-Villages (1)      → appellation_key = 366
 *   J. Mâcon-Lugny (1)         → appellation_key = 329
 *   K. Mâcon-Bussières (1)     → appellation_key = 400
 *   L. Gevrey-Chambertin (1)   → appellation_key = 15
 *
 * Not fixed (left as VdF — legitimate VdF cuvée names):
 *   - Domaine Guillot-Broux "Un rouge vibrant en Mâconnais" (VdF by choice)
 *   - "Blanc" / "Châteauneuf du Pape" 2023 (garbled scraper entry — investigate separately)
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const db = new Database(DB_PATH, APPLY ? undefined : { readonly: true });
if (APPLY) db.pragma('foreign_keys = OFF');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

// Strip the appellation from a cuvée name (leading prefix or trailing suffix)
function stripApp(cuvee, appVariants) {
  let out = cuvee;
  // Try trailing " - App" or ", App" (with space before dash)
  for (const v of appVariants) {
    const esc = v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`\\s+[-–—]\\s+${esc}\\s*$`, 'i'), '');
    out = out.replace(new RegExp(`\\s*,\\s*${esc}\\s*$`, 'i'), '');
    // Leading "App " or "App - "
    out = out.replace(new RegExp(`^\\s*${esc}\\s*[-–—]?\\s+`, 'i'), '');
    // Strip producer name embedded in cuvée: "Producer - Cuvee - App" → "Cuvee"
    // Already handled below per case
  }
  // Collapse and trim
  out = out.replace(/\s{2,}/g, ' ');
  out = out.replace(/^\s*[-–—,;:]+\s*/, '');
  out = out.replace(/\s*[-–—,;:]+\s*$/, '');
  return out.trim();
}

// ── Plan entries ──────────────────────────────────────────────────────────────
// Each entry: { key, newAppKey, cuveeFn? }
// cuveeFn(cuvee, producer) → new cuvee_name (or null to compute automatically)

const PLAN = [];

// A. Côte-Rôtie variants (appellation_key = 299)
const COTE_ROTIE_VARIANTS = [
  'Côte-Rôtie', 'Cote-Rotie', 'Côte Rôtie', 'Cote Rotie', 'Côte-Rotie',
];
const COTE_ROTIE_KEYS = [
  // Delas Frères
  '8258677d481651e2','b1d4ba84ecde6b40','31113ade010491a4','d58707e1c18a4197',
  '8fb33a48f3898b82','bb4025abdc48ee33',
  // Domaine Clusel-Roch
  'ed4cf42aef43df3e','e7942d6d0517fb00','9f607a5118d0df55',
  // Domaine de Bonserine
  '470995928ffcd5d7','bb3b149a4eec21ba','118f1bc66c2f3c8a','ccef0a47ef08dd7a',
  // Domaine François Villard
  '53bde4466c5c0592','69311f7edba4f57e',
  // Domaine Georges Vernay
  '053d0eb9e2c4fb03','96c5e069bf029580','0d3710416a58a492',
  '13675a1025149304','a5e8775f8b980b0a','8134cfee79fc0216','c4f6c95778489ab6',
  // Domaine Jean-Michel Stephan
  '95b8a0dc10171386',
  // Domaine Jean-Michel Gerin
  '735e9f91af74fa3a','7c65a455a1942921','9514936683581b18','65473dfbfafc0f1e',
  '5d4bca442fd71654','38a25ccef16680f5','e4f60261ea7e643b','e955b15b339f7707',
  'b17bb3f46dacfd2c','ac576ef413a19b97','60b4aaa77e73b8b7',
  'd61c02a250dbcdb9','28b894b9f2461aed','71fe813ee13ff196','56c5347c6ff8184d',
  // Domaine Pierre Benetière
  'f7d66c20bb263514',
  // Domaine Pierre Gaillard
  'afdf26aa73e08c74',
  // Domaine Rostaing
  'd7feffed6407b6f0',
  // Domaine Stéphane Ogier
  '5d7b319b0cab4a49','6704a1140e96f15d',
  '7e7bc6cd6beae61d','5eb3e112fa4a63d5','090227df47d078b9',
  '56efc392bf9d46e6','5f0d820a6e5d303c',
  // Domaine Yves Cuilleron
  '0857a3049f94a1a9','6d97ff4916fc07ae','ad41a89524c1d735','77b16f7137a51c07',
  '8e2b2fc95b0f9439','97fda0cd08acc0f1','2f4e0a40a4c09e74','9c5d2b56c4458ef9',
  'aee693e5771dbc46',
  // E. Guigal
  '4b9bfdc2061064ac','dc63b816d24e499b','e355e38d15d6b21e','cc2172310c6f3072',
  'eca529357c06b59e','eb4f531d8d396c20','aff01ff6ebccd854','7cdc0c64b45fe16b',
  '31fb6c59d2cf1dbf','3fac279030cc828a','1b042923340dce2e',
  '993c0452a2c22c65','d7934f901035cb27',
  // Domaine Graeme & Julie Bott
  'f7a9204394e595ca',
  // Maison Les Alexandrins
  '3683453b9574975e',
  // Maison M. Chapoutier
  '6fdeb89d7ddaf453','bd94092c743a4e94','f640aa4ee4ed6873','6a5e77c2dfc84097',
  '59a72a7cdd7b7f4d',
  // Michel & Stéphane Ogier
  'db4a02060cb5860d','42bdb5a9f217db91',
  // Vignobles Levet
  '21b33f9fcfc2e661','df5953a229aea7c0','4d477b5414c98417','d130589e83a5834d',
  '183f86488523d9df',
];
for (const key of COTE_ROTIE_KEYS) {
  PLAN.push({
    key, newAppKey: 299,
    stripVariants: COTE_ROTIE_VARIANTS,
    // Also strip producer name prefix like "Jean-Michel Gerin - "
    stripProducerPrefix: true,
  });
}

// B. Saint-Joseph (appellation_key = 270)
const SJ_FIXES = [
  // Vignoble Dauny "Un saint-joseph droit en finesse" — poetic name, keep cuvée but fix app
  { key: '836ed4d6cfc8a681', newCuvee: 'Un saint-joseph droit en finesse' },
  // M. Chapoutier Les Granits Saint-Joseph Blanc
  { key: '0a6e3c20066d1d48', newCuvee: 'Les Granits Blanc' },
  { key: '0d4324de7dfae62e', newCuvee: 'Les Granits Blanc' },
  { key: '6931a3e0e9385d1c', newCuvee: 'Les Granits Blanc' },
  { key: '5e75357aa477f8f5', newCuvee: 'Les Granits Blanc' },
];
for (const f of SJ_FIXES) {
  PLAN.push({ key: f.key, newAppKey: 270, forceCuvee: f.newCuvee });
}

// C. Crozes-Hermitage (appellation_key = 240)
// "M. Chapoutier - Crozes-Ermitage Les Varonniers" → "Les Varonniers"
PLAN.push({
  key: '62953714f9e32313', newAppKey: 240,
  forceCuvee: 'Les Varonniers',
});

// D. Côtes du Rhône (appellation_key = 242)
// Domaine Gramenon "Cotes du Rhone La Sagesse" → "La Sagesse"
PLAN.push({
  key: '97f0c90a424d8b27', newAppKey: 242,
  forceCuvee: 'La Sagesse',
});

// E. Alsace (appellation_key = 376)
// "Alsace Sylvaner Zotzenberg" → "Sylvaner Zotzenberg"
PLAN.push({
  key: 'ca6713da990841c5', newAppKey: 376,
  forceCuvee: 'Sylvaner Zotzenberg',
});

// F. Saint-Émilion (appellation_key = 214) — cuvée = appellation name → clear
const SE_KEYS = [
  '230ee87ca2bdec45', // Château Beauséjour "Saint-Emilion" 2021
  'fd2f67945bb43da8', // Château Bellevue "Saint-Emilion" 2021
  '73a9104b445d852a', // Château Capet-Guillier "Saint Emilion" 2016
  '09dab1dd2644fa63', // Château Yon-Figeac "Saint Emilion" 2017
];
for (const key of SE_KEYS) {
  PLAN.push({ key, newAppKey: 214, forceCuvee: '' });
}

// G. Pouilly-Fumé (appellation_key = 302)
// "AOC Pouilly Fumé" by Dagueneau → clear cuvée
PLAN.push({ key: '852c3517ef93a547', newAppKey: 302, forceCuvee: '' });
// "Michel Redde et fils - Les Bois de Saint-Andelain - Pouilly Fumé" → "Les Bois de Saint-Andelain"
PLAN.push({ key: '4efa4728148c3670', newAppKey: 302, forceCuvee: 'Les Bois de Saint-Andelain' });

// H. Pouilly-Fuissé (appellation_key = 150)
// "Pouilly-Fuissé Joseph Drouhin" → "" (grand vin; producer strip handles "Joseph Drouhin")
PLAN.push({ key: 'f47e1b679c6c2210', newAppKey: 150, forceCuvee: '' });

// I. Mâcon-Villages (appellation_key = 366)
// "Mâcon-Villages Joseph Drouhin" → ""
PLAN.push({ key: 'fe9a86b7a3315c71', newAppKey: 366, forceCuvee: '' });

// J. Mâcon-Lugny (appellation_key = 329)
// "Mâcon-Lugny Les Crays Joseph Drouhin" → "Les Crays"
PLAN.push({ key: '8a44a62506538d77', newAppKey: 329, forceCuvee: 'Les Crays' });

// K. Mâcon-Bussières (appellation_key = 400)
// "Mâcon-Bussières Les Clos Joseph Drouhin" → "Les Clos"
PLAN.push({ key: '6a8d6dcfcb96be69', newAppKey: 400, forceCuvee: 'Les Clos' });

// L. Gevrey-Chambertin (appellation_key = 15)
// "Gevrey-Chambertin, Joseph Drouhin" → ""
PLAN.push({ key: '87aa9a49f5c0863c', newAppKey: 15, forceCuvee: '' });

// ── Helpers ───────────────────────────────────────────────────────────────────
const fetchWine = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.cuvee_norm, w.vintage,
         p.producer_name, p.producer_key
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  WHERE w.wine_key = ?
`);
const fetchApp = db.prepare(`SELECT appellation_name FROM dim_appellation WHERE appellation_key = ?`);

function computeNewCuvee(entry, wine) {
  if ('forceCuvee' in entry) return entry.forceCuvee;
  let cuvee = wine.cuvee_name || '';

  // For Côte-Rôtie group: also strip producer prefix like "Jean-Michel Gerin - "
  if (entry.stripProducerPrefix) {
    const prodEsc = wine.producer_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    cuvee = cuvee.replace(new RegExp(`^\\s*${prodEsc}\\s*[-–—]?\\s*`, 'i'), '');
    // Also strip display variants like "M. Chapoutier - "
    cuvee = cuvee.replace(/^M\.\s*Chapoutier\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Maison\s+M\.\s*Chapoutier\s*-\s*/i, '');
    cuvee = cuvee.replace(/^E\.\s*Guigal\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Guigal\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Graeme\s*&\s*Julie\s*Bott\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Domaine\s+Graeme\s*et\s*Julie\s*Bott\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Les\s+Alexandrins\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Stéphane\s+Ogier\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Domaine\s+Stéphane\s+Ogier\s*-\s*/i, '');
    cuvee = cuvee.replace(/^Michel\s*&\s*Stéphane\s+Ogier\s*-\s*/i, '');
  }

  if (entry.stripVariants) {
    cuvee = stripApp(cuvee, entry.stripVariants);
  }
  return cuvee;
}

// ── Preview ───────────────────────────────────────────────────────────────────
console.log(`=== VdF French-appellation fixes: ${PLAN.length} wines ===\n`);
let found = 0, missing = 0;
for (const entry of PLAN) {
  const wine = fetchWine.get(entry.key);
  if (!wine) { console.log(`  [${entry.key}] NOT FOUND`); missing++; continue; }
  const app = fetchApp.get(entry.newAppKey);
  const newCuvee = computeNewCuvee(entry, wine);
  console.log(`  [${entry.key}] ${wine.producer_name} · ${wine.vintage ?? 'NV'}`);
  console.log(`    cuvée: "${wine.cuvee_name}"  →  "${newCuvee}"`);
  console.log(`    app:   Vin de France  →  ${app?.appellation_name ?? '???'} (${entry.newAppKey})`);
  found++;
}
console.log(`\n  ${found} found, ${missing} not found`);

// ── Apply ─────────────────────────────────────────────────────────────────────
if (APPLY) {
  const upd = db.prepare(`
    UPDATE dim_wine
    SET appellation_key = ?, cuvee_name = ?, cuvee_norm = ?, canonical_name = ?
    WHERE wine_key = ?
  `);

  const tx = db.transaction(() => {
    let changed = 0;
    for (const entry of PLAN) {
      const wine = fetchWine.get(entry.key);
      if (!wine) continue;
      const newCuvee = computeNewCuvee(entry, wine);
      const newNorm = normText(newCuvee);
      const app = fetchApp.get(entry.newAppKey);
      const parts = [wine.producer_name];
      if (newCuvee) parts.push(newCuvee);
      if (wine.vintage) parts.push(String(wine.vintage));
      const newCanonical = parts.join(' ');
      upd.run(entry.newAppKey, newCuvee, newNorm, newCanonical, entry.key);
      console.log(`  Updated [${entry.key}] → "${app?.appellation_name}" | cuvée="${newCuvee}"`);
      changed++;
    }
    return changed;
  });
  const n = tx();
  console.log(`\nApplied ${n} appellation fixes.`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
