#!/usr/bin/env node
/**
 * Cleanup pollution in dim_producer.producer_name.
 *
 * Strips: vintage, shop SKU codes (CB6, CB12...), bottle sizes (75CL, MAGNUM...),
 * packaging tags (EN COFFRET, +COFFRET OR...), classification tails
 * (Saint-Emilion Grand Cru, etc.), color suffixes (- Rouge / - Blanc).
 *
 * When cleanup makes producer A's name equal to producer B's normalized name
 * (same country_code), the two are merged: all dim_wine.producer_key references
 * are re-pointed to the survivor and the duplicate dim_producer row is deleted.
 *
 * Dry-run by default. Pass --apply to mutate.
 *
 *   node scripts/cleanup-producer-names.mjs                 # dry-run summary
 *   node scripts/cleanup-producer-names.mjs --filter cheval # filtered sample
 *   node scripts/cleanup-producer-names.mjs --apply         # write changes
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const FILTER = (() => { const i = argv.indexOf('--filter'); return i>=0 ? (argv[i+1]||'').toLowerCase() : null; })();
const SAMPLE_LIMIT = (() => { const i = argv.indexOf('--limit'); return i>=0 ? (parseInt(argv[i+1],10)||25) : 25; })();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// ---------- patterns ----------
// Conservative philosophy: only strip when pollution is UNAMBIGUOUS.
// Anchors: stripping happens only when there's a clear delimiter (vintage year,
// all-caps run, explicit " - " / "," / "(" separator). "Château Margaux" stays
// "Château Margaux"; "Domaine Peyre-Rose" stays as-is (no space-dash-space).

const VINTAGE_RE = /\b(19|20)\d{2}\b/g;
const SHOP_CODE_PATTERNS = [
  /\s*\(CB\d{1,2}\)/gi,         // (CB6)  (CB12)
  /\s*\(C\d{1,2}\)/gi,          // (C6)   (C12)
  /\s+CB\d{1,2}\b/gi,           // " CB6"  " CB12"
  /\s+C\d{1,2}\b(?![A-Za-z])/gi,// " C6"
];
const SIZE_PATTERNS = [
  /\s+\d+\s*(ml|cl|l)\b/gi,                  // " 75CL" — must be space-prefixed numeric
  /\s+-?\s*magnum\b/gi,
  /\s+-?\s*jeroboam\b/gi,
  /\s+-?\s*demi[- ]bouteille\b/gi,
  /\s+-?\s*half[- ]bottle\b/gi,
];
const PACKAGING_PATTERNS = [
  /\s*\b(in\s+houten\s+kist|original\s+wooden\s+case|owc|caisse\s+bois|coffret(\s+(or|argent))?|en\s+coffret|en\s+etui|\+\s*coffret.*)$/gi,
];
// Classification: require leading delimiter (comma OR space-dash-space) and end-anchor.
const CLASSIFICATION_TAILS = [
  /\s*[,]\s*(1\s*er|premier)\s+grand\s+cru\s+class[ée](\s+[ab])?\s*$/i,
  /\s+-\s+(1\s*er|premier)\s+grand\s+cru\s+class[ée](\s+[ab])?\s*$/i,
  /\s*[,]\s*grand\s+cru\s+class[ée]\s*$/i,
  /\s+-\s+grand\s+cru\s+class[ée]\s*$/i,
  /\s*[,]\s*1\s*er\s+cru(\s+class[ée])?\s*$/i,
  /\s+-\s+1\s*er\s+cru(\s+class[ée])?\s*$/i,
  /\s*[,]\s*grand\s+cru\s*$/i,
  /\s+-\s+grand\s+cru\s*$/i,
  /\s*[,]\s*cru\s+bourgeois(\s+sup[ée]rieur|\s+exceptionnel)?\s*$/i,
  /\s*[,]\s*cru\s+artisan\s*$/i,
];
// Appellation tails: require leading "," or " - " or "(", NOT bare-space.
const APP_WORDS = [
  'saint[- ]?[eé]milion(?:\\s+grand\\s+cru(?:\\s+class[ée])?)?',
  'pessac[- ]?l[ée]ognan',
  'saint[- ]?julien', 'saint[- ]?est[èe]phe', 'pauillac', 'margaux',
  'haut[- ]?m[ée]doc', 'm[ée]doc', 'graves', 'sauternes', 'barsac',
  'pomerol', 'fronsac', 'listrac', 'moulis',
  'chablis(?:\\s+grand\\s+cru|\\s+1\\s*er\\s+cru)?',
  'gevrey[- ]?chambertin', 'vosne[- ]?roman[ée]e', 'pommard', 'meursault',
  'puligny[- ]?montrachet', 'chassagne[- ]?montrachet',
  'sancerre', 'chinon', 'vouvray',
  'c[ôo]tes?[- ]du[- ]rh[ôo]ne', 'ch[âa]teauneuf[- ]du[- ]pape',
  'brunello\\s+di\\s+montalcino', 'barolo', 'barbaresco',
];
const APP_TAIL_RE = new RegExp(
  `(\\s*[,]\\s*|\\s+-\\s+|\\s+\\(\\s*)(?:${APP_WORDS.join('|')})\\s*\\)?\\s*$`,
  'i'
);
const APPELLATION_TAILS = [APP_TAIL_RE];
// Dom Pérignon-style ": Vintage YYYY" colon-prefixed tail
const COLON_VINTAGE_RE = /\s*:\s*vintage\s*$/i;
// Color suffix: require " - " or ", " explicit separator.
const COLOR_SUFFIX_RE = /\s+(?:-|–|,)\s+(rouge|blanc|rose|rosé|red|white)\s*$/i;
// All-caps shop-feed appellation tail (only matches if the producer is mostly upper-case).
const APPELLATION_TAIL_UPPER_RE = /\s+(ST[- ]?EMILION|ST[- ]?ESTEPHE|ST[- ]?JULIEN|PAUILLAC|MARGAUX|PESSAC|GRAVES|SAUTERNES|MEDOC|HAUT[- ]?MEDOC|MOULIS|LISTRAC|FRONSAC|POMEROL|BARSAC|LISTRAC[- ]MEDOC|CHABLIS)\s*$/i;
const ALL_CAPS_RE = /^[^a-z]{6,}$/;

// Pollution gate: only consider a producer name "polluted" if at least one of
// these is true. Names like "Château Margaux" don't qualify and stay untouched.
const VINTAGE_TEST_RE = /\b(19|20)\d{2}\b/;
function isPolluted(name) {
  if (VINTAGE_TEST_RE.test(name)) return true;
  if (ALL_CAPS_RE.test(name)) return true;
  if (/\(\s*CB\d/.test(name)) return true;
  if (/\d+\s*(CL|ML|L)\b/i.test(name) && /\s/.test(name)) return true;
  if (/\b(coffret|owc|houten kist|en coffret|en etui)\b/i.test(name)) return true;
  // Explicit ", Classification/Appellation" tail
  if (/,\s*(saint[- ]?[eé]milion|pessac[- ]?l[ée]ognan|pauillac|margaux|grand\s+cru|1\s*er\s+cru|cru\s+bourgeois)/i.test(name)) return true;
  // Explicit " - Color" or ", Color" tail
  if (/\s+(?:-|–|,)\s+(rouge|blanc|rose|rosé|red|white)\s*$/i.test(name)) return true;
  return false;
}

function normText(s) {
  return (s||'').normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g,' ').replace(/\s+/g,' ').trim();
}

// Expand abbreviated producer prefixes for grouping equivalence.
// "ch lynch bages" / "lynch bages" / "chateau lynch bages" all collapse.
function expandPrefix(norm) {
  let out = norm;
  if (/^ch\s+/.test(out))         out = 'chateau ' + out.slice(3);
  else if (/^d\s+/.test(out))     out = 'domaine ' + out.slice(2);
  else if (/^dom\s+/.test(out))   out = 'domaine ' + out.slice(4);
  // Also: producers stored bare (no prefix) should match their "Château X" form.
  return out;
}
function groupingNorm(norm) {
  const expanded = expandPrefix(norm);
  // Compute both prefix-stripped variants for fuzzy matching.
  const stripped = expanded.replace(/^(chateau|domaine|maison|bodega|tenuta|cantina|weingut|quinta|casa)\s+/, '');
  return { full: expanded, stripped };
}

function clean(name) {
  if (!isPolluted(name)) return name; // safety gate
  let out = name;
  for (const re of SHOP_CODE_PATTERNS)    out = out.replace(re, ' ');
  for (const re of SIZE_PATTERNS)         out = out.replace(re, ' ');
  for (const re of PACKAGING_PATTERNS)    out = out.replace(re, ' ');
  out = out.replace(VINTAGE_RE, ' ');
  for (const re of CLASSIFICATION_TAILS)  out = out.replace(re, '');
  for (const re of APPELLATION_TAILS)     out = out.replace(re, '');
  if (ALL_CAPS_RE.test(name)) {
    out = out.replace(APPELLATION_TAIL_UPPER_RE, '');
    // Strip trailing standalone color word only as the LAST token after a number/code
    // so we don't kill "CHEVAL BLANC"-style producer names where color is part of the name.
    // Pattern requires the color word to be preceded by a vintage-like token, shop code,
    // or comma/dash separator — never bare space after a name word.
    out = out.replace(/(?:\d{4}|\(?C\d{1,2}\)?|[,\-])\s+(ROUGE|BLANC|ROSE|ROSÉ|RED|WHITE)\b/gi,
                      (m, _g) => m.replace(/\s+(ROUGE|BLANC|ROSE|ROSÉ|RED|WHITE)\b/i, ''));
    // Standalone batch codes / shop tags
    out = out.replace(/\s+(C\d{1,2}|A\s*VIS|RY\s+D'?ARGENT)\b\.?/g, ' ');
  }
  out = out.replace(COLOR_SUFFIX_RE, '');
  out = out.replace(COLON_VINTAGE_RE, '');
  // Collapse separators and trim.
  out = out.replace(/\s*[-–—|]\s*[-–—|]\s*/g, ' - ');
  out = out.replace(/\(\s*\)/g, ' ');
  out = out.replace(/\s+,/g, ',');
  out = out.replace(/^\s*[,\-–—:]+\s*/, '');
  out = out.replace(/\s*[,\-–—:]+\s*$/, '');
  out = out.replace(/\s+/g, ' ').trim();
  return out;
}

