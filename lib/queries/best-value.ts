import { db } from "@/db";
import { dimWine, dimProducer, dimAppellation, factPrice, factRating, stagingPriceCandidates } from "@/db/schema";
import { sql, desc, eq, and, gt, isNotNull, inArray } from "drizzle-orm";
import { deriveConfidence, type Confidence } from "@/components/ConfidenceBadge";

export type DrinkingIntent = "drink_now" | "cellar_10" | "invest";

export interface FilterParams {
  country?: string;
  region?: string;
  vintage?: number;
  color?: string;
  minPrice?: number;
  maxPrice?: number;
  minRating?: number;
  maxRating?: number;
  drinkingIntent?: DrinkingIntent;
}

export interface BestValueFilterOptions {
  countries: Array<{ code: string; name: string }>;
  regions: string[];
  vintages: number[];
}

export interface BestValueRow {
  wineKey: string;
  canonicalName: string;
  producerKey: number;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  color: string | null;
  classification: string | null;
  appellationName: string;
  score: number;
  priceEur: number;
  minPriceEur: number;
  maxPriceEur: number;
  ratingNorm100: number;
  confidence: Confidence;
  sourceCount: number;
}

const CURRENT_YEAR = 2026;

/**
 * Filter dropdown options (countries / regions / vintages) for wines that have
 * at least one price. Shared by the best-value page (SSR) and
 * GET /api/best-value/filter-options.
 */
