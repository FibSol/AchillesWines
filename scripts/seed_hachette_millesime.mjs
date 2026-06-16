/**
 * Seed fact_vintage_rating with the Hachette 'Tableau de cotation des
 * millésimes' (Le Guide Hachette des Vins — sélection 2018), scale /20.
 *
 * Data extracted by scripts/extract_hachette_millesime.py (per-cell OCR) into
 * data/hachette_millesime.json. Distinct source_key from vintage_consensus, so
 * rows coexist (unique index = country,region,subregion,color,vintage,source).
 *
 * Run once: node scripts/seed_hachette_millesime.mjs
 */
import Database from 'better-sqlite3';
import { readFileSync } from 'node:fs';

const db = new Database('data/achilles.db');
const data = JSON.parse(readFileSync('scripts/seed-data/hachette_millesime.json', 'utf-8'));

// ── 1. Hachette source (F_vintage_authority) ───────────────────────────────
let src = db.prepare("SELECT source_key FROM dim_source WHERE source_code='hachette_millesime_2018'").get();
if (!src) {
  db.prepare(`
    INSERT INTO dim_source (source_code, source_name, source_tier, country_code,
      base_url, license_class, cadence, enabled, requires_auth, notes)
    VALUES ('hachette_millesime_2018','Le Guide Hachette des Vins — Millésimes (2018)',
      'F_vintage_authority','FR',?,'public_check_terms','one_shot',1,0,
      'Tableau de cotation des millésimes, notes /20, 1945–2016. Mini-guide PDF.')
  `).run(data.source_url);
  src = db.prepare("SELECT source_key FROM dim_source WHERE source_code='hachette_millesime_2018'").get();
  console.log('Created dim_source hachette_millesime_2018, key=', src.source_key);
} else {
  console.log('Using existing dim_source hachette_millesime_2018, key=', src.source_key);
}
const SOURCE_KEY = src.source_key;

// Idempotency: the unique index includes `subregion`, which is NULL for every
// Hachette row — and SQLite treats NULLs as DISTINCT in unique indexes, so
// INSERT OR REPLACE never fires a conflict and would duplicate on every run.
// Clear this source's rows first, then re-insert cleanly.
const cleared = db.prepare("DELETE FROM fact_vintage_rating WHERE source_key=?").run(SOURCE_KEY).changes;
console.log(`Cleared ${cleared} existing Hachette rows for clean re-seed.`);

// ── 2. Map the 17 Hachette columns → (region, subregion, color) ────────────
// region strings match the existing vintage_consensus convention so the
// VintageHeatmap can render them. character_notes preserves the exact Hachette
// column label for full auditability of the color/region mapping.
const COLMAP = {
  "Alsace":                    { region: "Alsace",                subregion: null,   color: "white" },
  "Beaujolais":                { region: "Beaujolais",            subregion: null,   color: "red" },
  "Bordeaux rouge":            { region: "Bordeaux",              subregion: null,   color: "red" },
  "Bordeaux liquoreux":        { region: "Bordeaux",              subregion: null,   color: "sweet" },
  "Bordeaux sec":              { region: "Bordeaux",              subregion: null,   color: "white" },
  "Bourgogne rouge":           { region: "Bourgogne",             subregion: null,   color: "red" },
  "Bourgogne blanc":           { region: "Bourgogne",             subregion: null,   color: "white" },
  "Champagne":                 { region: "Champagne",             subregion: null,   color: "sparkling" },
  "Jura (vin jaune)":          { region: "Jura",                  subregion: null,   color: "white" },
  "Languedoc-Roussillon":      { region: "Languedoc-Roussillon",  subregion: null,   color: "red" },
  "Provence rouge":            { region: "Provence",              subregion: null,   color: "red" },
  "Sud-Ouest rouge":           { region: "Sud-Ouest",             subregion: null,   color: "red" },
  "Sud-Ouest blanc liquoreux": { region: "Sud-Ouest",             subregion: null,   color: "sweet" },
  "Loire rouge":               { region: "Loire",                 subregion: null,   color: "red" },
  "Loire blanc liquoreux":     { region: "Loire",                 subregion: null,   color: "sweet" },
  "Rhône (nord)":              { region: "Rhône Nord",            subregion: null,   color: "red" },
  "Rhône (sud)":               { region: "Rhône Sud",             subregion: null,   color: "red" },
};

// ── 3. Insert (idempotent on the unique index) ─────────────────────────────
const insert = db.prepare(`
  INSERT OR REPLACE INTO fact_vintage_rating
    (country_code, region, subregion, color, vintage, source_key,
     score, scale, score_normalized_100, character_notes, source_url)
  VALUES ('FR', ?, ?, ?, ?, ?, ?, '/20', ?, ?, ?)
`);

let inserted = 0, skipped = 0;
const tx = db.transaction(() => {
  for (const [year, row] of Object.entries(data.matrix)) {
    for (const [label, score] of Object.entries(row)) {
      if (score === null || score === undefined) continue;
      const m = COLMAP[label];
      if (!m) { skipped++; continue; }
      const norm = Number(score) * 5; // /20 → /100
      const r = insert.run(
        m.region, m.subregion, m.color, Number(year), SOURCE_KEY,
        Number(score), norm, `Hachette: ${label}`, data.source_url,
      );
      inserted += r.changes;
    }
  }
});
tx();

console.log(`Done — upserted ${inserted} Hachette vintage-rating rows (skipped ${skipped}).`);
const n = db.prepare("SELECT count(*) AS n FROM fact_vintage_rating WHERE source_key=?").get(SOURCE_KEY);
console.log(`Hachette rows now in fact_vintage_rating: ${n.n}`);
const span = db.prepare("SELECT min(vintage) a, max(vintage) b FROM fact_vintage_rating WHERE source_key=?").get(SOURCE_KEY);
console.log(`Vintage span: ${span.a}–${span.b}`);
db.close();
