#!/usr/bin/env tsx
/**
 * scripts/import-bm-appellations.ts
 *
 * Import 201 appellations from burgundy-manager → dim_appellation.
 * Role: Patroclus (Backend)
 * Run : npx tsx scripts/import-bm-appellations.ts
 */

import Database from "better-sqlite3";
import { eq, and } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import { db, schema } from "../db/index";
import { normText } from "../lib/identity";

const BM_DB = "C:\\Users\\Nicolas\\Bourgogne\\burgundy-manager\\data\\burgundy.db";

interface BmAppellation {
  id: number;
  name: string;
  level: string;         // "GC" | "1er" | "Village" | "Regional" | ...
  commune: string | null;
  geo_polygon: string | null;
}

// ─── Level mapping ────────────────────────────────────────────────────────────

type AchillesLevel = "regional" | "village" | "premier_cru" | "grand_cru" | "iconic";

function mapLevel(lvl: string): AchillesLevel {
  switch ((lvl || "").toLowerCase()) {
    case "gc":
    case "grand cru":
    case "grand_cru":      return "grand_cru";
    case "1er":
    case "1er cru":
    case "premier cru":
    case "premier_cru":    return "premier_cru";
    case "village":        return "village";
    default:               return "regional";
  }
}

// ─── Region inference from commune / appellation name ────────────────────────

function inferRegion(name: string, commune: string | null): string {
  const n = (name + " " + (commune ?? "")).toLowerCase();
  if (n.includes("chablis"))              return "Bourgogne";
  if (n.includes("mâcon") || n.includes("macon") || n.includes("pouilly-fuissé") || n.includes("saint-véran")) return "Bourgogne";
  if (["marsannay","fixin","gevrey","morey","chambolle","vougeot","flagey",
       "vosne","nuits","côte de nuits","hautes côtes","premeaux"].some(x => n.includes(x))) return "Bourgogne";
  if (["aloxe","pernand","ladoix","savigny","beaune","pommard","volnay","meursault",
       "puligny","chassagne","santenay","maranges","auxey","saint-romain","saint-aubin",
       "côte de beaune","monthélie","blagny"].some(x => n.includes(x))) return "Bourgogne";
  if (n.includes("mercurey") || n.includes("rully") || n.includes("givry") ||
      n.includes("bouzeron") || n.includes("côte chalonnaise")) return "Bourgogne";
  if (n.includes("irancy") || n.includes("vézelay") || n.includes("tonnerre")) return "Bourgogne";
  if (n.includes("bordeaux") || n.includes("médoc") || n.includes("pauillac") ||
      n.includes("saint-julien") || n.includes("margaux") || n.includes("saint-estèphe") ||
      n.includes("pomerol") || n.includes("saint-émilion") || n.includes("graves") ||
      n.includes("sauternes") || n.includes("barsac"))           return "Bordeaux";
  if (n.includes("champagne"))            return "Champagne";
  if (n.includes("alsace"))               return "Alsace";
  if (n.includes("côte-rôtie") || n.includes("cote-rotie") || n.includes("condrieu") ||
      n.includes("hermitage") || n.includes("crozes") || n.includes("cornas") ||
      n.includes("saint-joseph") || n.includes("châteauneuf") ||
      n.includes("côtes du rhône") || n.includes("gigondas"))    return "Rhône";
  if (n.includes("sancerre") || n.includes("pouilly") || n.includes("vouvray") ||
      n.includes("chinon") || n.includes("bourgueil") || n.includes("muscadet") ||
      n.includes("anjou") || n.includes("saumur"))               return "Loire";
  return "Bourgogne"; // BM is Burgundy-first
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const bm = new Database(BM_DB, { readonly: true });
  const rows = bm.prepare(`SELECT * FROM appellations ORDER BY id`).all() as BmAppellation[];
  bm.close();

  console.log(`📥  ${rows.length} appellations from burgundy-manager`);

  const batchId = randomUUID();
  let inserted = 0, skipped = 0;

  // Upsert burgundy_manager source key
  const src = db
    .select({ sourceKey: schema.dimSource.sourceKey })
    .from(schema.dimSource)
    .where(eq(schema.dimSource.sourceCode, "burgundy_manager"))
    .get();
  const sourceKey = src?.sourceKey ?? null;

  db.insert(schema.opsBatchLog).values({
    batchId, sourceKey, startedAt: new Date(), status: "running", rowsFetched: rows.length,
  }).run();

  for (const row of rows) {
    const countryCode   = "FR";
    const appellationNorm = normText(row.name);
    const region        = inferRegion(row.name, row.commune);
    const level         = mapLevel(row.level);

    const existing = db
      .select({ appellationKey: schema.dimAppellation.appellationKey })
      .from(schema.dimAppellation)
      .where(and(
        eq(schema.dimAppellation.appellationNorm, appellationNorm),
        eq(schema.dimAppellation.countryCode, countryCode),
      ))
      .get();

    if (existing) { skipped++; continue; }

    db.insert(schema.dimAppellation).values({
      countryCode,
      region,
      subregion: row.commune ?? undefined,
      appellationName: row.name,
      appellationNorm,
      level,
      geoPolygon: row.geo_polygon ?? undefined,
    }).run();
    inserted++;
  }

  db.update(schema.opsBatchLog).set({
    finishedAt: new Date(), status: "success",
    rowsInserted: inserted, rowsSkippedUnchanged: skipped,
  }).where(eq(schema.opsBatchLog.batchId, batchId)).run();

  console.log(`\n✅  Appellations import complete`);
  console.log(`   Inserted : ${inserted}`);
  console.log(`   Skipped  : ${skipped} (already existed)`);
  console.log(`   Batch    : ${batchId}`);
}

main();
