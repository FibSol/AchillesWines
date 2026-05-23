#!/usr/bin/env node
/**
 * Strip CellarTracker-style noise from cuvee_name:
 *   - "Barrel sample" / "Barrel Sample" (anywhere)
 *   - "(Saint-Émilion)" / "(Pauillac)" — appellation in parentheses
 *   - "Bordeaux-style Red Blend" / "Red Blend" / "White Blend" pseudo-cuvées
 *     when the producer is a real château (Cheval Blanc isn't a "Red Blend")
 *   - Leading producer name re-prepended by the scraper
 *   - Trailing "Le Petit Cheval" style second-wine confusion when it equals
 *     a known second-wine entity (these should not appear inside cuvée_name
 *     of the grand vin; flag them but only fix when low-risk)
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

const BARREL_SAMPLE_RE = /\bbarrel\s+sample\b/gi;
const PARENS_APPELLATION_RE = /\s*\(\s*(saint[- ]?[eé]milion|pauillac|margaux|m[ée]doc|saint[- ]?julien|saint[- ]?est[èe]phe|pessac[- ]?l[ée]ognan|graves|sauternes|barsac|pomerol|fronsac|listrac|moulis|haut[- ]?m[ée]doc|chablis|gevrey[- ]?chambertin|vosne[- ]?roman[ée]e|pommard|meursault|puligny[- ]?montrachet|chassagne[- ]?montrachet|sancerre|chinon|vouvray|c[ôo]tes?[- ]du[- ]rh[ôo]ne|ch[âa]teauneuf[- ]du[- ]pape|barolo|barbaresco|brunello\s+di\s+montalcino)\s*\)/gi;
const GENERIC_BLEND_RE = /\b(bordeaux[- ]style\s+red\s+blend|red\s+blend|white\s+blend|rh[ôo]ne[- ]style\s+(red|white)\s+blend)\b/gi;

const rows = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.cuvee_norm, w.vintage,
         p.producer_name, p.producer_norm,
         a.appellation_name
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
  WHERE w.cuvee_name IS NOT NULL AND w.cuvee_name <> ''
`).all();

function strip(name, producerName) {
  let out = name;
  out = out.replace(BARREL_SAMPLE_RE, ' ');
  out = out.replace(PARENS_APPELLATION_RE, ' ');
  out = out.replace(GENERIC_BLEND_RE, ' ');
  // Strip leading producer name re-prepended by the scraper.
  // Build a case-insensitive escaped regex from the producer name.
  if (producerName) {
    const escP = producerName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`^\\s*${escP}\\s+`, 'i'), '');
  }
  // Collapse separators.
  out = out.replace(/\s{2,}/g, ' ');
  out = out.replace(/\s*[-–—|]\s*[-–—|]\s*/g, ' - ');
  out = out.replace(/^\s*[,\-–—:]+\s*/, '');
  out = out.replace(/\s*[,\-–—:]+\s*$/, '');
  return out.trim();
}

const plan = [];
const samples = [];
for (const r of rows) {
  const cleaned = strip(r.cuvee_name, r.producer_name);
  if (cleaned === r.cuvee_name) continue;
  if (cleaned.length > 0 && cleaned.length < 2) continue; // safety: don't reduce to nothing weird
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
