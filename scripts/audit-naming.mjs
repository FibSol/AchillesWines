#!/usr/bin/env node
/**
 * Audit naming-pollution patterns in dim_producer, dim_wine, dim_appellation.
 * Read-only — emits counts + samples to stdout, optionally writes detailed CSV.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';
import fs from 'node:fs';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const CSV = argv.includes('--csv') ? argv[argv.indexOf('--csv') + 1] : null;

const db = new Database(DB_PATH, { readonly: true });

// ---------- pattern definitions ----------

const VINTAGE_RE = /\b(19|20)\d{2}\b/;
const SHOP_CODE_RE = /\b(CB\d{1,2}|OWC|EP|EN PRIMEUR)\b|\(CB\d+\)/i;
const SIZE_RE = /\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor|impériale|imperiale|demi[- ]bouteille|half[- ]bottle|\d+\s*ml|\d+\s*cl)\b/i;
const PACKAGING_RE = /\bin\s+houten\s+kist\b|\bowc\b|\boriginal\s+wooden\s+case\b|\bcaisse\s+bois\b|\bcoffret\b/i;
const COLOR_SUFFIX_RE = /\b-\s*(rouge|blanc|rose|rosé|red|white)\b\s*$/i;
const COLOR_IN_NAME_RE = /\b-\s*(rouge|blanc|rose|rosé)\b/i;
const CLASSIFICATION_RE = /\b(grand\s+cru(\s+class[ée])?|1\s*er\s+cru(\s+class[ée])?|premier\s+grand\s+cru|cru\s+bourgeois|cru\s+artisan|cru\s+class[ée])\b/i;
const BARREL_SAMPLE_RE = /\bbarrel\s+sample\b/i;
const APPELLATION_TAILS = [
  /\bsaint[- ]?[eé]milion(\s+grand\s+cru(\s+class[ée])?)?$/i,
  /\bpauillac$/i, /\bmargaux$/i, /\bm[ée]doc$/i,
  /\bsaint[- ]?julien$/i, /\bsaint[- ]?est[èe]phe$/i,
  /\bpessac[- ]?l[ée]ognan$/i, /\bgraves$/i, /\bsauternes$/i,
  /\bchablis(\s+grand\s+cru|\s+1\s*er\s+cru)?$/i,
];
const VIN_DE_FRANCE_RE = /^vin de france$/i;

// Producer should ideally start with a recognized entity word.
const PRODUCER_ENTITY_PREFIX_RE = /^(ch[âa]teau|domaine|maison|bodega|bodegas|tenuta|cantina|weingut|quinta|casa|clos|mas|finca|vi[gn]a|azienda|fattoria|tenute|villa|cave|caves|union des |producteurs|f\.|d\.|e\.|h\.|j\.|l\.|m\.|p\.|r\.|s\.|gj |g\. |le |la |les )/i;

// Appellation in producer name (heuristic — appellation-only producers)
const APPELLATION_AS_PRODUCER_RE = /^(saint[- ]?[eé]milion|pauillac|margaux|m[ée]doc|chablis|sancerre|chinon|vouvray|c[ôo]tes? du rh[ôo]ne|c[ôo]tes? de provence|bourgogne|bordeaux|champagne|alsace|languedoc)/i;

// ---------- pull data ----------

const producers = db.prepare(`
  SELECT producer_key, producer_name, producer_norm, country_code, region
  FROM dim_producer
`).all();

const wines = db.prepare(`
  SELECT w.wine_key, w.producer_key, w.cuvee_name, w.cuvee_norm, w.vintage,
         w.color, w.classification, w.canonical_name,
         p.producer_name, p.country_code, p.region,
         a.appellation_name, a.appellation_norm
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  JOIN dim_appellation a ON a.appellation_key = w.appellation_key
`).all();

// ---------- categorise ----------

const issues = {
  producer_vintage:       [],
  producer_shop_code:     [],
  producer_size:          [],
  producer_color_suffix:  [],
  producer_classification:[],
  producer_appellation_tail: [],
  producer_appellation_only: [],
  producer_no_entity_prefix: [],
  producer_packaging:     [],
  cuvee_vintage:          [],
  cuvee_shop_code:        [],
  cuvee_size:             [],
  cuvee_packaging:        [],
  cuvee_color_suffix:     [],
  cuvee_classification:   [],
  cuvee_barrel_sample:    [],
  cuvee_appellation_tail: [],
  cuvee_double_spaces:    [],
  appellation_vin_de_france_with_known_region: [],
};

for (const p of producers) {
  const n = p.producer_name || '';
  if (VINTAGE_RE.test(n))          issues.producer_vintage.push(p);
  if (SHOP_CODE_RE.test(n))        issues.producer_shop_code.push(p);
  if (SIZE_RE.test(n))             issues.producer_size.push(p);
  if (COLOR_SUFFIX_RE.test(n))     issues.producer_color_suffix.push(p);
  if (CLASSIFICATION_RE.test(n))   issues.producer_classification.push(p);
  if (PACKAGING_RE.test(n))        issues.producer_packaging.push(p);
  if (APPELLATION_TAILS.some(re => re.test(n))) issues.producer_appellation_tail.push(p);
  if (APPELLATION_AS_PRODUCER_RE.test(n.trim())) issues.producer_appellation_only.push(p);
  if (!PRODUCER_ENTITY_PREFIX_RE.test(n.trim()) && /^[A-Z]/.test(n.trim())) {
    // Only flag if it doesn't start with a known entity word AND isn't a single brand-style word.
    if (n.trim().split(/\s+/).length > 1) issues.producer_no_entity_prefix.push(p);
  }
}

for (const w of wines) {
  const n = w.cuvee_name || '';
  if (!n) continue;
  if (VINTAGE_RE.test(n))          issues.cuvee_vintage.push(w);
  if (SHOP_CODE_RE.test(n))        issues.cuvee_shop_code.push(w);
  if (SIZE_RE.test(n))             issues.cuvee_size.push(w);
  if (PACKAGING_RE.test(n))        issues.cuvee_packaging.push(w);
  if (COLOR_SUFFIX_RE.test(n))     issues.cuvee_color_suffix.push(w);
  if (CLASSIFICATION_RE.test(n))   issues.cuvee_classification.push(w);
  if (BARREL_SAMPLE_RE.test(n))    issues.cuvee_barrel_sample.push(w);
  if (APPELLATION_TAILS.some(re => re.test(n))) issues.cuvee_appellation_tail.push(w);
  if (/\s{2,}/.test(n))            issues.cuvee_double_spaces.push(w);
}

// "Vin de France" appellation paired with a producer that has a known region
for (const w of wines) {
  if (VIN_DE_FRANCE_RE.test(w.appellation_name || '') && w.region && w.region !== 'Vin de France') {
    issues.appellation_vin_de_france_with_known_region.push(w);
  }
}

// ---------- print summary ----------

console.log('=== AUDIT SUMMARY ===\n');
console.log(`Total producers : ${producers.length}`);
console.log(`Total wines     : ${wines.length}\n`);

const pad = (s, n) => s.padEnd(n);
for (const [k, arr] of Object.entries(issues)) {
  console.log(`${pad(k, 50)} ${String(arr.length).padStart(6)}`);
}

// Sample 3 examples per category
console.log('\n=== SAMPLES ===');
for (const [k, arr] of Object.entries(issues)) {
  if (arr.length === 0) continue;
  console.log(`\n[${k}] — ${arr.length} rows`);
  for (const row of arr.slice(0, 3)) {
    if (k.startsWith('producer_')) {
      console.log(`   • "${row.producer_name}"  (key=${row.producer_key})`);
    } else if (k.startsWith('appellation_')) {
      console.log(`   • "${row.producer_name}" / appellation="${row.appellation_name}" / region="${row.region}"`);
    } else {
      console.log(`   • "${row.cuvee_name}"  [${row.producer_name} · ${row.vintage ?? 'NV'}]`);
    }
  }
}

// ---------- optional CSV ----------

if (CSV) {
  const lines = ['category,wine_key_or_producer_key,producer_name,cuvee_name,vintage,appellation_name,region,issue_value'];
  for (const [k, arr] of Object.entries(issues)) {
    for (const row of arr) {
      const key = row.wine_key || row.producer_key;
      const csvEsc = (s) => `"${String(s ?? '').replace(/"/g, '""')}"`;
      lines.push([
        k, key,
        csvEsc(row.producer_name),
        csvEsc(row.cuvee_name ?? ''),
        row.vintage ?? '',
        csvEsc(row.appellation_name ?? ''),
        csvEsc(row.region ?? ''),
        csvEsc(row.cuvee_name ?? row.producer_name),
      ].join(','));
    }
  }
  fs.writeFileSync(CSV, lines.join('\n'), 'utf8');
  console.log(`\nWrote ${lines.length - 1} rows to ${CSV}`);
}

db.close();
