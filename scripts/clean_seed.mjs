import Database from 'better-sqlite3';
const db = new Database('data/achilles.db');
const d = db.prepare('DELETE FROM fact_vintage_rating WHERE source_key=32').run();
console.log('Deleted', d.changes, 'rows');
db.close();
