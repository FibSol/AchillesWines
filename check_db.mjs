import Database from 'better-sqlite3';
const db = new Database('data/achilles.db', { readonly: true });

// Sources
const sources = db.prepare("SELECT * FROM dim_source LIMIT 10").all();
console.log('SOURCES:', JSON.stringify(sources, null, 2));

// Distinct regions with country
const regions = db.prepare(`
  SELECT DISTINCT country_code, region, count(*) as cnt
  FROM dim_producer WHERE status='active' AND region IS NOT NULL
  GROUP BY country_code, region
  ORDER BY cnt DESC LIMIT 30
`).all();
console.log('\nREGIONS (top 30):', JSON.stringify(regions, null, 2));

db.close();
