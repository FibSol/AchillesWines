#!/usr/bin/env tsx
/**
 * scripts/import-bm-cuvees-ratings.ts
 *
 * Import 5,798 cuvées + 20,664 ratings from burgundy-manager.
 *   - cuvées → dim_wine (one entry per cuvée×vintage found in ratings, plus NV stubs)
 *   - ratings → staging_rating_candidates
 * Role: Patroclus (Backend)
 * Run : npx tsx scripts/import-bm-cuvees-ratings.ts
 */

import Database from "better-sqlite3";
import { eq, and } from "drizzle-orm";
import { createHash, randomUUID } from "node:crypto";
import { db, schema } from "../db/index";
import {
  normText,
  computeWineKey,
  normalizeProducer,
  normalizeCuvee,
  normalizeScoreTo100,
} from "../lib/identity";

const BM_DB = "C:\\Users\\Nicolas\\Bourgogne\\burgundy-manager\\data\\burgundy.db";

// ─── BM types ─────────────────────────────────────────────────────────────────

interface BmDomaine  { id: number; name: string; region: string|null; lat: number|null; lng: number|null; tier: number|null; }
interface BmCuvee    { id: number; domaine_id: number; name: string; appellation_id: number|null; appellation_name: string|null; cepage: string|null; color: string|null; }
interface BmRating   { id: number; cuvee_id: number; vintage: number; critic: string; score: number; scale: string; date_recorded: number; }

type WineColor  = "red"|"white"|"rosé"|"sparkling"|"sweet"|"fortified"|"orange";
type CriticCode = "WA"|"Vinous"|"BH"|"JMIB"|"RVF"|"Decanter"|"JS"|"JG"|"JD"|"WS"|"Hachette"|"CT"|"XW"|"WE"|"VI";

const VALID_CRITICS = new Set(["WA","Vinous","BH","JMIB","RVF","Decanter","JS","JG","JD","WS","Hachette","CT","XW","WE","VI"]);
const VALID_SCALES  = new Set(["/100","/20","/5","stars"]);

// ─── Color mapping ────────────────────────────────────────────────────────────

function bmColorToAchilles(c: string|null): WineColor {
  switch ((c ?? "").toUpperCase()) {
    case "W":  return "white";
    case "R":  return "red";
    case "P":  return "rosé";
    case "S":  return "sparkling";
    case "SW": return "sweet";
    default:   return "red";
  }
}

// ─── Region from appellation name ─────────────────────────────────────────────

function regionFromApp(appName: string|null): string {
  const n = (appName ?? "").toLowerCase();
  if (n.includes("champagne"))  return "Champagne";
  if (n.includes("bordeaux") || n.includes("pauillac") || n.includes("margaux") ||
      n.includes("saint-émilion") || n.includes("pomerol") || n.includes("graves")) return "Bordeaux";
  if (n.includes("alsace"))     return "Alsace";
  if (n.includes("rhône") || n.includes("hermitage") || n.includes("côte-rôtie") ||
      n.includes("châteauneuf")) return "Rhône";
  if (n.includes("sancerre") || n.includes("chinon") || n.includes("vouvray") ||
      n.includes("muscadet"))   return "Loire";
  return "Bourgogne";
}

// ─── Main ─────────────────────────────────────────────────────────────────────

