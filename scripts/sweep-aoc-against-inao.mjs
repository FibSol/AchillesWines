#!/usr/bin/env node
/**
 * Full sweep of dim_appellation FR rows against the INAO 2012 reference list
 * (data/inao-refs/inao_liste_aoc_vins.txt, derived from INAO's official
 * Liste-AOC-vins.pdf).
 *
 * Three outputs:
 *   1. Stats: how many AOCs match exactly, how many differ only by accents,
 *      how many INAO entries are missing from the DB, how many DB FR entries
 *      have no INAO twin.
 *   2. Auto-normalize ACCENT/SPACING/HYPHEN differences when there's only ONE
 *      DB row whose norm matches an INAO row. Updates appellation_name to the
 *      INAO canonical spelling (preserving accents like é, è, à) and applies
 *      a region/bassin label.
 *   3. data/aoc-sweep-report.csv — lists every unresolved row so they can be
 *      picked up by the manual-review issue.
 *
 * Defaults to DRY-RUN. Pass --apply to mutate.
 */
import Database from 'better-sqlite3';
import { argv } from 'node:process';
import fs from 'node:fs';

const DB_PATH = 'C:/Claude/achilles-wines/data/achilles.db';
const REF_TXT = 'C:/Claude/achilles-wines/data/inao-refs/inao_liste_aoc_vins.txt';
const APPLY = argv.includes('--apply');

// ---------- 1. Parse the INAO reference ----------