// ---------- compute plan ----------

const producers = db.prepare('SELECT * FROM dim_producer').all();
const wineCountRows = db.prepare('SELECT producer_key, COUNT(*) AS n FROM dim_wine GROUP BY producer_key').all();
const wineCount = new Map(wineCountRows.map(r => [r.producer_key, r.n]));

// Compute clean name + norm for every producer (clean returns original if not polluted).
// Reject the cleanup if it mutilates the name (too short, or removed >60% of length,
// or stripped a token that could have been the actual producer surname).
const STRUCT_TOKENS = new Set(['CH','CHATEAU','CHÂTEAU','DOMAINE','MAISON','BODEGA','A','DE','DU','LA','LE','LES','DOM','&','ET']);
function meaningfulTokens(s) {
  return s.split(/\s+/).filter(t => t.length >= 3 && !STRUCT_TOKENS.has(t.toUpperCase()) && !/^\d/.test(t));
}
function isMutilated(orig, cleaned) {
  if (!cleaned || cleaned.length < 4) return true;
  const tokens = cleaned.split(/\s+/).filter(t => t.length > 1);
  if (tokens.length === 0) return true;
  // Reject if cleaned ends in a tiny structural token.
  const lastTok = tokens[tokens.length - 1].toUpperCase();
  if (STRUCT_TOKENS.has(lastTok)) return true;
  // Accept if there are 2+ meaningful tokens (real producer words).
  if (meaningfulTokens(cleaned).length >= 2) return false;
  // Otherwise apply the ratio guard for short/single-token cases.
  if (cleaned.length / orig.length < 0.25) return true;
  return false;
}