function main() {
  const bm = new Database(BM_DB, { readonly: true });
  const domaines = bm.prepare(`SELECT id,name,region,lat,lng,tier FROM domaines`).all() as BmDomaine[];
  const cuvees   = bm.prepare(`SELECT * FROM cuvees`).all() as BmCuvee[];
  const ratings  = bm.prepare(`SELECT * FROM ratings ORDER BY cuvee_id, vintage`).all() as BmRating[];
  bm.close();

  console.log(`📥  ${cuvees.length} cuvées + ${ratings.length} ratings from burgundy-manager`);

  // Build lookup maps
  const domaineMap = new Map<number, BmDomaine>(domaines.map(d => [d.id, d]));
  const cuveeMap   = new Map<number, BmCuvee>(cuvees.map(c => [c.id, c]));

  const batchId   = randomUUID();
  const sourceKey = db
    .select({ sourceKey: schema.dimSource.sourceKey })
    .from(schema.dimSource)
    .where(eq(schema.dimSource.sourceCode, "burgundy_manager"))
    .get()?.sourceKey;

  if (!sourceKey) throw new Error("Source 'burgundy_manager' not found in dim_source. Run db:seed first.");

  db.insert(schema.opsBatchLog).values({
    batchId, sourceKey, startedAt: new Date(), status: "running",
    rowsFetched: cuvees.length + ratings.length,
  }).run();

  // Producer cache: producerNorm|CC → producerKey
  const producerCache    = new Map<string, number>();
  // Appellation cache: appNorm|CC → appellationKey
  const appellationCache = new Map<string, number>();
  // Wine cache: wineKey → boolean (already inserted)
  const wineCache        = new Set<string>();

  let winesInserted = 0, winesSkipped = 0, ratingsStaged = 0, dlq = 0;
  const now = new Date();

  // ── Helper: resolve or create producer ────────────────────────────────────
  function resolveProducer(domaine: BmDomaine): number|null {
    const producerNorm = normalizeProducer(domaine.name);
    const key = `${producerNorm}|FR`;
    if (producerCache.has(key)) return producerCache.get(key)!;

    const ex = db
      .select({ producerKey: schema.dimProducer.producerKey })
      .from(schema.dimProducer)
      .where(and(eq(schema.dimProducer.producerNorm, producerNorm), eq(schema.dimProducer.countryCode, "FR")))
      .get();

    if (ex) {
      producerCache.set(key, ex.producerKey);
      return ex.producerKey;
    }
    // Insert on-the-fly (shouldn't happen if import-bm-producers ran first, but safe)
    const [p] = db.insert(schema.dimProducer).values({
      producerName: domaine.name, producerNorm, countryCode: "FR",
      region: "Bourgogne", allowedAppellations: [], aliases: [],
      status: "active", coverageTier: "long_tail",
    }).returning({ producerKey: schema.dimProducer.producerKey }).all();
    producerCache.set(key, p.producerKey);
    return p.producerKey;
  }

  // ── Helper: resolve or create appellation ─────────────────────────────────
  function resolveAppellation(appName: string|null): number {
    const name    = appName || "Bourgogne";
    const appNorm = normText(name);
    const key     = `${appNorm}|FR`;
    if (appellationCache.has(key)) return appellationCache.get(key)!;

    const ex = db
      .select({ appellationKey: schema.dimAppellation.appellationKey })
      .from(schema.dimAppellation)
      .where(and(eq(schema.dimAppellation.appellationNorm, appNorm), eq(schema.dimAppellation.countryCode, "FR")))
      .get();

    if (ex) { appellationCache.set(key, ex.appellationKey); return ex.appellationKey; }

    const [a] = db.insert(schema.dimAppellation).values({
      countryCode: "FR", region: regionFromApp(appName),
      appellationName: name, appellationNorm: appNorm, level: "regional",
    }).returning({ appellationKey: schema.dimAppellation.appellationKey }).all();
    appellationCache.set(key, a.appellationKey);
    return a.appellationKey;
  }

  // ── Helper: resolve or create dim_wine ────────────────────────────────────
  function resolveWine(
    cuvee: BmCuvee, vintage: number|null,
    producerKey: number, appellationKey: number,
  ): string|null {
    const domaine = domaineMap.get(cuvee.domaine_id);
    if (!domaine) return null;

    const producerNorm  = normalizeProducer(domaine.name);
    const cuveeNorm     = normalizeCuvee(cuvee.name, [producerNorm]);
    const color         = bmColorToAchilles(cuvee.color);
    const wineKey       = computeWineKey({ producerNorm, cuveeNorm, vintage });

    if (wineCache.has(wineKey)) return wineKey;

    const ex = db.select({ wineKey: schema.dimWine.wineKey }).from(schema.dimWine)
      .where(eq(schema.dimWine.wineKey, wineKey)).get();

    if (ex) {
      db.update(schema.dimWine).set({ lastSeenAt: now }).where(eq(schema.dimWine.wineKey, wineKey)).run();
      wineCache.add(wineKey);
      winesSkipped++;
      return wineKey;
    }

    const canonicalName = [domaine.name, cuvee.name, vintage ? String(vintage) : "NV"].join(" · ");
    db.insert(schema.dimWine).values({
      wineKey, producerKey, appellationKey,
      cuveeName: cuvee.name, cuveeNorm, color,
      vintage, isNonVintage: vintage === null,
      bottleMl: 750, canonicalName,
    }).run();
    wineCache.add(wineKey);
    winesInserted++;
    return wineKey;
  }

  // ── Process ratings (create wines on the fly per vintage) ─────────────────
  console.log("   Processing ratings + creating per-vintage wines…");
  for (let i = 0; i < ratings.length; i++) {
    if ((i + 1) % 5000 === 0) console.log(`   … ${i + 1}/${ratings.length} ratings`);
    const rating = ratings[i];

    try {
      const cuvee = cuveeMap.get(rating.cuvee_id);
      if (!cuvee) throw new Error(`cuvee_id ${rating.cuvee_id} not found`);
      const domaine = domaineMap.get(cuvee.domaine_id);
      if (!domaine) throw new Error(`domaine_id ${cuvee.domaine_id} not found`);
      if (!VALID_CRITICS.has(rating.critic)) throw new Error(`Unknown critic: ${rating.critic}`);
      if (!VALID_SCALES.has(rating.scale))   throw new Error(`Unknown scale: ${rating.scale}`);

      const producerKey    = resolveProducer(domaine);
      if (!producerKey) throw new Error(`Cannot resolve producer for domaine ${domaine.id}`);
      const appellationKey = resolveAppellation(cuvee.appellation_name);
      const wineKey        = resolveWine(cuvee, rating.vintage, producerKey, appellationKey);
      if (!wineKey) throw new Error(`Cannot resolve wine for cuvee ${cuvee.id}`);

      const scoreNorm = normalizeScoreTo100(rating.score, rating.scale as "/100"|"/20"|"/5"|"stars");
      const contentHash = createHash("sha1")
        .update(`${wineKey}|${rating.critic}|${rating.score}|${rating.vintage}`)
        .digest("hex").slice(0, 32);

      try {
        db.insert(schema.stagingRatingCandidates).values({
          wineKey, sourceKey,
          criticCode:        rating.critic as CriticCode,
          reviewerType:      "critic",
          score:             rating.score,
          scale:             rating.scale as "/100"|"/20"|"/5"|"stars",
          scoreNormalized100: scoreNorm,
          recordedAt:        new Date(rating.date_recorded * 1000),
          contentHash,
          batchId,
          needsReview:       true,
        }).run();
        ratingsStaged++;
      } catch { /* duplicate */ }

    } catch (err) {
      db.insert(schema.opsDeadLetter).values({
        sourceKey, batchId, errorClass: "validation_error",
        errorMessage: String(err),
        sourceRecordId: String(rating.id),
        rawRecord: JSON.stringify(rating), resolution: "pending",
      }).run();
      dlq++;
    }
  }

  // ── Create NV stubs for cuvées with no ratings ─────────────────────────────
  console.log("   Creating NV stubs for cuvées without ratings…");
  const ratedCuveeIds = new Set(ratings.map(r => r.cuvee_id));
  let nvStubs = 0;
  for (const cuvee of cuvees) {
    if (ratedCuveeIds.has(cuvee.id)) continue;
    try {
      const domaine = domaineMap.get(cuvee.domaine_id);
      if (!domaine) continue;
      const producerKey    = resolveProducer(domaine);
      if (!producerKey) continue;
      const appellationKey = resolveAppellation(cuvee.appellation_name);
      resolveWine(cuvee, null, producerKey, appellationKey);
      nvStubs++;
    } catch { /* skip */ }
  }

  // ── Finalise ───────────────────────────────────────────────────────────────
  db.update(schema.opsBatchLog).set({
    finishedAt: now,
    status: dlq > (ratings.length * 0.05) ? "partial" : "success",
    rowsInserted: winesInserted + ratingsStaged,
    rowsUpdated:  winesSkipped,
    rowsDlq:      dlq,
  }).where(eq(schema.opsBatchLog.batchId, batchId)).run();

  console.log(`\n✅  Cuvées + ratings import complete`);
  console.log(`   Wines new    : ${winesInserted}`);
  console.log(`   Wines NV stubs: ${nvStubs}`);
  console.log(`   Wines updated: ${winesSkipped}`);
  console.log(`   Ratings staged: ${ratingsStaged}`);
  console.log(`   DLQ          : ${dlq}`);
  console.log(`   Batch        : ${batchId}`);
}

main();