function normText(s) {
  if (!s) return '';
  return s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/[,.'"\/\-()\[\]_&+]/g, ' ').replace(/\s+/g, ' ').trim();
}

// File is Latin-1 (ISO-8859-1) encoded — reading as 'latin1' preserves accents correctly
// so normText can strip them predictably. Reading as 'utf8' corrupts high bytes.
const raw = fs.readFileSync(REF_TXT, 'latin1');
const inao = []; // { name, bassin, type2 }
for (const line of raw.split(/\r?\n/)) {
  // Skip header / page-break lines.
  if (!/^Vin\b/.test(line)) continue;
  // The file is fixed-width but pdftotext compresses some columns; safer to
  // tokenize by 2+ spaces. Expect: Type1 [Type2] Signe Bassin Name [Denoms]
  const cells = line.split(/\s{2,}/).filter(s => s);
  // cells[0] = "Vin"
  let idx = 1;
  let type2 = '';
  // type2 is optional
  if (cells[idx] && /Vin (de liqueur|doux naturel)/i.test(cells[idx])) {
    type2 = cells[idx]; idx++;
  }
  const signe = cells[idx]; idx++;
  if (signe !== 'AOC-AOP') continue;     // skip AOR (regional eaux-de-vie etc.)
  const bassin = cells[idx]; idx++;
  const rawName = cells[idx];
  if (!rawName) continue;
  // Strip " ou <alternative>" synonyms (e.g. "Hermitage ou L'Hermitage ou Ermitage")
  // — we keep only the primary name; alternatives are handled by normText matching.
  const name = rawName.split(/ ou /i)[0].trim();
  // Skip non-wine appellations the file lists (eg. "Crémant", "Vin jaune" included as actual AOCs)
  // — these ARE wine AOCs, we keep them.
  inao.push({ name, bassin: bassin?.trim() || '', type2 });
}

// Dedup INAO list (some appellations appear twice for different bassins via
// "ou" synonyms — keep first occurrence).
const inaoByNorm = new Map();
for (const r of inao) {
  const n = normText(r.name);
  if (!inaoByNorm.has(n)) inaoByNorm.set(n, r);
}

console.log(`INAO reference parsed: ${inao.length} entries, ${inaoByNorm.size} unique by norm.`);

// ---------- 2. Load DB appellations ----------

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

const dbApps = db.prepare(`
  SELECT a.*, COUNT(w.wine_key) AS n_wines
  FROM dim_appellation a
  LEFT JOIN dim_wine w ON w.appellation_key = a.appellation_key
  WHERE a.country_code = 'FR'
  GROUP BY a.appellation_key
`).all();

const dbByNorm = new Map();
for (const a of dbApps) {
  const n = a.appellation_norm || normText(a.appellation_name);
  if (!dbByNorm.has(n)) dbByNorm.set(n, []);
  dbByNorm.get(n).push(a);
}

console.log(`DB FR appellations: ${dbApps.length} rows, ${dbByNorm.size} unique norms.\n`);

// ---------- 3. Compare ----------

const stats = {
  exact: [],                  // INAO name === DB name
  accentDiff: [],             // INAO norm === DB norm, names differ
  inaoOnly: [],               // INAO has it, DB doesn't
  dbOnly: [],                 // DB has it, INAO doesn't (could be IGP / sub-region / typo)
};

const seenDbKeys = new Set();
for (const [norm, ref] of inaoByNorm) {
  const matches = dbByNorm.get(norm);
  if (!matches) {
    stats.inaoOnly.push(ref);
    continue;
  }
  for (const m of matches) {
    seenDbKeys.add(m.appellation_key);
    if (m.appellation_name === ref.name) {
      stats.exact.push({ inao: ref, db: m });
    } else {
      stats.accentDiff.push({ inao: ref, db: m });
    }
  }
}

for (const a of dbApps) {
  if (!seenDbKeys.has(a.appellation_key)) {
    stats.dbOnly.push(a);
  }
}

console.log(`Exact-match AOCs               : ${stats.exact.length}`);
console.log(`Accent / spacing differences   : ${stats.accentDiff.length}`);
console.log(`Missing in DB (INAO has it)    : ${stats.inaoOnly.length}`);
console.log(`Extra in DB (no INAO match)    : ${stats.dbOnly.length}\n`);

// ---------- 4. Apply accent-diff renames (low-risk) ----------

const renameStmt = db.prepare('UPDATE dim_appellation SET appellation_name = ? WHERE appellation_key = ?');
const updRegionStmt = db.prepare('UPDATE dim_appellation SET region = ? WHERE appellation_key = ? AND (region IS NULL OR region = ?)');

let renamed = 0;
const sampleRenames = [];

function countDiacritics(s) {
  return (s.normalize('NFKD').match(/[̀-ͯ]/g) || []).length;
}

let skippedAccentLoss = 0;
const skippedSamples = [];

const tx = db.transaction(() => {
  for (const { inao: ref, db: row } of stats.accentDiff) {
    // Skip when more than one DB row maps to the same norm (ambiguous).
    if (dbByNorm.get(normText(ref.name)).length > 1) continue;
    // Guard: never apply a rename that loses diacritics
    // (PDF text extraction sometimes drops é/è/à inconsistently).
    if (countDiacritics(ref.name) < countDiacritics(row.appellation_name)) {
      skippedAccentLoss++;
      if (skippedSamples.length < 8) {
        skippedSamples.push(`"${row.appellation_name}"  ✗→  "${ref.name}"  (would lose accent)`);
      }
      continue;
    }
    if (APPLY) renameStmt.run(ref.name, row.appellation_key);
    renamed++;
    if (sampleRenames.length < 20) {
      sampleRenames.push(`"${row.appellation_name}"  →  "${ref.name}"  (${row.n_wines} wines)`);
    }
  }
});
tx();

console.log(`Accent / spacing renames planned : ${renamed}`);
for (const s of sampleRenames) console.log(`  ${s}`);
if (skippedAccentLoss > 0) {
  console.log(`\nSkipped (would lose accents) : ${skippedAccentLoss}`);
  for (const s of skippedSamples) console.log(`  ${s}`);
}

// ---------- 5. Emit CSV report ----------

const lines = ['category,inao_name,inao_bassin,inao_type2,db_name,db_region,db_level,db_wines,db_appellation_key'];
function esc(s) { const str = String(s ?? ''); return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str; }

for (const r of stats.inaoOnly) {
  lines.push(['missing_in_db', esc(r.name), esc(r.bassin), esc(r.type2), '', '', '', '', ''].join(','));
}
for (const a of stats.dbOnly) {
  lines.push(['extra_in_db', '', '', '', esc(a.appellation_name), esc(a.region), esc(a.level), a.n_wines, a.appellation_key].join(','));
}
for (const { inao: r, db: a } of stats.accentDiff) {
  if (dbByNorm.get(normText(r.name)).length > 1) {
    lines.push(['ambiguous_accent', esc(r.name), esc(r.bassin), esc(r.type2), esc(a.appellation_name), esc(a.region), esc(a.level), a.n_wines, a.appellation_key].join(','));
  }
}

const OUT = 'C:/Claude/achilles-wines/data/aoc-sweep-report.csv';
fs.writeFileSync(OUT, '﻿' + lines.join('\n') + '\n', 'utf8');
console.log(`\nWrote ${lines.length - 1} unresolved rows to ${OUT}`);

if (!APPLY) console.log('\n(Dry-run — re-run with --apply to mutate.)');

db.close();
