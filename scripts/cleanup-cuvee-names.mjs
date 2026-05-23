#!/usr/bin/env node
/**
 * Data-quality cleanup for dim_wine rows.
 *
 * Fixes:
 *  - cuvée_name contaminated with vintage years        → vintage column already has it, strip
 *  - cuvée_name contaminated with appellation tails    → keep appellation_key, strip from name
 *  - cuvée_name contaminated with classification       → extract into `classification` column
 *  - cuvée_name == producer (grand vin)                → cuvée becomes empty string (display = producer)
 *  - canonical_name rebuilt = producer [cuvée] [vintage]
 *  - cuvee_norm recomputed
 *
 * Defaults to DRY-RUN. Pass --apply to mutate the DB.
 * Pass --limit N to preview the first N changed rows.
 *
 *  node scripts/cleanup-cuvee-names.mjs                # dry-run summary
 *  node scripts/cleanup-cuvee-names.mjs --limit 50     # dry-run + sample
 *  node scripts/cleanup-cuvee-names.mjs --apply        # write changes
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const SAMPLE_LIMIT = (() => {
  const i = argv.indexOf('--limit');
  return i >= 0 ? parseInt(argv[i + 1], 10) || 25 : 25;
})();
const FILTER = (() => {
  const i = argv.indexOf('--filter');
  return i >= 0 ? (argv[i + 1] || '').toLowerCase() : null;
})();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

// ---------- normalization helpers (mirror lib/identity.ts) ----------

function normText(s) {
  if (!s) return '';
  return s.normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// Classification phrases — order matters (more specific first).
const CLASSIFICATION_PATTERNS = [
  { re: /\b1\s*er\s+Grand\s+Cru\s+Class[ée]\s+A\b/i,        canon: '1er Grand Cru Classé A' },
  { re: /\b1\s*er\s+Grand\s+Cru\s+Class[ée]\s+B\b/i,        canon: '1er Grand Cru Classé B' },
  { re: /\b1\s*er\s+Grand\s+Cru\s+Class[ée]\b/i,            canon: '1er Grand Cru Classé' },
  { re: /\bPremier\s+Grand\s+Cru\s+Class[ée]\s+A\b/i,       canon: '1er Grand Cru Classé A' },
  { re: /\bPremier\s+Grand\s+Cru\s+Class[ée]\s+B\b/i,       canon: '1er Grand Cru Classé B' },
  { re: /\bPremier\s+Grand\s+Cru\s+Class[ée]\b/i,           canon: '1er Grand Cru Classé' },
  { re: /\bGrand\s+Cru\s+Class[ée]\b/i,                     canon: 'Grand Cru Classé' },
  { re: /\b1\s*er\s+Cru\s+Class[ée]\b/i,                    canon: '1er Cru Classé' },
  { re: /\b1\s*er\s+Cru\b/i,                                canon: '1er Cru' },
  { re: /\bGrand\s+Cru\b/i,                                 canon: 'Grand Cru' },
  { re: /\bCru\s+Bourgeois\s+Exceptionnel\b/i,              canon: 'Cru Bourgeois Exceptionnel' },
  { re: /\bCru\s+Bourgeois\s+Sup[ée]rieur\b/i,              canon: 'Cru Bourgeois Supérieur' },
  { re: /\bCru\s+Bourgeois\b/i,                             canon: 'Cru Bourgeois' },
  { re: /\bCru\s+Artisan\b/i,                               canon: 'Cru Artisan' },
];

// Appellation-ish phrases that often leak into cuvée_name.
// IMPORTANT: only used as TRAILING SUFFIX stripper (see stripAll) — never
// from the middle/start, to avoid destroying negociant cuvées where the
// appellation IS the cuvée name (e.g. Bouchard "Mercurey").
const APPELLATION_TAIL_PATTERNS = [
  /\bSaint[- ]?[EÉéè]milion\s+Grand\s+Cru\s+Class[ée]\b/i,
  /\bSaint[- ]?[EÉéè]milion\s+Grand\s+Cru\b/i,
];

const VINTAGE_RE = /\b(19|20)\d{2}\b/g;
const BOTTLE_SIZE_RE = /\b(\d+\s*(ml|cl|l)|magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor|impériale|imperiale)\b/gi;
const PACKAGING_RE = /\bin\s+houten\s+kist\b|\bcaisse\s+bois\b|\bowc\b|\boriginal\s+wooden\s+case\b|\bcoffret\b/gi;
const TRAILING_PUNCT = /[\s,\-–—:]+$/g;
const LEADING_PUNCT = /^[\s,\-–—:]+/g;

// Producer prefix expansions to compare cuvée vs producer.
function expandPrefix(s) {
  return s
    .replace(/^ch\b\.?\s+/i, 'chateau ')
    .replace(/^d\b\.?\s+/i, 'domaine ')
    .replace(/^dom\b\.?\s+/i, 'domaine ');
}

function extractClassification(name) {
  for (const { re, canon } of CLASSIFICATION_PATTERNS) {
    if (re.test(name)) return canon;
  }
  return null;
}

function stripAll(name) {
  let out = name;
  for (const { re } of CLASSIFICATION_PATTERNS) out = out.replace(re, ' ');
  out = out.replace(VINTAGE_RE, ' ');
  out = out.replace(BOTTLE_SIZE_RE, ' ');
  out = out.replace(PACKAGING_RE, ' ');
  // Only strip appellation patterns when they appear as a trailing suffix
  // separated by a dash/comma (preserves negociant cuvées named after appellations).
  for (const re of APPELLATION_TAIL_PATTERNS) {
    const tailRe = new RegExp(`\\s*[,\\-–—]\\s*${re.source}\\s*$`, re.flags);
    out = out.replace(tailRe, ' ');
  }
  out = out.replace(/\s*[-–—|]\s*[-–—|]\s*/g, ' - ');
  out = out.replace(/\s+/g, ' ');
  out = out.replace(LEADING_PUNCT, '');
  out = out.replace(TRAILING_PUNCT, '');
  return out.trim();
}

