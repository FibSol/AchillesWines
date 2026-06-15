import { db } from "@/db";
import {
  dimProducer,
  dimWine,
  dimAppellation,
  dimVariety,
  bridgeWineVariety,
  cellarInventory,
  factPrice,
  factRating,
} from "@/db/schema";
import { eq, inArray } from "drizzle-orm";
import type { CuveeYearPoint } from "@/components/DomaineCharts";
import type { DetailRow } from "@/components/DomaineDetailTable";

export interface VarietyInfo {
  varietyName: string;
  colorFamily: string;
}

export interface CuveeSummary {
  cuveeName: string;
  appellationName: string;
  color: string;
  vintageCount: number;
  bestRating: number | null;
  priceMin: number | null;
  priceMax: number | null;
  sourceCount: number;
  tier: "flagship" | "normal" | "entry";
}

export interface ProducerDetail {
  producer: typeof dimProducer.$inferSelect;
  varieties: VarietyInfo[];
  cuveeSummaries: CuveeSummary[];
  cuveeYearPoints: CuveeYearPoint[];
  detailRows: DetailRow[];
}

/**
 * Full producer (domaine) profile: producer row, grape varieties, per-cuvée
 * summaries, vintage chart points, and per-wine detail rows. Shared by the
 * domaine detail page (SSR) and GET /api/producers/[id]. Returns null if the
 * producer does not exist.
 */
