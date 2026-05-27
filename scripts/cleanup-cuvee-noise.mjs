#!/usr/bin/env node
/**
 * Strip shop-scraper noise from cuvee_name:
 *
 *  Wave 1 rules:
 *   - "Barrel sample" / "Barrel Sample" (anywhere)
 *   - "(Saint-Émilion)" / "(Pauillac)" — appellation in parentheses
 *   - "Bordeaux-style Red Blend" / "Red Blend" / "White Blend" pseudo-cuvées
 *   - Leading producer name re-prepended by the scraper
 *
 *  Wave 2 rules (2026-05-27):
 *   - "(CBO à partir de …)" / "(CB6)" / "(CB3)" — carton/wooden-case shop codes
 *   - " - [Appellation]" or ", [Appellation]" trailing suffix (own appellation or parent)
 *     e.g. "Cristal - Champagne" → "Cristal", "Bougros - Chablis" (app=Chablis GC) → "Bougros"
 *   - Cuvée that equals the wine's own appellation name → clear to empty (grand vin)
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const APPLY = argv.includes('--apply');
const FILTER = (() => { const i = argv.indexOf('--filter'); return i>=0 ? (argv[i+1]||'').toLowerCase() : null; })();
const SAMPLE_LIMIT = (() => { const i = argv.indexOf('--limit'); return i>=0 ? (parseInt(argv[i+1],10)||25) : 25; })();

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');

function normText(s) {
  return (s||'').normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g,' ').replace(/\s+/g,' ').trim();
}

// ── Wave 1 patterns ──────────────────────────────────────────────────────────
const BARREL_SAMPLE_RE = /\bbarrel\s+sample\b/gi;
const PARENS_APPELLATION_RE = /\s*\(\s*(saint[- ]?[eé]milion|pauillac|margaux|m[ée]doc|saint[- ]?julien|saint[- ]?est[èe]phe|pessac[- ]?l[ée]ognan|graves|sauternes|barsac|pomerol|fronsac|listrac[- ]?m[ée]doc|listrac|moulis|haut[- ]?m[ée]doc|montagne[- ]?saint[- ]?[eé]milion|canon[- ]?fronsac|c[ôo]tes[- ]?de[- ]?fronsac|lussac[- ]?saint[- ]?[eé]milion|puisseguin[- ]?saint[- ]?[eé]milion|chablis|gevrey[- ]?chambertin|vosne[- ]?roman[ée]e|pommard|meursault|puligny[- ]?montrachet|chassagne[- ]?montrachet|sancerre|chinon|vouvray|c[ôo]tes?[- ]du[- ]rh[ôo]ne|ch[âa]teauneuf[- ]du[- ]pape|barolo|barbaresco|brunello\s+di\s+montalcino)\s*\)/gi;
const GENERIC_BLEND_RE = /\b(bordeaux[- ]style\s+red\s+blend|red\s+blend|white\s+blend|rh[ôo]ne[- ]style\s+(red|white)\s+blend)\b/gi;

// ── Wave 2 patterns ──────────────────────────────────────────────────────────
// Matches: (CBO à partir de 6 bts), (CBO a partir de mgs), (CB6), (CB3), etc.
// Also catches standalone CB6 / CB3 / CB12 without parens (shop notation).
// Does NOT catch C21, C3 etc. (legitimate cuvée names like Cepa 21's "C21").
const CB_CODE_RE = /\s*\(CB[O0-9][^)]*\)\s*|\s*\bCB[0-9]{1,2}\b\s*/gi;


