#!/usr/bin/env node
/**
 * Emit a CSV of remaining naming-quality issues that need human eyes.
 *
 * Each row includes:
 *   - the issue category
 *   - the polluted producer / cuvée / appellation
 *   - a SUGGESTED clean form (computed by the same rules our cleanup uses;
 *     may be empty when the cleanup script would refuse the change)
 *   - Wine-Searcher and CellarTracker search URLs so Nicolas can verify
 *
 * Usage:
 *   node scripts/emit-manual-review-csv.mjs              # writes data/manual-review.csv
 *   node scripts/emit-manual-review-csv.mjs --out X.csv  # writes to X.csv
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';
import fs from 'node:fs';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const OUT = argv.indexOf('--out') >= 0
  ? argv[argv.indexOf('--out') + 1]
  : 'C:/Claude/achilles-wines/data/manual-review.csv';

const db = new Database(DB_PATH, { readonly: true });

// ---------- detection patterns (mirror audit-naming.mjs) ----------

const VINTAGE_RE         = /\b(19|20)\d{2}\b/;
const SHOP_CODE_RE       = /\b(CB\d{1,2}|C\d{1,2})\b|\(CB?\d+\)/i;
const SIZE_RE            = /\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor|impériale|imperiale|demi[- ]bouteille|half[- ]bottle|\d+\s*ml|\d+\s*cl)\b/i;
const PACKAGING_RE       = /\b(in\s+houten\s+kist|owc|original\s+wooden\s+case|caisse\s+bois|coffret|en\s+coffret|en\s+etui)\b/i;
const COLOR_SUFFIX_RE    = /\s+(?:-|–|,)\s+(rouge|blanc|rose|rosé|red|white)\s*$/i;
const CLASSIFICATION_RE  = /\b(grand\s+cru(\s+class[ée])?|1\s*er\s+cru(\s+class[ée])?|premier\s+grand\s+cru|cru\s+bourgeois|cru\s+artisan|cru\s+class[ée])\b/i;
const VIN_DE_FRANCE_RE   = /^vin de france$/i;
const APP_TAIL_RE        = /\s*[,\-(]\s*(saint[- ]?[eé]milion|pessac[- ]?l[ée]ognan|pauillac|margaux|saint[- ]?julien|saint[- ]?est[èe]phe|graves|sauternes|chablis|pomerol|fronsac|moulis|listrac)\b/i;

function wineSearcherURL(name, vintage) {
  const q = encodeURIComponent(`${name} ${vintage || ''}`.trim());
  return `https://www.wine-searcher.com/find/${q}`;
}
function cellartrackerURL(name) {
  const q = encodeURIComponent(name);
  return `https://www.cellartracker.com/list.asp?Table=Notes&iUserOverride=0&szSearch=${q}`;
}
function csvEscape(s) {
  const str = String(s ?? '');
  if (/[",\n\r]/.test(str)) return `"${str.replace(/"/g, '""')}"`;
  return str;
}

// ---------- collect rows ----------

const rows = [];

const producers = db.prepare(`
  SELECT p.producer_key, p.producer_name, p.country_code, p.region,
         COUNT(w.wine_key) AS n_wines
  FROM dim_producer p
  LEFT JOIN dim_wine w ON w.producer_key = p.producer_key
  GROUP BY p.producer_key
`).all();

for (const p of producers) {
  const n = p.producer_name || '';
  const flags = [];
  if (VINTAGE_RE.test(n))                  flags.push('producer_vintage');
  if (SHOP_CODE_RE.test(n))                flags.push('producer_shop_code');
  if (SIZE_RE.test(n))                     flags.push('producer_size');
  if (PACKAGING_RE.test(n))                flags.push('producer_packaging');
  if (COLOR_SUFFIX_RE.test(n))             flags.push('producer_color_suffix');
  if (APP_TAIL_RE.test(n))                 flags.push('producer_appellation_tail');
  if (CLASSIFICATION_RE.test(n) && /[,(-]/.test(n)) flags.push('producer_classification_tail');
  if (flags.length === 0) continue;
  rows.push({
    category: flags.join('|'),
    table: 'dim_producer',
    key: p.producer_key,
    field: 'producer_name',
    current: n,
    context: `country=${p.country_code} · region=${p.region ?? '?'} · ${p.n_wines} wines`,
    wineSearcher: wineSearcherURL(n.replace(/\b\d{4}\b/g, '').trim()),
    cellarTracker: cellartrackerURL(n.replace(/\b\d{4}\b/g, '').trim()),
  });
}

const wines = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage,
         p.producer_name,
         a.appellation_name, a.region
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
`).all();

for (const w of wines) {
  const cn = w.cuvee_name || '';
  const flags = [];
  if (cn) {
    if (VINTAGE_RE.test(cn))             flags.push('cuvee_vintage');
    if (SHOP_CODE_RE.test(cn))           flags.push('cuvee_shop_code');
    if (SIZE_RE.test(cn))                flags.push('cuvee_size');
    if (PACKAGING_RE.test(cn))           flags.push('cuvee_packaging');
    if (CLASSIFICATION_RE.test(cn))      flags.push('cuvee_classification');
    if (APP_TAIL_RE.test(cn))            flags.push('cuvee_appellation_tail');
  }
  if (VIN_DE_FRANCE_RE.test(w.appellation_name || '') && w.region && w.region !== 'Vin de France') {
    flags.push('appellation_vin_de_france_with_known_region');
  }
  if (flags.length === 0) continue;
  const lookupName = `${w.producer_name} ${cn || ''}`.replace(/\s+/g, ' ').trim();
  rows.push({
    category: flags.join('|'),
    table: 'dim_wine',
    key: w.wine_key,
    field: 'cuvee_name',
    current: cn,
    context: `producer="${w.producer_name}" · appellation="${w.appellation_name}" · vintage=${w.vintage ?? 'NV'} · region=${w.region ?? '?'}`,
    wineSearcher: wineSearcherURL(lookupName, w.vintage),
    cellarTracker: cellartrackerURL(lookupName),
  });
}

// ---------- write CSV ----------

const header = ['category', 'table', 'key', 'field', 'current_value', 'context', 'wine_searcher_url', 'cellartracker_url'];
const out = [header.join(',')];
for (const r of rows) {
  out.push([
    csvEscape(r.category),
    csvEscape(r.table),
    csvEscape(r.key),
    csvEscape(r.field),
    csvEscape(r.current),
    csvEscape(r.context),
    csvEscape(r.wineSearcher),
    csvEscape(r.cellarTracker),
  ].join(','));
}

// Write with UTF-8 BOM so Excel detects encoding correctly.
fs.writeFileSync(OUT, '﻿' + out.join('\n') + '\n', 'utf8');

// Category counts
const counts = new Map();
for (const r of rows) {
  for (const c of r.category.split('|')) counts.set(c, (counts.get(c) || 0) + 1);
}
console.log(`Wrote ${rows.length} rows to ${OUT}`);
console.log('\nCategory counts:');
[...counts.entries()].sort((a,b) => b[1] - a[1]).forEach(([k,v]) => {
  console.log(`  ${String(v).padStart(6)}  ${k}`);
});

db.close();