export async function getProducerDetail(producerKey: number): Promise<ProducerDetail | null> {
  const producerRows = await db
    .select()
    .from(dimProducer)
    .where(eq(dimProducer.producerKey, producerKey))
    .limit(1);

  const producer = producerRows[0];
  if (!producer) return null;

  const wines = await db
    .select({
      wineKey: dimWine.wineKey,
      cuveeName: dimWine.cuveeName,
      canonicalName: dimWine.canonicalName,
      vintage: dimWine.vintage,
      isNonVintage: dimWine.isNonVintage,
      color: dimWine.color,
      classification: dimWine.classification,
      alcoholPct: dimWine.alcoholPct,
      bottleMl: dimWine.bottleMl,
      appellationName: dimAppellation.appellationName,
    })
    .from(dimWine)
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .where(eq(dimWine.producerKey, producerKey));

  const wineKeys = wines.map((w) => w.wineKey);

  if (wineKeys.length === 0) {
    return { producer, varieties: [], cuveeSummaries: [], cuveeYearPoints: [], detailRows: [] };
  }

  const [prices, ratings, varietyRows, cellarRows] = await Promise.all([
    db.select().from(factPrice).where(inArray(factPrice.wineKey, wineKeys)),
    db.select().from(factRating).where(inArray(factRating.wineKey, wineKeys)),
    db
      .select({
        wineKey: bridgeWineVariety.wineKey,
        varietyName: dimVariety.varietyName,
        colorFamily: dimVariety.colorFamily,
      })
      .from(bridgeWineVariety)
      .innerJoin(dimVariety, eq(bridgeWineVariety.varietyKey, dimVariety.varietyKey))
      .where(inArray(bridgeWineVariety.wineKey, wineKeys)),
    db
      .select({ wineKey: cellarInventory.wineKey, qty: cellarInventory.qty })
      .from(cellarInventory)
      .where(inArray(cellarInventory.wineKey, wineKeys)),
  ]);

  // Index prices and ratings by wineKey
  const pricesByWine = new Map<string, typeof prices>();
  for (const p of prices) {
    const arr = pricesByWine.get(p.wineKey) ?? [];
    arr.push(p);
    pricesByWine.set(p.wineKey, arr);
  }
  const ratingsByWine = new Map<string, typeof ratings>();
  for (const r of ratings) {
    const arr = ratingsByWine.get(r.wineKey) ?? [];
    arr.push(r);
    ratingsByWine.set(r.wineKey, arr);
  }

  // Cellar qty aggregated by wineKey
  const cellarQty = new Map<string, number>();
  for (const row of cellarRows) {
    cellarQty.set(row.wineKey, (cellarQty.get(row.wineKey) ?? 0) + row.qty);
  }

  // Unique varieties across all wines of this producer
  const seenVarieties = new Map<string, VarietyInfo>();
  for (const v of varietyRows) {
    if (!seenVarieties.has(v.varietyName)) {
      seenVarieties.set(v.varietyName, { varietyName: v.varietyName, colorFamily: v.colorFamily });
    }
  }
  const varieties = Array.from(seenVarieties.values());

  /* ── Cuvée summaries (aggregated — no vintage) ── */
  const cuveeMap = new Map<
    string,
    {
      cuveeName: string;
      appellationName: string;
      color: string;
      vintages: Set<number>;
      allRatings: number[];
      allPrices: number[];
      sources: Set<number>;
    }
  >();

  for (const w of wines) {
    const existing = cuveeMap.get(w.cuveeName) ?? {
      cuveeName: w.cuveeName,
      appellationName: w.appellationName,
      color: w.color,
      vintages: new Set<number>(),
      allRatings: [],
      allPrices: [],
      sources: new Set<number>(),
    };
    if (w.vintage) existing.vintages.add(w.vintage);

    for (const p of pricesByWine.get(w.wineKey) ?? []) {
      if (typeof p.amountEur === "number" && p.amountEur > 0) existing.allPrices.push(p.amountEur);
      existing.sources.add(p.sourceKey);
    }
    for (const r of ratingsByWine.get(w.wineKey) ?? []) {
      existing.allRatings.push(r.scoreNormalized100);
      existing.sources.add(r.sourceKey);
    }
    cuveeMap.set(w.cuveeName, existing);
  }

  const cuveeSummaries: CuveeSummary[] = Array.from(cuveeMap.values())
    .map((c) => {
      const bestRating = c.allRatings.length > 0 ? Math.max(...c.allRatings) : null;
      const tier: "flagship" | "normal" | "entry" =
        bestRating === null ? "entry" : bestRating >= 94 ? "flagship" : bestRating >= 88 ? "normal" : "entry";
      return {
        cuveeName: c.cuveeName,
        appellationName: c.appellationName,
        color: c.color,
        vintageCount: c.vintages.size,
        bestRating,
        priceMin: c.allPrices.length > 0 ? Math.min(...c.allPrices) : null,
        priceMax: c.allPrices.length > 0 ? Math.max(...c.allPrices) : null,
        sourceCount: c.sources.size,
        tier,
      };
    })
    .sort((a, b) => (b.bestRating ?? -1) - (a.bestRating ?? -1));

  /* ── Chart data: one point per (cuveeName, vintage) ── */
  const cuveeYearPoints: CuveeYearPoint[] = [];
  for (const w of wines) {
    if (!w.vintage) continue;
    const wPrices = (pricesByWine.get(w.wineKey) ?? [])
      .map((p) => p.amountEur)
      .filter((v): v is number => typeof v === "number" && v > 0);
    const wRatings = (ratingsByWine.get(w.wineKey) ?? []).map((r) => r.scoreNormalized100);
    cuveeYearPoints.push({
      cuveeName: w.cuveeName,
      vintage: w.vintage,
      avgPrice: wPrices.length > 0 ? wPrices.reduce((a, b) => a + b) / wPrices.length : null,
      bestRating: wRatings.length > 0 ? Math.max(...wRatings) : null,
    });
  }

  /* ── Detail rows: one per wine entity ── */
  const detailRows: DetailRow[] = wines
    .map((w) => {
      const wPrices = pricesByWine.get(w.wineKey) ?? [];
      const wRatings = ratingsByWine.get(w.wineKey) ?? [];
      const priceValues = wPrices
        .map((p) => p.amountEur)
        .filter((v): v is number => typeof v === "number" && v > 0);
      const ratingScores = wRatings.map((r) => r.scoreNormalized100);

      const criticBest = new Map<string, number>();
      for (const r of wRatings) {
        const prev = criticBest.get(r.criticCode) ?? 0;
        if (r.scoreNormalized100 > prev) criticBest.set(r.criticCode, r.scoreNormalized100);
      }
      const criticBreakdown = Array.from(criticBest.entries())
        .map(([criticCode, score]) => ({ criticCode, score }))
        .sort((a, b) => b.score - a.score);

      return {
        wineKey: w.wineKey,
        canonicalName: w.canonicalName,
        cuveeName: w.cuveeName,
        vintage: w.vintage,
        isNonVintage: w.isNonVintage,
        appellationName: w.appellationName,
        color: w.color,
        classification: w.classification,
        alcoholPct: w.alcoholPct,
        bottleMl: w.bottleMl,
        bestRating: ratingScores.length > 0 ? Math.max(...ratingScores) : null,
        criticBreakdown,
        priceMin: priceValues.length > 0 ? Math.min(...priceValues) : null,
        priceMax: priceValues.length > 0 ? Math.max(...priceValues) : null,
        inCellar: cellarQty.get(w.wineKey) ?? 0,
        sourceCount: new Set([
          ...wPrices.map((p) => p.sourceKey),
          ...wRatings.map((r) => r.sourceKey),
        ]).size,
      } satisfies DetailRow;
    })
    .sort((a, b) => {
      if (a.cuveeName !== b.cuveeName) return a.cuveeName.localeCompare(b.cuveeName);
      return (b.vintage ?? 0) - (a.vintage ?? 0);
    });

  return { producer, varieties, cuveeSummaries, cuveeYearPoints, detailRows };
}