for (const p of producers) {
  const cleaned = clean(p.producer_name);
  p._cleanName = isMutilated(p.producer_name, cleaned) ? p.producer_name : cleaned;
  p._mutilated = p._cleanName === p.producer_name && cleaned !== p.producer_name;
  p._cleanNorm = normText(p._cleanName);
  const g = groupingNorm(p._cleanNorm);
  p._groupNormFull = g.full;
  p._groupNormStripped = g.stripped;
}

// Group by (country_code, prefix-expanded clean_norm). Two passes so producers
// stored without "Château"/"Domaine" can still merge with their prefixed twin.
const groups = new Map();
const stripIndex = new Map(); // stripped → first full key seen, for fuzzy match
for (const p of producers) {
  let k = `${p.country_code}|${p._groupNormFull}`;
  if (!groups.has(k)) {
    // Check whether a different group key matches via prefix-stripped form.
    const sk = `${p.country_code}|${p._groupNormStripped}`;
    if (stripIndex.has(sk)) {
      k = stripIndex.get(sk); // merge into the earlier group
    } else {
      stripIndex.set(sk, k);
    }
  }
  if (!groups.has(k)) groups.set(k, []);
  groups.get(k).push(p);
}

// Survivor scoring:
//   1. prefer producer whose name carries the proper entity prefix
//      (Château / Domaine / Maison / Bodega / Tenuta / Weingut / Quinta / Casa)
//   2. then prefer one whose current name already equals the clean form
//   3. then most wines
//   4. then lowest key
const ENTITY_PREFIX_RE = /^(ch[âa]teau|domaine|maison|bodega|bodegas|tenuta|cantina|weingut|quinta|casa|clos|mas|finca|azienda|fattoria)\b/i;
function pickSurvivor(rows) {
  return rows.slice().sort((a, b) => {
    const aPrefix = ENTITY_PREFIX_RE.test(a.producer_name) ? 0 : 1;
    const bPrefix = ENTITY_PREFIX_RE.test(b.producer_name) ? 0 : 1;
    if (aPrefix !== bPrefix) return aPrefix - bPrefix;
    const aClean = a.producer_name === a._cleanName ? 0 : 1;
    const bClean = b.producer_name === b._cleanName ? 0 : 1;
    if (aClean !== bClean) return aClean - bClean;
    const aN = wineCount.get(a.producer_key) || 0;
    const bN = wineCount.get(b.producer_key) || 0;
    if (aN !== bN) return bN - aN;
    return a.producer_key - b.producer_key;
  })[0];
}

