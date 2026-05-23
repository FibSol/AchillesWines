import { NextResponse } from "next/server";
import { db } from "@/db/index";
import { stagingPriceCandidates, factPrice } from "@/db/schema";
import { eq, isNull, sql, and } from "drizzle-orm";

const TOLERANCE = 0.15; // ±15% of median

type StagingRow = typeof stagingPriceCandidates.$inferSelect;

export async function POST() {
  // Fetch all pending unreviewed candidates
  const candidates = await db
    .select()
    .from(stagingPriceCandidates)
    .where(
      and(
        eq(stagingPriceCandidates.needsReview, true),
        isNull(stagingPriceCandidates.promotedAt)
      )
    );

  // Group by wine_key
  const byWine = new Map<string, StagingRow[]>();
  for (const c of candidates) {
    const list = byWine.get(c.wineKey) ?? [];
    list.push(c);
    byWine.set(c.wineKey, list);
  }

  let promoted = 0;
  let pending = 0;
  const now = Math.floor(Date.now() / 1000);

  for (const [, items] of byWine) {
    if (items.length < 2) {
      pending += items.length;
      continue;
    }

    // Compute median price
    const sorted = [...items].sort((a, b) => (a.amountEur ?? 0) - (b.amountEur ?? 0));
    const median = sorted[Math.floor(sorted.length / 2)].amountEur ?? 0;
    if (median === 0) {
      pending += items.length;
      continue;
    }

    // Find concordant items (within ±TOLERANCE of median, from distinct sources)
    const concordant = items.filter(
      (c) => Math.abs((c.amountEur ?? 0) - median) / median <= TOLERANCE
    );

    // Require at least 2 concordant rows from distinct sources
    const distinctSources = new Set(concordant.map((c) => c.sourceKey)).size;
    if (concordant.length >= 2 && distinctSources >= 2) {
      for (const c of concordant) {
        const inserted = await db
          .insert(factPrice)
          .values({
            wineKey: c.wineKey,
            sourceKey: c.sourceKey!,
            retailer: c.retailer ?? c.sourceKey?.toString() ?? "unknown",
            recordedAt: c.recordedAt,
            priceKind: "retail_in_stock",
            currencyCode: c.currencyCode,
            amountLocal: c.amountLocal,
            amountEur: c.amountEur,
            sourceUrl: c.sourceUrl,
            contentHash: c.contentHash,
            batchId: c.batchId,
          })
          .returning({ priceEventKey: factPrice.priceEventKey });

        const priceEventKey = inserted[0]?.priceEventKey ?? null;
        await db
          .update(stagingPriceCandidates)
          .set({
            promotedToFactPriceKey: priceEventKey,
            promotedAt: new Date(now * 1000),
            needsReview: false,
          })
          .where(eq(stagingPriceCandidates.candidateId, c.candidateId));
      }
      promoted += concordant.length;
      pending += items.length - concordant.length;
    } else {
      pending += items.length;
    }
  }

  const totalFactPrice = await db
    .select({ count: sql<number>`count(*)` })
    .from(factPrice)
    .then((r) => r[0]?.count ?? 0);

  return NextResponse.json({ promoted, pending, totalFactPrice });
}

export async function GET() {
  const pending = await db
    .select({ count: sql<number>`count(*)` })
    .from(stagingPriceCandidates)
    .where(
      and(
        eq(stagingPriceCandidates.needsReview, true),
        isNull(stagingPriceCandidates.promotedAt)
      )
    )
    .then((r) => r[0]?.count ?? 0);

  // Wine keys with candidates from 2+ distinct sources
  const overlapRows = await db
    .select({ wineKey: stagingPriceCandidates.wineKey })
    .from(stagingPriceCandidates)
    .where(
      and(
        eq(stagingPriceCandidates.needsReview, true),
        isNull(stagingPriceCandidates.promotedAt)
      )
    )
    .groupBy(stagingPriceCandidates.wineKey)
    .having(sql`count(distinct ${stagingPriceCandidates.sourceKey}) >= 2`);

  const overlap = overlapRows.length;

  const totalFactPrice = await db
    .select({ count: sql<number>`count(*)` })
    .from(factPrice)
    .then((r) => r[0]?.count ?? 0);

  return NextResponse.json({ pending, overlap, totalFactPrice });
}