export async function getBestValueFilterOptions(locale: string, country?: string): Promise<BestValueFilterOptions> {
  const countryNames = new Intl.DisplayNames([locale], { type: "region" });

  const [countriesResult, regionsResult, vintagesResult] = await Promise.all([
    db
      .selectDistinct({ countryCode: dimAppellation.countryCode })
      .from(dimAppellation)
      .innerJoin(dimWine, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .innerJoin(factPrice, eq(factPrice.wineKey, dimWine.wineKey))
      .orderBy(dimAppellation.countryCode),
    db
      .selectDistinct({ region: dimAppellation.region })
      .from(dimAppellation)
      .innerJoin(dimWine, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .innerJoin(factPrice, eq(factPrice.wineKey, dimWine.wineKey))
      .where(country ? eq(dimAppellation.countryCode, country) : undefined)
      .orderBy(dimAppellation.region),
    db
      .selectDistinct({ vintage: dimWine.vintage })
      .from(dimWine)
      .innerJoin(factPrice, eq(factPrice.wineKey, dimWine.wineKey))
      .where(isNotNull(dimWine.vintage))
      .orderBy(desc(dimWine.vintage)),
  ]);

  const countries = countriesResult
    .map((r) => r.countryCode)
    .filter(Boolean)
    .map((code) => ({ code: code as string, name: countryNames.of(code as string) ?? (code as string) }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return {
    countries,
    regions: regionsResult.map((r) => r.region).filter(Boolean) as string[],
    vintages: vintagesResult.map((v) => v.vintage).filter(Boolean) as number[],
  };
}

export function matchesDrinkingIntent(wine: BestValueRow, intent: DrinkingIntent): boolean {
  const { vintage, color, classification, ratingNorm100, priceEur } = wine;
  const isWhiteOrRose = color === "white" || color === "rosé" || color === "orange";
  const age = vintage ? CURRENT_YEAR - vintage : null;

  if (intent === "drink_now") {
    if (vintage === null) return true; // NV wines: drink now
    if (isWhiteOrRose) return age !== null && age >= 3;
    return age !== null && age >= 6; // reds/sparkling: 6+ years
  }

  if (intent === "cellar_10") {
    if (vintage === null) return false;
    const isClassified = !!classification;
    const isHighRated = ratingNorm100 >= 85;
    if (isWhiteOrRose) return age !== null && age <= 3 && (isClassified || isHighRated);
    return age !== null && age <= 5 && (isClassified || isHighRated);
  }

  if (intent === "invest") {
    if (ratingNorm100 >= 93) return true;
    return ratingNorm100 >= 90 && priceEur >= 50;
  }

  return true;
}

/**
 * Best-value ranking engine. In rating mode (ratings present) scores wines by
 * rating²/log(price); otherwise falls back to a price-confidence score
 * (sources × price-agreement). Merges confirmed fact_price with single-source
 * staging candidates. Shared by the best-value page (SSR) and GET /api/best-value.
 */
export async function getBestValueWines(filters: FilterParams = {}): Promise<{ wines: BestValueRow[]; ratingMode: boolean }> {
  try {
    // Get average price + source count per wine from confirmed fact_price
    const prices = await db
      .select({
        wineKey: factPrice.wineKey,
        avgPrice: sql<number>`avg(${factPrice.amountEur})`,
        minPrice: sql<number>`min(${factPrice.amountEur})`,
        maxPrice: sql<number>`max(${factPrice.amountEur})`,
        srcCount: sql<number>`count(distinct ${factPrice.sourceKey})`,
      })
      .from(factPrice)
      .where(and(isNotNull(factPrice.amountEur), gt(factPrice.amountEur, 1)))
      .groupBy(factPrice.wineKey);

    // Also include staging prices for wines not yet promoted to fact_price (single-source candidates)
    const factPriceKeys = new Set(prices.map((p) => p.wineKey));
    const stagingRows = await db
      .select({
        wineKey: stagingPriceCandidates.wineKey,
        avgPrice: sql<number>`avg(${stagingPriceCandidates.amountEur})`,
        minPrice: sql<number>`min(${stagingPriceCandidates.amountEur})`,
        maxPrice: sql<number>`max(${stagingPriceCandidates.amountEur})`,
        srcCount: sql<number>`count(distinct ${stagingPriceCandidates.sourceKey})`,
      })
      .from(stagingPriceCandidates)
      .where(and(isNotNull(stagingPriceCandidates.amountEur), gt(stagingPriceCandidates.amountEur, 1)))
      .groupBy(stagingPriceCandidates.wineKey);

    // Merge: fact_price wins on overlap; staging fills in the rest
    let allPrices = [
      ...prices,
      ...stagingRows.filter((s) => !factPriceKeys.has(s.wineKey)),
    ];

    // Apply price filters
    if (filters.minPrice !== undefined) {
      allPrices = allPrices.filter((p) => p.avgPrice >= filters.minPrice!);
    }
    if (filters.maxPrice !== undefined) {
      allPrices = allPrices.filter((p) => p.avgPrice <= filters.maxPrice!);
    }

    if (allPrices.length === 0) return { wines: [], ratingMode: false };

    // Get average normalized rating + distinct source count per wine
    const ratings = await db
      .select({
        wineKey: factRating.wineKey,
        avgRating: sql<number>`avg(${factRating.scoreNormalized100})`,
        sourceCount: sql<number>`count(distinct ${factRating.sourceKey})`,
      })
      .from(factRating)
      .where(isNotNull(factRating.scoreNormalized100))
      .groupBy(factRating.wineKey);

    const hasRatings = ratings.length > 0;
    const priceMap = new Map(allPrices.map((p) => [p.wineKey, p]));
    const ratingMap = new Map(ratings.map((r) => [r.wineKey, { avg: r.avgRating, count: r.sourceCount }]));

    // In rating mode: only wines with both price + rating; in price-confidence mode: all price wines
    const eligibleKeys = hasRatings
      ? [...priceMap.keys()].filter((k) => {
          if (!ratingMap.has(k)) return false;
          const rating = ratingMap.get(k)!.avg;
          if (filters.minRating !== undefined && rating < filters.minRating) return false;
          if (filters.maxRating !== undefined && rating > filters.maxRating) return false;
          return true;
        })
      : [...priceMap.keys()];

    if (eligibleKeys.length === 0) return { wines: [], ratingMode: false };

    // Fetch wine + producer + appellation data for eligible keys (batched for SQLite)
    const BATCH = 200;
    const wineRows: Array<{
      wineKey: string; canonicalName: string; cuveeName: string;
      vintage: number | null; color: string | null; classification: string | null;
      producerKey: number; producerName: string; appellationName: string;
    }> = [];
    for (let i = 0; i < eligibleKeys.length; i += BATCH) {
      const batch = eligibleKeys.slice(i, i + BATCH);
      const rows = await db
        .select({
          wineKey: dimWine.wineKey,
          canonicalName: dimWine.canonicalName,
          cuveeName: dimWine.cuveeName,
          vintage: dimWine.vintage,
          color: dimWine.color,
          classification: dimWine.classification,
          producerKey: dimProducer.producerKey,
          producerName: dimProducer.producerName,
          appellationName: dimAppellation.appellationName,
        })
        .from(dimWine)
        .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
        .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
        .where(
          and(
            inArray(dimWine.wineKey, batch),
            filters.country ? eq(dimAppellation.countryCode, filters.country) : undefined,
            filters.vintage !== undefined ? eq(dimWine.vintage, filters.vintage) : undefined,
            filters.region ? eq(dimAppellation.region, filters.region) : undefined,
            filters.color ? eq(dimWine.color, filters.color as "red" | "white" | "rosé" | "sparkling" | "sweet" | "fortified" | "orange") : undefined,
          )
        )
        .execute();
      wineRows.push(...rows);
    }

    // Score and sort
    const scored: BestValueRow[] = wineRows
      .map((w) => {
        const pd = priceMap.get(w.wineKey);
        if (!pd) return null;
        const price = pd.avgPrice;
        if (price <= 1) return null;
        const logPrice = Math.log(price);
        if (logPrice <= 0) return null;

        let score: number;
        let ratingNorm100: number;
        let sourceCount: number;

        if (hasRatings) {
          const ratingInfo = ratingMap.get(w.wineKey);
          const rating = ratingInfo?.avg ?? 0;
          if (rating === 0) return null;
          ratingNorm100 = rating;
          sourceCount = Number(ratingInfo?.count ?? 0);
          score = (rating * rating) / logPrice;
        } else {
          // Price-confidence mode: score = sources × (1 - price_spread_pct)
          // Rewards wines confirmed by multiple retailers with tight price agreement
          const spread = pd.maxPrice > 0 ? (pd.maxPrice - pd.minPrice) / pd.maxPrice : 0;
          const priceSources = Number(pd.srcCount ?? 1);
          score = priceSources * (1 - spread) * 100;
          ratingNorm100 = 0;
          sourceCount = priceSources;
        }

        return {
          wineKey: w.wineKey,
          canonicalName: w.canonicalName,
          producerKey: w.producerKey,
          producerName: w.producerName,
          cuveeName: w.cuveeName,
          vintage: w.vintage,
          color: w.color,
          classification: w.classification,
          appellationName: w.appellationName,
          score,
          priceEur: price,
          minPriceEur: pd.minPrice,
          maxPriceEur: pd.maxPrice,
          ratingNorm100,
          confidence: deriveConfidence(sourceCount),
          sourceCount,
        } satisfies BestValueRow;
      })
      .filter((r): r is BestValueRow => r !== null)
      .filter((r) => !filters.drinkingIntent || matchesDrinkingIntent(r, filters.drinkingIntent))
      .sort((a, b) => b.score - a.score)
      .slice(0, 50);

    return { wines: scored, ratingMode: hasRatings };
  } catch {
    return { wines: [], ratingMode: false };
  }
}