const plan = []; // { kind: 'rename'|'merge', from, survivor, newName }
for (const [, rows] of groups) {
  if (rows.length === 1) {
    const p = rows[0];
    if (p.producer_name !== p._cleanName && p._cleanName) {
      plan.push({ kind: 'rename', from: p, survivor: p, newName: p._cleanName });
    }
    continue;
  }
  const survivor = pickSurvivor(rows);
  if (survivor.producer_name !== survivor._cleanName && survivor._cleanName) {
    plan.push({ kind: 'rename', from: survivor, survivor, newName: survivor._cleanName });
  }
  for (const p of rows) {
    if (p.producer_key === survivor.producer_key) continue;
    plan.push({ kind: 'merge', from: p, survivor, newName: survivor._cleanName });
  }
}

const renames = plan.filter(p => p.kind === 'rename');
const merges  = plan.filter(p => p.kind === 'merge');

console.log(`Producers scanned : ${producers.length}`);
console.log(`Groups            : ${groups.size}`);
console.log(`Planned actions   : rename=${renames.length}  merge=${merges.length}\n`);

// ---------- samples ----------

const samples = [];
for (const item of plan) {
  const matchesFilter = !FILTER ||
    item.from.producer_name.toLowerCase().includes(FILTER) ||
    (item.newName || '').toLowerCase().includes(FILTER) ||
    item.survivor.producer_name.toLowerCase().includes(FILTER);
  if (matchesFilter && samples.length < SAMPLE_LIMIT) samples.push(item);
}

console.log(`--- Sample of ${samples.length} ---\n`);
for (const s of samples) {
  const n = wineCount.get(s.from.producer_key) || 0;
  if (s.kind === 'rename') {
    console.log(`RENAME [${s.from.producer_key}]  "${s.from.producer_name}"  →  "${s.newName}"   (${n} wines)`);
  } else {
    console.log(`MERGE  [${s.from.producer_key}→${s.survivor.producer_key}]  "${s.from.producer_name}"  →  "${s.survivor._cleanName}"   (${n} wines from source)`);
  }
}

// ---------- apply ----------

if (APPLY) {
  const renameStmt = db.prepare('UPDATE dim_producer SET producer_name = ?, producer_norm = ? WHERE producer_key = ?');
  const repointWinesStmt = db.prepare('UPDATE dim_wine SET producer_key = ? WHERE producer_key = ?');
  const deleteProducerStmt = db.prepare('DELETE FROM dim_producer WHERE producer_key = ?');

  let renamed = 0, merged = 0, winesMoved = 0;

  let skipped = 0;
  const skipList = [];

  const tx = db.transaction(() => {
    // 1. Merges first — frees up any conflicting norms held by dupes.
    for (const item of plan) {
      if (item.kind !== 'merge') continue;
      winesMoved += repointWinesStmt.run(item.survivor.producer_key, item.from.producer_key).changes;
      deleteProducerStmt.run(item.from.producer_key);
      merged++;
    }
    // 2. Renames second — skip + log any that still hit the unique constraint.
    for (const item of plan) {
      if (item.kind !== 'rename') continue;
      try {
        renameStmt.run(item.newName, normText(item.newName), item.from.producer_key);
        renamed++;
      } catch (e) {
        if (e.code === 'SQLITE_CONSTRAINT_UNIQUE') {
          skipped++;
          if (skipList.length < 20) skipList.push({ from: item.from.producer_name, to: item.newName });
        } else { throw e; }
      }
    }
  });

  tx();
  if (skipped > 0) {
    console.log(`\nSkipped ${skipped} renames due to UNIQUE constraint (sample):`);
    for (const s of skipList) console.log(`   "${s.from}"  ✗→  "${s.to}"`);
  }
  console.log(`\nApplied: renamed=${renamed}  merged=${merged}  wines re-pointed=${winesMoved}`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
