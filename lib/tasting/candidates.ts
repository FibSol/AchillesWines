/**
 * Loads the in-stock cellar wines and enriches each with everything the tasting
 * engine needs (grape, region, ratings, vintage score, price). Server-only —
 * imports the Drizzle client. Keeps DB concerns out of the pure engine.
 */

import { db } from "@/db";
import {
  dimWine,
  dimProducer,
  dimAppellation,
  dimVariety,
  bridgeWineVariety,
  cellarInventory,
  factPrice,
  factRating,
  factVintageRating,
} from "@/db/schema";
import { eq, sql, inArray, and } from "drizzle-orm";
import type { WineColor } from "@/lib/pairing";
import type { AppellationLevel, TastingCandidate } from "@/lib/tasting/engine";

/**
 * Returns one row per unique in-stock wine (qty summed across locations),
 * with average rating, average price, dominant grape and the matching
 * region × vintage × color vintage-chart score.
 */
export async function loadTastingCandidates(): Promise<TastingCandidate[]> {
  // 1. In-stock wines (qty > 0), aggregated across locations.
  const rows = await db
    .select({
      wineKey: dimWine.wineKey,
      canonicalName: dimWine.canonicalName,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      isNonVintage: dimWine.isNonVintage,
      color: dimWine.color,
      alcoholPct: dimWine.alcoholPct,
      producerName: dimProducer.producerName,
      appellationName: dimAppellation.appellationName,
      countryCode: dimAppellation.countryCode,
      region: dimAppellation.region,
      subregion: dimAppellation.subregion,
      level: dimAppellation.level,
      qty: sql<number>`coalesce(sum(${cellarInventory.qty}), 0)`,
    })
    .from(cellarInventory)
    .innerJoin(dimWine, eq(cellarInventory.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .groupBy(dimWine.wineKey)
    .having(sql`coalesce(sum(${cellarInventory.qty}), 0) > 0`);

  if (rows.length === 0) return [];

  const wineKeys = rows.map((r) => r.wineKey);

  // 2. Aggregates: ratings, prices, dominant grape.
  const [ratingAgg, priceAgg, varietyRows] = await Promise.all([
    db
      .select({
        wineKey: factRating.wineKey,
        avgRating: sql<number>`avg(${factRating.scoreNormalized100})`,
      })
      .from(factRating)
      .where(inArray(factRating.wineKey, wineKeys))
      .groupBy(factRating.wineKey),
    db
      .select({
        wineKey: factPrice.wineKey,
        avgPrice: sql<number>`avg(${factPrice.amountEur})`,
      })
      .from(factPrice)
      .where(inArray(factPrice.wineKey, wineKeys))
      .groupBy(factPrice.wineKey),
    db
      .select({
        wineKey: bridgeWineVariety.wineKey,
        varietyName: dimVariety.varietyName,
        sharePct: bridgeWineVariety.sharePct,
      })
      .from(bridgeWineVariety)
      .innerJoin(dimVariety, eq(bridgeWineVariety.varietyKey, dimVariety.varietyKey))
      .where(inArray(bridgeWineVariety.wineKey, wineKeys)),
  ]);

  const ratingByWine = new Map<string, number>();
  for (const r of ratingAgg) {
    if (r.avgRating !== null) ratingByWine.set(r.wineKey, Number(r.avgRating));
  }
  const priceByWine = new Map<string, number>();
  for (const r of priceAgg) {
    if (r.avgPrice !== null && r.avgPrice > 0) priceByWine.set(r.wineKey, Number(r.avgPrice));
  }

  // Full grape blend per wine, ordered by share (descending), name as tiebreak.
  const blendByWine = new Map<string, Array<{ name: string; share: number }>>();
  for (const v of varietyRows) {
    if (!blendByWine.has(v.wineKey)) blendByWine.set(v.wineKey, []);
    blendByWine.get(v.wineKey)!.push({ name: v.varietyName, share: v.sharePct ?? 0 });
  }
  const varietiesByWine = new Map<string, string[]>();
  for (const [wineKey, blend] of blendByWine) {
    blend.sort((a, b) => b.share - a.share || a.name.localeCompare(b.name));
    varietiesByWine.set(wineKey, blend.map((b) => b.name));
  }

  // 3. Vintage-chart scores: fetch all relevant (region, vintage) pairs once.
  const regionVintagePairs = rows
    .filter((r) => r.vintage !== null)
    .map((r) => ({ countryCode: r.countryCode, region: r.region, vintage: r.vintage as number }));

  const vintageScoreByKey = new Map<string, number>();
  if (regionVintagePairs.length > 0) {
    const uniqueRegions = [...new Set(rows.map((r) => `${r.countryCode}|${r.region}`))];
    const uniqueVintages = [
      ...new Set(rows.map((r) => r.vintage).filter((v): v is number => v !== null)),
    ];
    const vrRows = await db
      .select({
        countryCode: factVintageRating.countryCode,
        region: factVintageRating.region,
        color: factVintageRating.color,
        vintage: factVintageRating.vintage,
        score: factVintageRating.scoreNormalized100,
      })
      .from(factVintageRating)
      .where(
        and(
          inArray(factVintageRating.vintage, uniqueVintages),
          inArray(
            sql`${factVintageRating.countryCode} || '|' || ${factVintageRating.region}`,
            uniqueRegions,
          ),
        ),
      );
    // Index by country|region|vintage|color, and a color-agnostic fallback.
    const byExact = new Map<string, number[]>();
    const byAny = new Map<string, number[]>();
    for (const v of vrRows) {
      const base = `${v.countryCode}|${v.region}|${v.vintage}`;
      pushTo(byExact, `${base}|${v.color}`, v.score);
      pushTo(byAny, base, v.score);
    }
    for (const r of rows) {
      if (r.vintage === null) continue;
      const base = `${r.countryCode}|${r.region}|${r.vintage}`;
      const exact = byExact.get(`${base}|${r.color}`) ?? byExact.get(`${base}|all`);
      const any = byAny.get(base);
      const pick = exact ?? any;
      if (pick && pick.length > 0) {
        vintageScoreByKey.set(r.wineKey, avg(pick));
      }
    }
  }

  // 4. Assemble candidates.
  return rows.map((r): TastingCandidate => ({
    wineKey: r.wineKey,
    producerName: r.producerName,
    cuveeName: r.cuveeName,
    canonicalName: r.canonicalName,
    vintage: r.vintage,
    isNonVintage: r.isNonVintage,
    color: r.color as WineColor,
    alcoholPct: r.alcoholPct,
    appellationName: r.appellationName,
    countryCode: r.countryCode,
    region: r.region,
    subregion: r.subregion,
    level: r.level as AppellationLevel,
    primaryVariety: varietiesByWine.get(r.wineKey)?.[0] ?? null,
    varieties: varietiesByWine.get(r.wineKey) ?? [],
    avgRating: ratingByWine.get(r.wineKey) ?? null,
    vintageScore: vintageScoreByKey.get(r.wineKey) ?? null,
    avgPriceEur: priceByWine.get(r.wineKey) ?? null,
    qty: Number(r.qty ?? 0),
  }));
}

function pushTo(m: Map<string, number[]>, k: string, v: number): void {
  if (!m.has(k)) m.set(k, []);
  m.get(k)!.push(v);
}
function avg(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}
