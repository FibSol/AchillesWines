// Idempotently register the 'tastingbook' source in dim_source on the live DB.
// Mirrors the row added to db/seed.ts. Safe to run repeatedly.
//
//   node scripts/register-tastingbook-source.mjs
import Database from 'better-sqlite3';

const db = new Database('C:/Claude/achilles-wines/data/achilles.db');

const existing = db
  .prepare("SELECT source_key FROM dim_source WHERE source_code = ?")
  .get('tastingbook');

if (existing) {
  console.log(`tastingbook already registered (source_key=${existing.source_key})`);
} else {
  const info = db
    .prepare(
      `INSERT INTO dim_source
         (source_code, source_name, source_tier, cadence, base_url, license_class)
       VALUES (?, ?, ?, ?, ?, ?)`
    )
    .run(
      'tastingbook',
      'Tastingbook (critic panel — James Suckling)',
      'D_user_aggregate',
      'on_demand',
      'https://tastingbook.com',
      'public_check_terms'
    );
  console.log(`Registered tastingbook (source_key=${info.lastInsertRowid})`);
}
db.close();
