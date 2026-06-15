import { db } from "@/db";
import {
  dimWine,
  dimProducer,
  cellarInventory,
  factRating,
  opsBatchLog,
  opsDeadLetter,
  factPrice,
} from "@/db/schema";
import { sql, desc, eq } from "drizzle-orm";

export interface DashboardStats {
  bottles: number;
  uniqueWines: number;
  producers: number;
  ratings: number;
  cellarValue: number;
  lastIngest: Date | null;
  dlqOpen: number;
}

const EMPTY_STATS: DashboardStats = {
  bottles: 0,
  uniqueWines: 0,
  producers: 0,
  ratings: 0,
  cellarValue: 0,
  lastIngest: null,
  dlqOpen: 0,
};

/**
 * Dashboard headline counters: cellar size, catalogue breadth, ingest health.
 * Single source of truth shared by the dashboard page (SSR) and GET /api/stats.
 */
export async function getDashboardStats(): Promise<DashboardStats> {
  try {
    const [bottlesRow] = await db
      .select({ total: sql<number>`coalesce(sum(${cellarInventory.qty}), 0)` })
      .from(cellarInventory);
    const [uniqueRow] = await db
      .select({ total: sql<number>`count(distinct ${dimWine.wineKey})` })
      .from(dimWine);
    const [producersRow] = await db
      .select({ total: sql<number>`count(*)` })
      .from(dimProducer)
      .where(eq(dimProducer.status, "active"));
    const [ratingsRow] = await db
      .select({ total: sql<number>`count(*)` })
      .from(factRating);
    // Use COALESCE(market_avg_price, purchase_price) so wines imported without
    // a purchase price still contribute their market value to the total.
    const marketAvg = db
      .select({
        wineKey: factPrice.wineKey,
        amountEur: sql<number>`avg(${factPrice.amountEur})`.as("amount_eur"),
      })
      .from(factPrice)
      .where(sql`${factPrice.priceKind} = 'market_avg'`)
      .groupBy(factPrice.wineKey)
      .as("market_avg");

    const [valueRow] = await db
      .select({
        total: sql<number>`coalesce(sum(${cellarInventory.qty} * coalesce(${marketAvg.amountEur}, ${cellarInventory.purchasePriceEur})), 0)`,
      })
      .from(cellarInventory)
      .leftJoin(marketAvg, eq(marketAvg.wineKey, cellarInventory.wineKey));
    const [lastBatch] = await db
      .select()
      .from(opsBatchLog)
      .orderBy(desc(opsBatchLog.startedAt))
      .limit(1);
    const [dlqRow] = await db
      .select({ total: sql<number>`count(*)` })
      .from(opsDeadLetter)
      .where(eq(opsDeadLetter.resolution, "pending"));

    return {
      bottles: Number(bottlesRow?.total ?? 0),
      uniqueWines: Number(uniqueRow?.total ?? 0),
      producers: Number(producersRow?.total ?? 0),
      ratings: Number(ratingsRow?.total ?? 0),
      cellarValue: Number(valueRow?.total ?? 0),
      lastIngest: lastBatch?.finishedAt ?? null,
      dlqOpen: Number(dlqRow?.total ?? 0),
    };
  } catch {
    return { ...EMPTY_STATS };
  }
}
