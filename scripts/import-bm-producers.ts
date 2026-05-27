#!/usr/bin/env tsx
/**
 * scripts/import-bm-producers.ts
 *
 * Import 8,701 domaines from burgundy-manager → dim_producer.
 * Enriches existing producers with lat/lng, tier, style notes where missing.
 * Role: Patroclus (Backend)
 * Run : npx tsx scripts/import-bm-producers.ts
 */

import Database from "better-sqlite3";
import { eq, and } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import { db, schema } from "../db/index";
import { normalizeProducer } from "../lib/identity";

const BM_DB = "C:\\Users\\Nicolas\\Bourgogne\\burgundy-manager\\data\\burgundy.db";

interface BmDomaine {
  id: number;
  name: string;
  region: string | null;
  commune: string | null;
  vigneron: string | null;
  surface_ha: number | null;
  lat: number | null;
  lng: number | null;
  tier: number | null;      // 1–3
  style: string | null;
  rvf: number | null;
  created_at: number;
}

// ─── Coverage tier mapping ────────────────────────────────────────────────────

function coverageTier(tier: number | null): "notable" | "mid" | "long_tail" {
  if (tier === 1) return "notable";
  if (tier === 2) return "mid";
  return "long_tail";
}

// ─── Region → French region ───────────────────────────────────────────────────

function mapRegion(region: string | null): string {
  if (!region) return "Bourgogne";
  const r = region.toLowerCase();
  if (r.includes("bordeaux") || r.includes("médoc") || r.includes("pomerol") ||
      r.includes("saint-émilion") || r.includes("graves") || r.includes("sauternes")) return "Bordeaux";
  if (r.includes("champagne")) return "Champagne";
  if (r.includes("alsace"))    return "Alsace";
  if (r.includes("rhône") || r.includes("rhone") || r.includes("côte-rôtie") ||
      r.includes("hermitage") || r.includes("châteauneuf")) return "Rhône";
  if (r.includes("loire") || r.includes("sancerre") || r.includes("vouvray") ||
      r.includes("chinon") || r.includes("muscadet")) return "Loire";
  if (r.includes("provence") || r.includes("bandol")) return "Provence";
  if (r.includes("languedoc") || r.includes("roussillon")) return "Languedoc";
  if (r.includes("jura"))   return "Jura";
  if (r.includes("savoie")) return "Savoie";
  if (r.includes("beaujolais")) return "Beaujolais";
  // Everything else is Burgundy (BM is Burgundy-centric)
  return "Bourgogne";
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const bm = new Database(BM_DB, { readonly: true });
  const rows = bm.prepare(`SELECT * FROM domaines ORDER BY id`).all() as BmDomaine[];
  bm.close();

  console.log(`📥  ${rows.length} domaines from burgundy-manager`);

  const batchId  = randomUUID();
  const sourceKey = db
    .select({ sourceKey: schema.dimSource.sourceKey })
    .from(schema.dimSource)
    .where(eq(schema.dimSource.sourceCode, "burgundy_manager"))
    .get()?.sourceKey ?? null;

  db.insert(schema.opsBatchLog).values({
    batchId, sourceKey, startedAt: new Date(), status: "running", rowsFetched: rows.length,
  }).run();

  let inserted = 0, enriched = 0, skipped = 0, dlq = 0;
  const now = new Date();

  for (let i = 0; i < rows.length; i++) {
    if ((i + 1) % 1000 === 0) console.log(`   … ${i + 1}/${rows.length}`);
    const row = rows[i];

    try {
      const producerNorm = normalizeProducer(row.name);
      const countryCode  = "FR";
      const region       = mapRegion(row.region);

      const existing = db
        .select({
          producerKey:  schema.dimProducer.producerKey,
          latitude:     schema.dimProducer.latitude,
          longitude:    schema.dimProducer.longitude,
          tier:         schema.dimProducer.tier,
        })
        .from(schema.dimProducer)
        .where(and(
          eq(schema.dimProducer.producerNorm, producerNorm),
          eq(schema.dimProducer.countryCode, countryCode),
        ))
        .get();

      if (existing) {
        // Enrich with lat/lng and tier if missing
        const updates: Record<string, unknown> = { lastSeenAt: now };
        if (row.lat  && !existing.latitude)  updates.latitude  = row.lat;
        if (row.lng  && !existing.longitude) updates.longitude = row.lng;
        if (row.tier && !existing.tier)      updates.tier      = row.tier;

        if (Object.keys(updates).length > 1) {
          db.update(schema.dimProducer)
            .set(updates)
            .where(eq(schema.dimProducer.producerKey, existing.producerKey))
            .run();
          enriched++;
        } else {
          skipped++;
        }
      } else {
        db.insert(schema.dimProducer).values({
          producerName:       row.name,
          producerNorm,
          countryCode,
          region,
          subregion:          row.commune ?? undefined,
          allowedAppellations: [],
          aliases:            row.vigneron ? [row.vigneron] : [],
          latitude:           row.lat  ?? undefined,
          longitude:          row.lng  ?? undefined,
          tier:               row.tier ?? undefined,
          notes:              row.style ?? undefined,
          status:             "active",
          coverageTier:       coverageTier(row.tier),
        }).run();
        inserted++;
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
    finishedAt: now,
    status: dlq > rows.length * 0.05 ? "partial" : "success",
    rowsInserted: inserted, rowsUpdated: enriched,
    rowsSkippedUnchanged: skipped, rowsDlq: dlq,
  }).where(eq(schema.opsBatchLog.batchId, batchId)).run();

  console.log(`\n✅  Producers import complete`);
  console.log(`   Inserted : ${inserted}`);
  console.log(`   Enriched : ${enriched} (lat/lng or tier added to existing)`);
  console.log(`   Skipped  : ${skipped}`);
  console.log(`   DLQ      : ${dlq}`);
  console.log(`   Batch    : ${batchId}`);
}

main();
