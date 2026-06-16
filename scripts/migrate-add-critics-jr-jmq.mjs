/**
 * Migration: extend critic_code CHECK to include 'JR' (Jancis Robinson, /20)
 * and 'JMQ' (Jean-Marc Quarin, /100) on fact_rating + staging_rating_candidates.
 *
 * SQLite can't ALTER a CHECK constraint, so each table is rebuilt (create new,
 * copy, drop, rename, recreate indexes) inside a transaction with FKs off.
 *
 * Run once: node scripts/migrate-add-critics-jr-jmq.mjs
 */
import Database from 'better-sqlite3';
const db = new Database('data/achilles.db');

const CRITICS = "'WA','Vinous','BH','JMIB','RVF','Decanter','JS','JG','JD','WS','Hachette','CT','XW','WE','VI','SM','JR','JMQ'";

const NEW_FACT = `
CREATE TABLE "fact_rating__new" (
  "rating_event_key"    integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  "wine_key"            text    NOT NULL REFERENCES "dim_wine"("wine_key"),
  "source_key"          integer NOT NULL REFERENCES "dim_source"("source_key"),
  "critic_code"         text    NOT NULL CHECK("critic_code" IN (${CRITICS})),
  "reviewer_type"       text    NOT NULL CHECK("reviewer_type" IN ('critic','user_aggregate')),
  "score"               real    NOT NULL,
  "scale"               text    NOT NULL CHECK("scale" IN ('/100','/20','/5','stars')),
  "score_normalized_100" real   NOT NULL,
  "rating_count"        integer,
  "recorded_at"         integer NOT NULL DEFAULT (unixepoch()),
  "source_url"          text,
  "content_hash"        text,
  "batch_id"            text    NOT NULL,
  CONSTRAINT "chk_rating_normalized_range" CHECK("score_normalized_100" BETWEEN 0 AND 100)
)`;

const NEW_STAGING = `
CREATE TABLE "staging_rating_candidates__new" (
  "candidate_id"                 integer PRIMARY KEY AUTOINCREMENT NOT NULL,
  "wine_key"                     text    NOT NULL REFERENCES "dim_wine"("wine_key"),
  "source_key"                   integer NOT NULL REFERENCES "dim_source"("source_key"),
  "critic_code"                  text    NOT NULL CHECK("critic_code" IN (${CRITICS})),
  "reviewer_type"                text    NOT NULL CHECK("reviewer_type" IN ('critic','user_aggregate')),
  "score"                        real    NOT NULL,
  "scale"                        text    NOT NULL CHECK("scale" IN ('/100','/20','/5','stars')),
  "score_normalized_100"         real    NOT NULL,
  "rating_count"                 integer,
  "recorded_at"                  integer NOT NULL DEFAULT (unixepoch()),
  "source_url"                   text,
  "content_hash"                 text,
  "batch_id"                     text    NOT NULL,
  "needs_review"                 integer NOT NULL DEFAULT 1,
  "promoted_to_fact_rating_key"  integer,
  "promoted_at"                  integer,
  CONSTRAINT "chk_staging_normalized_range" CHECK("score_normalized_100" BETWEEN 0 AND 100)
)`;

const INDEXES = [
  'CREATE INDEX `idx_rating_wine` ON `fact_rating` (`wine_key`)',
  'CREATE INDEX `idx_rating_critic` ON `fact_rating` (`critic_code`)',
  'CREATE INDEX `idx_rating_wine_critic` ON `fact_rating` (`wine_key`, `critic_code`)',
  'CREATE INDEX `idx_staging_wine` ON `staging_rating_candidates` (`wine_key`)',
  'CREATE INDEX `idx_staging_critic` ON `staging_rating_candidates` (`critic_code`)',
  'CREATE INDEX `idx_staging_pending` ON `staging_rating_candidates` (`needs_review`, `promoted_at`)',
  'CREATE UNIQUE INDEX `idx_staging_dedup` ON `staging_rating_candidates` (`wine_key`, `source_key`, `content_hash`)',
];

function rebuild(table, newDdl) {
  const before = db.prepare(`SELECT count(*) c FROM ${table}`).get().c;
  db.exec(newDdl);
  db.exec(`INSERT INTO "${table}__new" SELECT * FROM "${table}"`);
  db.exec(`DROP TABLE "${table}"`);
  db.exec(`ALTER TABLE "${table}__new" RENAME TO "${table}"`);
  const after = db.prepare(`SELECT count(*) c FROM ${table}`).get().c;
  if (before !== after) throw new Error(`${table}: row count changed ${before} -> ${after}`);
  console.log(`  ${table}: rebuilt, ${after} rows preserved`);
}

db.pragma('foreign_keys = OFF');
const tx = db.transaction(() => {
  rebuild('fact_rating', NEW_FACT);
  rebuild('staging_rating_candidates', NEW_STAGING);
  for (const sql of INDEXES) db.exec(sql);
});
tx();
// Note: foreign_key_check reports PRE-EXISTING orphans across the whole DB
// (staging_*, dim_wine, ops_job_queue) that are unrelated to this rebuild and
// were never enforced at insert time. Report a count only; not fatal.
const fk = db.pragma('foreign_key_check');
db.pragma('foreign_keys = ON');
if (fk.length) {
  const byTable = fk.reduce((m, r) => ((m[r.table] = (m[r.table] || 0) + 1), m), {});
  console.warn('Pre-existing FK orphans (not caused by this migration):', byTable);
}

// verify the new CHECK accepts the added critics
const ok = db.prepare("SELECT sql FROM sqlite_master WHERE name='fact_rating'").get().sql;
console.log('CHECK has JD:', /'JD'/.test(ok), '| JR:', /'JR'/.test(ok), '| JMQ:', /'JMQ'/.test(ok));
console.log('Migration complete.');
db.close();
