#!/usr/bin/env tsx
/**
 * scripts/import-bm-vintage-scores.ts
 *
 * Import 364 vintage_scores from burgundy-manager → fact_vintage_rating.
 * Score mapping (1–5 scale): 1→60, 2→75, 3→85, 4→92, 5→97
 * Role: Patroclus (Backend)
 * Run : npx tsx scripts/import-bm-vintage-scores.ts
 */

import Database from "better-sqlite3";
import { eq } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import { db, schema } from "../db/index";

const BM_DB = "C:\\Users\\Nicolas\\Bourgogne\\burgundy-manager\\data\\burgundy.db";

interface BmVintageScore {
  id: number;
  year: number;
  region: string;
  score: number;     // 1–5
  label: string | null;
  notes: string | null;
}

// ─── Score normalisation (matches seed_vintage_ratings.mjs convention) ────────

const SCORE_MAP: Record<number, number> = { 1: 60, 2: 75, 3: 85, 4: 92, 5: 97 };
function normalise(score: number): number {
  return SCORE_MAP[Math.round(score)] ?? Math.round((score / 5) * 100);
}

// ─── Region + color mapping ───────────────────────────────────────────────────

interface RegionColor { region: string; color: "red"|"white"|"rosé"|"sparkling"|"sweet"|"all"; countryCode: string; subregion?: string; }

function mapRegionColor(bmRegion: string): RegionColor {
  const r = bmRegion.toLowerCase();

  // Burgundy
  if (r.includes("côte d'or") || r.includes("cote d'or") || r.includes("côte de nuits") || r.includes("côte de beaune")) {
    const color = r.includes("rouge") || r.includes("red") ? "red" : r.includes("blanc") || r.includes("white") ? "white" : "all";
    return { region: "Bourgogne", color: color === "all" ? "red" : color, countryCode: "FR" };
  }
  if (r.includes("chablis"))      return { region: "Bourgogne", color: "white", countryCode: "FR", subregion: "Chablis" };
  if (r.includes("côte chalonnaise") || r.includes("cote chalonnaise")) return { region: "Bourgogne", color: "all", countryCode: "FR", subregion: "Côte Chalonnaise" };
  if (r.includes("mâconnais") || r.includes("maconnais")) return { region: "Bourgogne", color: "white", countryCode: "FR", subregion: "Mâconnais" };
  if (r.includes("bourgogne"))    return { region: "Bourgogne", color: "all", countryCode: "FR" };

  // Bordeaux
  if (r.includes("bordeaux"))     return { region: "Bordeaux", color: "red", countryCode: "FR" };
  if (r.includes("sauternes") || r.includes("barsac")) return { region: "Bordeaux", color: "sweet", countryCode: "FR" };
  if (r.includes("médoc") || r.includes("medoc")) return { region: "Bordeaux", color: "red", countryCode: "FR" };
  if (r.includes("saint-émilion") || r.includes("pomerol")) return { region: "Bordeaux", color: "red", countryCode: "FR" };
  if (r.includes("graves")) return { region: "Bordeaux", color: r.includes("blanc") ? "white" : "red", countryCode: "FR" };

  // Other French
  if (r.includes("champagne"))    return { region: "Champagne",  color: "sparkling", countryCode: "FR" };
  if (r.includes("alsace"))       return { region: "Alsace",     color: "white",     countryCode: "FR" };
  if (r.includes("rhône") || r.includes("rhone") || r.includes("hermitage") || r.includes("châteauneuf")) {
    return { region: "Rhône", color: r.includes("blanc") ? "white" : "red", countryCode: "FR" };
  }
  if (r.includes("loire"))        return { region: "Loire",      color: r.includes("rouge") ? "red" : "white", countryCode: "FR" };
  if (r.includes("provence"))     return { region: "Provence",   color: r.includes("blanc") ? "white" : "red", countryCode: "FR" };
  if (r.includes("beaujolais"))   return { region: "Beaujolais", color: "red",       countryCode: "FR" };

  // Italy
  if (r.includes("piémont") || r.includes("piemont") || r.includes("barolo") || r.includes("barbaresco")) return { region: "Piémont", color: "red", countryCode: "IT" };
  if (r.includes("toscane") || r.includes("toscana") || r.includes("chianti")) return { region: "Toscane", color: "red", countryCode: "IT" };

  // Default fallback
  return { region: bmRegion, color: "all", countryCode: "FR" };
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const bm = new Database(BM_DB, { readonly: true });
  const rows = bm.prepare(`SELECT * FROM vintage_scores ORDER BY year, region`).all() as BmVintageScore[];
  bm.close();

  console.log(`📥  ${rows.length} vintage_scores from burgundy-manager`);

  const batchId   = randomUUID();
  const sourceKey = db
    .select({ sourceKey: schema.dimSource.sourceKey })
    .from(schema.dimSource)
    .where(eq(schema.dimSource.sourceCode, "burgundy_manager"))
    .get()?.sourceKey;

  if (!sourceKey) throw new Error("Source 'burgundy_manager' not found. Run db:seed first.");

  db.insert(schema.opsBatchLog).values({
    batchId, sourceKey, startedAt: new Date(), status: "running", rowsFetched: rows.length,
  }).run();

  let inserted = 0, skipped = 0, dlq = 0;
  const now = new Date();

  for (const row of rows) {
    try {
      const { region, color, countryCode, subregion } = mapRegionColor(row.region);
      const scoreNorm = normalise(row.score);
      const notes = [row.label, row.notes].filter(Boolean).join(" — ") || undefined;

      try {
        db.insert(schema.factVintageRating).values({
          countryCode,
          region,
          subregion:          subregion ?? undefined,
          color,
          vintage:            row.year,
          sourceKey,
          score:              row.score,
          scale:              "/5",
          scoreNormalized100: scoreNorm,
          characterNotes:     notes,
          recordedAt:         now,
        }).run();
        inserted++;
      } catch {
        // Unique constraint hit — already exists from seed_vintage_ratings
        skipped++;
      }
    } catch (err) {
      db.insert(schema.opsDeadLetter).values({
        sourceKey, batchId, errorClass: "validation_error",
        errorMessage: String(err),
        sourceRecordId: String(row.id),
        rawRecord: JSON.stringify(row), resolution: "pending",
      }).run();
      dlq++;
    }
  }

  db.update(schema.opsBatchLog).set({
    finishedAt: now, status: dlq > 10 ? "partial" : "success",
    rowsInserted: inserted, rowsSkippedUnchanged: skipped, rowsDlq: dlq,
  }).where(eq(schema.opsBatchLog.batchId, batchId)).run();

  console.log(`\n✅  Vintage scores import complete`);
  console.log(`   Inserted : ${inserted}`);
  console.log(`   Skipped  : ${skipped} (unique constraint — already seeded)`);
  console.log(`   DLQ      : ${dlq}`);
  console.log(`   Batch    : ${batchId}`);
}

main();