const rows = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.cuvee_norm, w.vintage,
         p.producer_name, p.producer_norm,
         a.appellation_name
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name <> ''
`).all();

function strip(name, producerName, appellationName) {
  let out = name;

  // Wave 2: strip CB/CBO carton-case shop codes first
  out = out.replace(CB_CODE_RE, ' ');

  // Wave 1: barrel sample, parenthesised appellation, generic blend
  out = out.replace(BARREL_SAMPLE_RE, ' ');
  out = out.replace(PARENS_APPELLATION_RE, ' ');
  out = out.replace(GENERIC_BLEND_RE, ' ');

  // Wave 2: strip trailing ", [appellation]" or " - [appellation]" suffix.
  //
  // IMPORTANT: the separator before the appellation MUST have whitespace before the
  // dash so we don't accidentally strip "Provence" from "Côtes-de-Provence" or
  // "Beaune" from "Savigny-les-Beaune". Accepted separators:
  //   (\s+[-–—]\s+)  = " - ", " – " etc. (space-dash-space)
  //   (\s*,\s*)       = ", " or ","
  //
  // Pass 1: exact match against the wine's own appellation_name.
  //   "Cristal - Champagne" → "Cristal"
  //   "rouge, Pessac-Léognan" → "rouge"
  //
  // Pass 2: parent-appellation match — when the appellation name STARTS WITH the
  //   tail word (e.g. "Chablis Grand Cru" starts with "Chablis"), strip that word too.
  //   "Bougros - Chablis" (app="Chablis Grand Cru") → "Bougros"
  const SEP = `(?:\\s+[-–—]\\s+|\\s*,\\s*)`;
  if (appellationName) {
    const appNorm = normText(appellationName);
    try {
      // Pass 1 — exact
      const escApp = appellationName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      out = out.replace(new RegExp(`${SEP}${escApp}\\s*$`, 'i'), '');
    } catch (_) { /* skip */ }
    // Pass 2 — parent appellation (first word)
    try {
      const firstWord = appellationName.split(/[\s\-]+/)[0] || '';
      const firstNorm = normText(firstWord);
      if (firstWord.length >= 4 && appNorm.startsWith(firstNorm) && appNorm !== firstNorm) {
        const escFirst = firstWord.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        out = out.replace(new RegExp(`${SEP}${escFirst}\\s*$`, 'i'), '');
      }
    } catch (_) { /* skip */ }
  }

  // Strip leading producer name re-prepended by the scraper.
  // Use (\s+|$) so that when the whole remaining string IS the producer name
  // (e.g. "PHELAN SEGUR ST-ESTEPHE" after CB6 strip) it becomes empty.
  if (producerName) {
    try {
      const escP = producerName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      out = out.replace(new RegExp(`^\\s*${escP}(\\s+|$)`, 'i'), '');
    } catch (_) { /* skip */ }
  }

  // Collapse separators and trim punctuation.
  out = out.replace(/\s{2,}/g, ' ');
  out = out.replace(/\s*[-–—|]\s*[-–—|]\s*/g, ' - ');
  out = out.replace(/^\s*[,\-–—:]+\s*/, '');
  out = out.replace(/\s*[,\-–—:]+\s*$/, '');
  return out.trim();
}

const plan = [];
const samples = [];
for (const r of rows) {
  const cleaned = strip(r.cuvee_name, r.producer_name, r.appellation_name);
  if (cleaned === r.cuvee_name) continue;
  if (cleaned.length > 0 && cleaned.length < 2) continue; // safety: don't reduce to a single char
  const newNorm = normText(cleaned);
  plan.push({ row: r, newName: cleaned, newNorm });

  const matchesFilter = !FILTER ||
    r.producer_name.toLowerCase().includes(FILTER) ||
    r.cuvee_name.toLowerCase().includes(FILTER);
  if (matchesFilter && samples.length < SAMPLE_LIMIT) {
    samples.push({ row: r, newName: cleaned });
  }
}

console.log(`Scanned wines with cuvée : ${rows.length}`);
console.log(`Rows to cleanup          : ${plan.length}\n`);
console.log(`--- Sample of ${samples.length} ---\n`);
for (const s of samples) {
  console.log(`[${s.row.wine_key}] ${s.row.producer_name} · ${s.row.vintage ?? 'NV'}`);
  console.log(`   cuvée:  "${s.row.cuvee_name}"  →  "${s.newName}"`);
}

if (APPLY) {
  const upd = db.prepare('UPDATE dim_wine SET cuvee_name = ?, cuvee_norm = ?, canonical_name = ? WHERE wine_key = ?');
  let changed = 0;
  const tx = db.transaction(() => {
    for (const item of plan) {
      const newCanonicalParts = [item.row.producer_name];
      if (item.newName) newCanonicalParts.push(item.newName);
      if (item.row.vintage) newCanonicalParts.push(String(item.row.vintage));
      upd.run(item.newName, item.newNorm, newCanonicalParts.join(' '), item.row.wine_key);
      changed++;
    }
  });
  tx();
  console.log(`\nApplied ${changed} cuvée cleanups.`);
} else {
  console.log('\n(Dry-run — re-run with --apply to mutate.)');
}

db.close();
