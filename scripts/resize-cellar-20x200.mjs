#!/usr/bin/env node
/**
 * Resize the cellar to the real-world layout: 20 locations × 200 bottles each.
 *
 * Previous layout was 36 locations × 120. This migration:
 *   1. Sets capacity = 200 for locations 1–20 (and ensures they exist).
 *   2. Deletes locations 21–36 — but ONLY if no inventory or consumption row
 *      references them (otherwise it aborts so no bottle is orphaned).
 *
 * Idempotent: safe to run multiple times, on dev or prod.
 *
 *   node scripts/resize-cellar-20x200.mjs            # dry-run summary
 *   node scripts/resize-cellar-20x200.mjs --apply    # write changes
 *
 * Override the DB path with DATABASE_URL if needed.
 */
import Database from "better-sqlite3";
import { argv, env } from "node:process";

const DB_PATH = env.DATABASE_URL ?? "C:/Claude/achilles-wines/data/achilles.db";
const APPLY = argv.includes("--apply");
const TARGET_LOCATIONS = 20;
const TARGET_CAPACITY = 200;

const db = new Database(DB_PATH);
db.pragma("foreign_keys = ON");

const before = db
  .prepare("SELECT COUNT(*) n, COALESCE(MIN(capacity),0) minc, COALESCE(MAX(capacity),0) maxc FROM cellar_locations")
  .get();
const blockers = db
  .prepare(
    `SELECT
       (SELECT COUNT(*) FROM cellar_inventory  WHERE location_id > ?) inv,
       (SELECT COUNT(*) FROM cellar_consumption WHERE location_id > ?) con`,
  )
  .get(TARGET_LOCATIONS, TARGET_LOCATIONS);

console.log(`DB: ${DB_PATH}`);
console.log(`Before: ${before.n} locations (capacity ${before.minc}–${before.maxc})`);
console.log(`Rows referencing locations > ${TARGET_LOCATIONS}: inventory=${blockers.inv}, consumption=${blockers.con}`);

if (blockers.inv > 0 || blockers.con > 0) {
  console.error(
    `\n✖ Aborting: ${blockers.inv} inventory and ${blockers.con} consumption row(s) still ` +
      `reference locations beyond ${TARGET_LOCATIONS}. Move those bottles first, then re-run.`,
  );
  db.close();
  process.exit(1);
}

if (!APPLY) {
  const toDelete = db
    .prepare("SELECT COUNT(*) n FROM cellar_locations WHERE location_id > ?")
    .get(TARGET_LOCATIONS).n;
  console.log(
    `\nDRY-RUN. Would: set capacity=${TARGET_CAPACITY} for locations 1–${TARGET_LOCATIONS}, ` +
      `delete ${toDelete} empty location(s) > ${TARGET_LOCATIONS}.`,
  );
  console.log("Re-run with --apply to write changes.");
  db.close();
  process.exit(0);
}

const tx = db.transaction(() => {
  const upsert = db.prepare(
    `INSERT INTO cellar_locations (location_id, name, capacity, temperature_zone)
     VALUES (?, ?, ?, 'cellar')
     ON CONFLICT(location_id) DO UPDATE SET capacity = excluded.capacity`,
  );
  for (let i = 1; i <= TARGET_LOCATIONS; i++) {
    upsert.run(i, `Emplacement ${String(i).padStart(2, "0")}`, TARGET_CAPACITY);
  }
  const del = db.prepare("DELETE FROM cellar_locations WHERE location_id > ?").run(TARGET_LOCATIONS);
  return del.changes;
});

const deleted = tx();
const after = db
  .prepare("SELECT COUNT(*) n, MIN(capacity) minc, MAX(capacity) maxc FROM cellar_locations")
  .get();
console.log(`\n✓ Applied. Deleted ${deleted} location(s).`);
console.log(`After: ${after.n} locations (capacity ${after.minc}–${after.maxc}).`);
db.close();
