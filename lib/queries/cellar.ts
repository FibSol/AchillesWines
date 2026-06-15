import { db } from "@/db";
import {
  cellarLocations,
  cellarInventory,
  dimWine,
  dimProducer,
  dimAppellation,
  dimVariety,
  bridgeWineVariety,
  factRating,
  factPrice,
} from "@/db/schema";
import { eq, sql, inArray } from "drizzle-orm";
import type { CellarBottleRow } from "@/components/CellarBoard";

export interface CellarKpis {
  totalBottles: number;
  totalCapacity: number;
  uniqueWines: number;
  cellarValue: number;
  locationsInUse: number;
  avgCriticRating: number | null;
}

export interface CellarData {
  locations: (typeof cellarLocations.$inferSelect)[];
  bottles: CellarBottleRow[];
  kpis: CellarKpis;
}

/**
 * Full cellar board: storage locations, enriched bottle rows (grape, avg
 * rating, avg market price), and headline KPIs. Shared by the cellar page
 * (SSR) and GET /api/cellar.
 */
export async function getCellar(): Promise<CellarData> {
  const locations = await db.select().from(cellarLocations).orderBy(cellarLocations.locationId);

  const inventoryRows = await db
    .select({
      inventoryId: cellarInventory.inventoryId,
      wineKey: cellarInventory.wineKey,
      locationId: cellarInventory.locationId,
      qty: cellarInventory.qty,
      purchasePriceEur: cellarInventory.purchasePriceEur,
      purchaseDate: cellarInventory.purchaseDate,
      purchaseSource: cellarInventory.purchaseSource,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      alcoholPct: dimWine.alcoholPct,
      producerName: dimProducer.producerName,
      appellationName: dimAppellation.appellationName,
      region: dimAppellation.region,
    })
    .from(cellarInventory)
    .innerJoin(dimWine, eq(cellarInventory.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey));

  // Per-wine enrichment for the hover ID card: dominant grape, avg critic
  // rating, avg market price. One grouped query each, keyed by wine_key.
  const wineKeys = [...new Set(inventoryRows.map((r) => r.wineKey))];
  const ratingByWine = new Map<string, number>();
  const priceByWine = new Map<string, number>();
  const grapeByWine = new Map<string, { name: string; share: number }>();
  if (wineKeys.length > 0) {
    const [ratingRows, priceRows, varietyRows] = await Promise.all([
      db
        .select({ wineKey: factRating.wineKey, avg: sql<number>`avg(${factRating.scoreNormalized100})` })
        .from(factRating)
        .where(inArray(factRating.wineKey, wineKeys))
        .groupBy(factRating.wineKey),
      db
        .select({ wineKey: factPrice.wineKey, avg: sql<number>`avg(${factPrice.amountEur})` })
        .from(factPrice)
        .where(inArray(factPrice.wineKey, wineKeys))
        .groupBy(factPrice.wineKey),
      db
        .select({ wineKey: bridgeWineVariety.wineKey, name: dimVariety.varietyName, share: bridgeWineVariety.sharePct })
        .from(bridgeWineVariety)
        .innerJoin(dimVariety, eq(bridgeWineVariety.varietyKey, dimVariety.varietyKey))
        .where(inArray(bridgeWineVariety.wineKey, wineKeys)),
    ]);
    for (const r of ratingRows) if (r.avg !== null) ratingByWine.set(r.wineKey, Number(r.avg));
    for (const r of priceRows) if (r.avg !== null && r.avg > 0) priceByWine.set(r.wineKey, Number(r.avg));
    for (const v of varietyRows) {
      const s = v.share ?? 0;
      const cur = grapeByWine.get(v.wineKey);
      if (!cur || s > cur.share) grapeByWine.set(v.wineKey, { name: v.name, share: s });
    }
  }

  const bottles: CellarBottleRow[] = inventoryRows.map((r) => ({
    inventoryId: r.inventoryId,
    wineKey: r.wineKey,
    locationId: r.locationId,
    qty: r.qty,
    purchasePriceEur: r.purchasePriceEur ?? null,
    purchaseDate: r.purchaseDate ?? null,
    purchaseSource: r.purchaseSource ?? null,
    cuveeName: r.cuveeName,
    producerName: r.producerName,
    vintage: r.vintage,
    color: r.color,
    appellationName: r.appellationName,
    region: r.region,
    primaryVariety: grapeByWine.get(r.wineKey)?.name ?? null,
    alcoholPct: r.alcoholPct ?? null,
    avgRating: ratingByWine.get(r.wineKey) ?? null,
    avgPriceEur: priceByWine.get(r.wineKey) ?? null,
  }));

  const totalBottles = bottles.reduce((a, b) => a + b.qty, 0);
  const totalCapacity = locations.reduce((a, l) => a + l.capacity, 0);
  const uniqueWines = new Set(bottles.map((b) => b.wineKey)).size;
  // Use COALESCE(market price, purchase price) so wines without a purchase
  // price still contribute their market value to the cellar total.
  const cellarValue = inventoryRows.reduce(
    (a, r) => a + (r.qty * (priceByWine.get(r.wineKey) ?? r.purchasePriceEur ?? 0)),
    0,
  );
  const locationsInUse = new Set(bottles.map((b) => b.locationId)).size;

  // KPI: average critic rating across wines in cellar (mean of per-wine averages)
  const avgCriticRating =
    ratingByWine.size > 0
      ? [...ratingByWine.values()].reduce((a, b) => a + b, 0) / ratingByWine.size
      : null;

  return {
    locations,
    bottles,
    kpis: { totalBottles, totalCapacity, uniqueWines, cellarValue, locationsInUse, avgCriticRating },
  };
}
