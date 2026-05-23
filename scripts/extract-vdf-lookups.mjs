#!/usr/bin/env node
/**
 * Pull the wine_keys + lookup info for VdF mixed-portfolio rows from the
 * manual-review CSV, emit a compact JSON list the Chrome-driver can iterate.
 */
import Database from 'better-sqlite3';
import fs from 'node:fs';

const db = new Database('C:/Claude/achilles-wines/data/achilles.db', { readonly: true });
const vdfKey = db.prepare("SELECT appellation_key FROM dim_appellation WHERE appellation_name='Vin de France' AND country_code='FR'").get();

// Same criterion as emit-manual-review-csv.mjs.
const producersWithRealAoc = new Set(
  db.prepare('SELECT DISTINCT producer_key FROM dim_wine WHERE appellation_key <> ?').all(vdfKey.appellation_key).map(r => r.producer_key)
);

const rows = db.prepare(`
  SELECT w.wine_key, w.cuvee_name, w.vintage, w.producer_key,
         p.producer_name, p.region
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  WHERE w.appellation_key = ?
`).all(vdfKey.appellation_key);

const out = [];
for (const r of rows) {
  if (!producersWithRealAoc.has(r.producer_key)) continue;
  const lookup = [r.producer_name, r.cuvee_name].filter(Boolean).join(' ').trim();
  out.push({
    wine_key: r.wine_key,
    producer_key: r.producer_key,
    producer: r.producer_name,
    cuvee: r.cuvee_name,
    vintage: r.vintage,
    region: r.region,
    lookup_q: lookup,
    wine_searcher_url: `https://www.wine-searcher.com/find/${encodeURIComponent(lookup)}`,
  });
}
fs.writeFileSync('C:/Claude/achilles-wines/data/vdf-lookups.json', JSON.stringify(out, null, 2), 'utf8');
console.log(`Wrote ${out.length} VdF lookup rows`);
db.close();
