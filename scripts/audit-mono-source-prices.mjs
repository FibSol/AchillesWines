#!/usr/bin/env node
// Audit and purge fact_price rows where the wine_key has only 1 distinct source.
// Conforms retroactively to ADR-003 + ADR-013.
import Database from 'better-sqlite3';

const db = new Database('data/achilles.db');

const before = db.prepare('SELECT COUNT(*) as n FROM fact_price').get().n;
console.log(`fact_price before: ${before} rows`);

const monoSource = db.prepare(`
  SELECT wine_key, COUNT(DISTINCT source_key) as src_count, COUNT(*) as row_count
  FROM fact_price
  GROUP BY wine_key
  HAVING src_count = 1
  ORDER BY row_count DESC
`).all();

console.log(`\nMono-source wine_keys: ${monoSource.length}`);
if (monoSource.length > 0) {
  console.log('Top 10:');
  monoSource.slice(0, 10).forEach(r => {
    console.log(`  ${r.wine_key}: ${r.row_count} rows (1 source)`);
  });
}

const monoKeys = monoSource.map(r => r.wine_key);
if (monoKeys.length > 0) {
  const placeholders = monoKeys.map(() => '?').join(',');
  const deleted = db.prepare(`DELETE FROM fact_price WHERE wine_key IN (${placeholders})`).run(...monoKeys);
  console.log(`\nDeleted ${deleted.changes} mono-source rows`);
} else {
  console.log('\nNo mono-source rows found. fact_price is clean.');
}

const after = db.prepare('SELECT COUNT(*) as n FROM fact_price').get().n;
console.log(`fact_price after: ${after} rows (removed ${before - after})`);
db.close();
