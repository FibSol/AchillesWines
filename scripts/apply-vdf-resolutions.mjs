#!/usr/bin/env node
/**
 * Apply manually-curated VdF resolution decisions to the DB.
 * Reads data/vdf-resolutions.json: [{wine_key, action, appellation_name?}]
 *   action = 'confirm_vdf'   → leave alone, just mark resolved
 *   action = 'repoint'       → move wine to the named appellation (must exist)
 *   action = 'not_found'     → leave alone, log for manual review
 */
import Database from 'better-sqlite3';
import fs from 'node:fs';
import { argv } from 'node:process';

const APPLY = argv.includes('--apply');
const db = new Database('C:/Claude/achilles-wines/data/achilles.db');
db.pragma('foreign_keys = ON');

const decisions = JSON.parse(fs.readFileSync('C:/Claude/achilles-wines/data/vdf-resolutions.json', 'utf8'));
const findApp = db.prepare("SELECT appellation_key FROM dim_appellation WHERE country_code='FR' AND appellation_name = ?");
const upd = db.prepare('UPDATE dim_wine SET appellation_key = ? WHERE wine_key = ?');

let confirmed = 0, repointed = 0, notFound = 0, errors = 0;
const sample = [];
const tx = db.transaction(() => {
  for (const d of decisions) {
    if (d.action === 'confirm_vdf')   { confirmed++; continue; }
    if (d.action === 'not_found')     { notFound++; continue; }
    if (d.action === 'repoint') {
      const a = findApp.get(d.appellation_name);
      if (!a) { errors++; continue; }
      if (APPLY) upd.run(a.appellation_key, d.wine_key);
      repointed++;
      if (sample.length < 10) sample.push(`${d.wine_key.slice(0,8)} → ${d.appellation_name}`);
    }
  }
});
tx();

console.log(`Decisions processed : ${decisions.length}`);
console.log(`  confirm_vdf  : ${confirmed}`);
console.log(`  repoint      : ${repointed}`);
console.log(`  not_found    : ${notFound}`);
console.log(`  errors       : ${errors}`);
for (const s of sample) console.log(`     ${s}`);
if (!APPLY) console.log('(Dry-run — re-run with --apply to mutate.)');
db.close();
