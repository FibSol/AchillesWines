#!/usr/bin/env node
/**
 * Strip trailing appellation suffixes from cuvee_name when:
 *   - it matches the wine's actual appellation_name (or a token of it), AND
 *   - it matches against a hardcoded list of common appellation words, AND
 *   - removing it leaves at least 2 characters.
 *
 * This v2 extends the v1 script to:
 * 1. Match both " - Appellation" (dash) and ", Appellation" (comma) separators
 * 2. Normalize accents before comparing (using normText)
 * 3. Try to match against common appellation words even if not in the wine's actual appellation
 * 4. Strip trailing "Classé" / "Grand Cru Classé" / "1er Grand Cru Classé" after the appellation
 *
 * Examples:
 *   "Château Bellefont-Bellecier, Saint-Emilion Classé" → "Château Bellefont-Bellecier"
 *   "Trio - Saint-Estephe" (appellation stored as "Saint-Estèphe") → "Trio"
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

function normText(s) {
  return (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

// Common French appellation words for matching.
// IMPORTANT: list longer/more-specific forms before shorter ones, and avoid
// tokens that are substrings of other compound appellation names (e.g. "Médoc"
// appears inside "Haut-Médoc", "Moulis-en-Médoc", "Listrac-Médoc" — so we list
// the full compound forms only and NOT bare "Médoc"/"Medoc").
const COMMON_APPELLATIONS = [
  'Saint-Émilion Grand Cru Classé', 'Saint-Emilion Grand Cru Classé',
  'Saint-Émilion Grand Cru', 'Saint-Emilion Grand Cru',
  'Saint-Émilion', 'Saint-Emilion',
  'Montagne-Saint-Émilion', 'Montagne-Saint-Emilion',
  'Lussac-Saint-Émilion', 'Lussac-Saint-Emilion',
  'Saint-Estèphe', 'Saint-Estephe',
  'Saint-Julien',
  'Pessac-Léognan', 'Pessac-Leognan',
  'Haut-Médoc', 'Haut-Medoc',
  'Listrac-Médoc', 'Listrac-Medoc',
  'Moulis-en-Médoc', 'Moulis-en-Medoc',
  'Pauillac',
  'Margaux',
  'Sauternes',
  'Pomerol',
  'Fronsac',
  'Moulis',
  'Listrac',
  'Chablis Grand Cru',
  'Chablis Premier Cru',
  'Chablis',
];

const rows = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage, p.producer_name, a.appellation_name
  FROM dim_wine w
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  JOIN dim_producer p   ON p.producer_key   = w.producer_key
  WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name <> ''
`).all();

const plan = [];

for (const r of rows) {
  const cn = r.cuvee_name;
  const app = r.appellation_name || '';

  // Build a list of appellation-derived suffixes to try, longest first.
  const appTokens = new Set();

  // Add common appellations
  for (const ca of COMMON_APPELLATIONS) {
    appTokens.add(ca);
  }

  // Add tokens from the wine's actual appellation
  if (app) {
    appTokens.add(app);                            // full name
    // First word group ("Chablis" from "Chablis Grand Cru" or "Chablis 1er Cru")
    const firstWord = app.split(/\s+/)[0];
    if (firstWord && firstWord.length >= 5) appTokens.add(firstWord);
  }

  // Accent-normalized copy of the cuvée for regex matching
  // (so "Saint-Estèphe" token matches "Saint-Estephe" in cuvée and vice versa).
  const cnNorm = cn.normalize('NFKD').replace(/[̀-ͯ]/g, '');

  // Try to match and strip appellation tails with either dash or comma separator
  let newCuvee = cn;
  let matched = false;

  for (const token of [...appTokens].sort((a, b) => b.length - a.length)) {
    // Build regex that matches:
    //   " - <token>" or "- <token>" (dash separator, space required before dash)
    //   ", <token>" (comma separator)
    // at the end of the cuvée (with optional trailing decorators like "à Prix Malin" or classification).
    // We strip accents from the token so it matches both accented and unaccented spellings
    // (e.g. token "Saint-Estèphe" also matches "Saint-Estephe" in the cuvée).
    const tokenNoAccent = token.normalize('NFKD').replace(/[̀-ͯ]/g, '');
    const escToken = tokenNoAccent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    // Pattern 1: dash separator " - <token> [optional classification]"
    // Require at least one space before the dash so we don't match word-internal
    // hyphens like the "-Saint" in "Montagne-Saint-Emilion".
    const dashRe = new RegExp(`[ \\t]+[-–—]\\s*${escToken}(\\s+(?:grand\\s+cru\\s+class[ée]|grand\\s+cru|1\\s*er\\s+grand\\s+cru|1\\s*er\\s+cru\\s+class[ée]|class[ée]|[à\\s\\w]+))?\\s*$`, 'i');

    // Pattern 2: comma separator ", <token> [optional classification]"
    const commaRe = new RegExp(`\\s*,\\s*${escToken}(\\s+(?:grand\\s+cru\\s+class[ée]|grand\\s+cru|1\\s*er\\s+grand\\s+cru|1\\s*er\\s+cru\\s+class[ée]|class[ée]|[à\\s\\w]+))?\\s*$`, 'i');

    // Test against accent-normalized cuvée; if matched, compute the stripped
    // length and apply the same trim to the original string.
    const commaMatch = cnNorm.match(commaRe);
    const dashMatch  = cnNorm.match(dashRe);
    const best = commaMatch ?? dashMatch;   // prefer comma (more specific)
    if (best) {
      // Strip the matched suffix from the original cuvée by length.
      newCuvee = cn.slice(0, cn.length - best[0].length).trim();
      matched = true;
      break;
    }
  }

  if (!matched) continue;
  if (!newCuvee || newCuvee.length < 2) continue;   // safety: don't blank everything
  if (newCuvee === cn) continue;
  plan.push({ wineKey: r.wine_key, oldCuvee: cn, newCuvee, newNorm: normText(newCuvee), producer: r.producer_name, vintage: r.vintage, app });
}

console.log(`Cuvée-appellation tail strips planned : ${plan.length}\n`);
const sample = plan.slice(0, 20);
for (const s of sample) {
  console.log(`  [${s.wineKey}] ${s.producer} · ${s.vintage ?? 'NV'} · "${s.app}"`);
  console.log(`     "${s.oldCuvee}"  →  "${s.newCuvee}"`);
}

if (APPLY) {
  const upd = db.prepare(`UPDATE dim_wine SET cuvee_name=?, cuvee_norm=?, canonical_name=? WHERE wine_key=?`);
  const tx = db.transaction(() => {
    for (const p of plan) {
      const canonical = `${p.producer}${p.newCuvee ? ' ' + p.newCuvee : ''}${p.vintage ? ' ' + p.vintage : ''}`;
      upd.run(p.newCuvee, p.newNorm, canonical, p.wineKey);
    }
  });
  tx();
  console.log(`\nApplied ${plan.length} cuvée-tail strips.`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
