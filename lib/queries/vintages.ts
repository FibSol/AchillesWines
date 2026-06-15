import { db } from "@/db";
import { dimWine, dimProducer, dimAppellation, factVintageRating, factPrice, factRating } from "@/db/schema";
import { eq, and, gte, lte, inArray, isNotNull, sql } from "drizzle-orm";
import type { VintageCell } from "@/components/VintageHeatmap";
import type { DivergenceCell } from "@/components/VintageDivergenceHeatmap";

export interface VintageHeatmapData {
  cells: VintageCell[];
  regions: string[];
  years: number[];
}

export interface VintageWineRow {
  wineKey: string;
  producerKey: number;
  producerName: string;
  cuveeName: string;
  canonicalName: string;
  color: string;
  appellationName: string;
  sourceCount: number;
}

/**
 * Critic-divergence cells (score spread per vintage × critic, 1990–2024).
 * Optionally scoped to a region. Shared by the vintages page (SSR) and
 * GET /api/vintages/heatmap.
 */
export async function getVintageDivergence(region?: string): Promise<DivergenceCell[]> {
  const rows = await db
    .select({
      year: dimWine.vintage,
      critic: factRating.criticCode,
      avg: sql<number>`round(avg(${factRating.scoreNormalized100}), 1)`,
      count: sql<number>`cast(count(*) as integer)`,
      // SQLite has no STDEV — approximate with sqrt(avg(x^2) - avg(x)^2)
      divergence: sql<number>`round(
        sqrt(
          max(0,
            avg(${factRating.scoreNormalized100} * ${factRating.scoreNormalized100})
            - avg(${factRating.scoreNormalized100}) * avg(${factRating.scoreNormalized100})
          )
        ),
        1
      )`,
    })
    .from(factRating)
    .innerJoin(dimWine, eq(factRating.wineKey, dimWine.wineKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .where(
      and(
        gte(dimWine.vintage, 1990),
        lte(dimWine.vintage, 2024),
        ...(region ? [eq(dimAppellation.region, region)] : []),
      )
    )
    .groupBy(dimWine.vintage, factRating.criticCode)
    .having(sql`count(*) >= 3`);

  return rows
    .filter((r) => r.year !== null)
    .map((r) => ({
      year: r.year as number,
      critic: r.critic,
      avg: Number(r.avg),
      count: Number(r.count),
      divergence: Number(r.divergence),
    }));
}

/**
 * Density heatmap cells: wine count per (region, vintage) crossed with regional
 * vintage scores, plus the sorted region/year axes. Shared by the vintages page
 * (SSR) and GET /api/vintages/heatmap.
 */
export async function getVintageHeatmap(): Promise<VintageHeatmapData> {
  // Wine counts per (region, vintage) from the producer registry
  const wineCounts = await db
    .select({
      countryCode: dimAppellation.countryCode,
      region: dimAppellation.region,
      vintage: dimWine.vintage,
      wineCount: sql<number>`cast(count(*) as integer)`,
    })
    .from(dimWine)
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .where(and(isNotNull(dimWine.vintage), gte(dimWine.vintage, 1980)))
    .groupBy(dimAppellation.countryCode, dimAppellation.region, dimWine.vintage);

  // Vintage scores from fact_vintage_rating
  const vintageScores = await db
    .select({
      countryCode: factVintageRating.countryCode,
      region: factVintageRating.region,
      vintage: factVintageRating.vintage,
      avgScore: sql<number>`avg(${factVintageRating.scoreNormalized100})`,
    })
    .from(factVintageRating)
    .where(gte(factVintageRating.vintage, 1980))
    .groupBy(factVintageRating.countryCode, factVintageRating.region, factVintageRating.vintage);

  const scoreMap = new Map<string, { score: number; countryCode: string }>();
  for (const s of vintageScores) {
    scoreMap.set(`${s.region}|${s.vintage}`, {
      score: Number(s.avgScore),
      countryCode: s.countryCode,
    });
  }

  const cellMap = new Map<string, VintageCell>();

  // Cells from wine counts
  for (const r of wineCounts) {
    if (r.vintage === null || !r.region) continue;
    const key = `${r.region}|${r.vintage}`;
    const sc = scoreMap.get(key);
    cellMap.set(key, {
      region: r.region,
      countryCode: r.countryCode ?? sc?.countryCode ?? "??",
      vintage: r.vintage,
      wineCount: Number(r.wineCount),
      avgScore: sc?.score ?? null,
    });
  }

  // Additional cells from vintage scores with no wines
  for (const s of vintageScores) {
    const key = `${s.region}|${s.vintage}`;
    if (!cellMap.has(key)) {
      cellMap.set(key, {
        region: s.region,
        countryCode: s.countryCode,
        vintage: s.vintage,
        wineCount: 0,
        avgScore: Number(s.avgScore),
      });
    }
  }

  const cells = Array.from(cellMap.values());
  if (cells.length === 0) return { cells: [], regions: [], years: [] };

  const yearsSet = new Set(cells.map((c) => c.vintage));
  const years = Array.from(yearsSet).sort((a, b) => a - b);

  const regionTotals = new Map<string, number>();
  for (const c of cells) {
    regionTotals.set(c.region, (regionTotals.get(c.region) ?? 0) + c.wineCount);
  }
  const regions = Array.from(regionTotals.keys()).sort(
    (a, b) => (regionTotals.get(b) ?? 0) - (regionTotals.get(a) ?? 0)
  );

  return { cells, regions, years };
}

/**
 * Wines from a given region × vintage, enriched with distinct source counts,
 * plus the regional vintage average score. Shared by the vintage detail page
 * (SSR) and GET /api/vintages/wines.
 */
export async function getVintageWines(region: string, vintage: number): Promise<{
  wines: VintageWineRow[];
  avgScore: number | null;
}> {
  const [wineRows, scoreRows] = await Promise.all([
    db
      .select({
        wineKey: dimWine.wineKey,
        producerKey: dimProducer.producerKey,
        producerName: dimProducer.producerName,
        cuveeName: dimWine.cuveeName,
        canonicalName: dimWine.canonicalName,
        color: dimWine.color,
        appellationName: dimAppellation.appellationName,
      })
      .from(dimWine)
      .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .where(and(eq(dimAppellation.region, region), eq(dimWine.vintage, vintage)))
      .limit(200),

    db
      .select({ avgScore: sql<number>`avg(${factVintageRating.scoreNormalized100})` })
      .from(factVintageRating)
      .where(and(eq(factVintageRating.region, region), eq(factVintageRating.vintage, vintage))),
  ]);

  const avgScore = scoreRows[0]?.avgScore != null ? Number(scoreRows[0].avgScore) : null;

  if (wineRows.length === 0) {
    return { wines: [], avgScore };
  }

  const wineKeys = wineRows.map((w) => w.wineKey);
  const [priceSrc, ratingSrc] = await Promise.all([
    db.select({ wineKey: factPrice.wineKey, sourceKey: factPrice.sourceKey })
      .from(factPrice).where(inArray(factPrice.wineKey, wineKeys))
      .groupBy(factPrice.wineKey, factPrice.sourceKey),
    db.select({ wineKey: factRating.wineKey, sourceKey: factRating.sourceKey })
      .from(factRating).where(inArray(factRating.wineKey, wineKeys))
      .groupBy(factRating.wineKey, factRating.sourceKey),
  ]);

  const sourcesByWine = new Map<string, Set<number>>();
  for (const r of [...priceSrc, ...ratingSrc]) {
    if (!sourcesByWine.has(r.wineKey)) sourcesByWine.set(r.wineKey, new Set());
    sourcesByWine.get(r.wineKey)!.add(r.sourceKey);
  }

  const wines: VintageWineRow[] = wineRows.map((w) => ({
    ...w,
    sourceCount: sourcesByWine.get(w.wineKey)?.size ?? 0,
  }));

  return { wines, avgScore };
}
