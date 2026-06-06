import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { factRating, factPrice } from "@/db/schema";
import { eq, desc, sql } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ wineKey: string }> },
) {
  const { wineKey } = await params;

  const [ratings, prices] = await Promise.all([
    db
      .select({
        criticCode: factRating.criticCode,
        score: factRating.scoreNormalized100,
        scale: factRating.scale,
      })
      .from(factRating)
      .where(eq(factRating.wineKey, wineKey))
      .orderBy(desc(factRating.scoreNormalized100))
      .limit(10),
    db
      .select({
        amountEur: factPrice.amountEur,
        retailer: factPrice.retailer,
        priceKind: factPrice.priceKind,
        inStock: factPrice.inStock,
      })
      .from(factPrice)
      .where(eq(factPrice.wineKey, wineKey))
      .orderBy(desc(factPrice.recordedAt))
      .limit(10),
  ]);

  const validPrices = prices.filter((r) => r.amountEur !== null && r.amountEur > 0);
  const avgPrice =
    validPrices.length > 0
      ? validPrices.reduce((a, r) => a + (r.amountEur ?? 0), 0) / validPrices.length
      : null;

  return NextResponse.json({ ratings, prices, avgPrice });
}