function buildCanonical(producerDisplay, cuveeName, vintage) {
  const parts = [producerDisplay];
  const cleanCuvee = (cuveeName || '').trim();
  const pNorm = expandPrefix(normText(producerDisplay));
  const cNorm = expandPrefix(normText(cleanCuvee));
  if (cleanCuvee && cNorm && cNorm !== pNorm && !pNorm.includes(cNorm) && !cNorm.includes(pNorm)) {
    parts.push(cleanCuvee);
  }
  if (vintage) parts.push(String(vintage));
  return parts.join(' ');
}

function cleanProducerDisplay(producerName) {
  let out = stripAll(producerName);
  out = out.replace(/^\s*[-–—]+\s*/, '').replace(/\s*[-–—]+\s*$/, '');
  return out.trim() || producerName;
}

// ---------- pull all dim_wine rows ----------

const rows = db.prepare(`
  SELECT w.wine_key, w.producer_key, w.appellation_key,
         w.cuvee_name, w.cuvee_norm, w.classification, w.canonical_name, w.vintage,
         p.producer_name, p.producer_norm,
         a.appellation_name
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
`).all();

let changed = 0;
const samples = [];

const updateStmt = db.prepare(`
  UPDATE dim_wine
  SET cuvee_name = ?, cuvee_norm = ?, classification = COALESCE(classification, ?), canonical_name = ?
  WHERE wine_key = ?
`);

const tx = db.transaction((mutations) => {
  for (const m of mutations) updateStmt.run(m.newCuveeName, m.newCuveeNorm, m.newClassification, m.newCanonical, m.wineKey);
});

const mutations = [];

for (const r of rows) {
  const original = r.cuvee_name || '';
  const producerDisplay = cleanProducerDisplay(r.producer_name);
  const classification = r.classification || extractClassification(original) || extractClassification(r.producer_name);
  let cleaned = stripAll(original);

  // Comparison uses cleaned producer (vintages/appellations stripped) to detect grand-vin cases.
  const pNorm = expandPrefix(normText(producerDisplay));
  const cNorm = expandPrefix(normText(cleaned));
  let displayCuvee = cleaned;
  if (cNorm && (cNorm === pNorm || pNorm.includes(cNorm) || cNorm.includes(pNorm))) {
    displayCuvee = '';
  }

  // Recompute cuvee_norm by stripping producer words too.
  const stripWords = pNorm.split(' ').filter(w => w.length > 2);
  let cuveeNorm = normText(displayCuvee);
  for (const w of stripWords) {
    cuveeNorm = cuveeNorm.replace(new RegExp(`\\b${w}\\b`, 'g'), ' ');
  }
  cuveeNorm = cuveeNorm.replace(/\s+/g, ' ').trim();

  const newCanonical = buildCanonical(producerDisplay, displayCuvee, r.vintage);

  const cuveeChanged = displayCuvee !== r.cuvee_name;
  const canonChanged = newCanonical !== r.canonical_name;
  const classChanged = !!classification && classification !== r.classification;
  const normChanged  = cuveeNorm !== r.cuvee_norm;

  if (!cuveeChanged && !canonChanged && !classChanged && !normChanged) continue;

  changed++;
  const matchesFilter = !FILTER ||
    r.producer_name.toLowerCase().includes(FILTER) ||
    (r.cuvee_name || '').toLowerCase().includes(FILTER);
  if (matchesFilter && samples.length < SAMPLE_LIMIT) {
    samples.push({
      wine_key: r.wine_key,
      producer: r.producer_name,
      vintage: r.vintage,
      before: { cuvee_name: r.cuvee_name, classification: r.classification, canonical_name: r.canonical_name },
      after:  { cuvee_name: displayCuvee, classification: classification, canonical_name: newCanonical },
    });
  }
  mutations.push({
    wineKey: r.wine_key,
    newCuveeName: displayCuvee,
    newCuveeNorm: cuveeNorm,
    newClassification: classification,
    newCanonical: newCanonical,
  });
}

console.log(`\nScanned ${rows.length} dim_wine rows.`);
console.log(`Rows that would change: ${changed}`);
console.log(`\n--- Sample of ${samples.length} changes ---\n`);
for (const s of samples) {
  console.log(`[${s.wine_key}] ${s.producer} (${s.vintage ?? 'NV'})`);
  console.log(`  cuvée:          "${s.before.cuvee_name}"  →  "${s.after.cuvee_name}"`);
  if (s.before.classification !== s.after.classification)
    console.log(`  classification: "${s.before.classification ?? ''}"  →  "${s.after.classification ?? ''}"`);
  if (s.before.canonical_name !== s.after.canonical_name)
    console.log(`  canonical:      "${s.before.canonical_name}"  →  "${s.after.canonical_name}"`);
  console.log('');
}

if (APPLY) {
  console.log(`Applying ${mutations.length} updates…`);
  tx(mutations);
  console.log('Done.');
} else {
  console.log('\n(Dry-run — re-run with --apply to write changes.)');
}

db.close();
