import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { dimWine, dimProducer, dimAppellation, factPrice, factRating } from "@/db/schema";
import { eq, and, inArray, sql } from "drizzle-orm";

interface WineEntry {
  wineKey: string;
  canonicalName: string;
  producerName: string;
  cuveeName: string;
  sourceCount: number;
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const { searchParams } = new URL(req.url);
  const region = searchParams.get("region") ?? "";
  const vintageStr = searchParams.get("vintage") ?? "";
  const vintage = parseInt(vintageStr, 10);

  if (!region || isNaN(vintage)) {
    return NextResponse.json({ error: "region and vintage required" }, { status: 400 });
  }

  try {
    const wines = await db
      .select({
        wineKey: dimWine.wineKey,
        canonicalName: dimWine.canonicalName,
        producerName: dimProducer.producerName,
        cuveeName: dimWine.cuveeName,
      })
      .from(dimWine)
      .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .where(and(eq(dimAppellation.region, region), eq(dimWine.vintage, vintage)))
      .limit(60);

    if (wines.length === 0) {
      return NextResponse.json({ wines: [] });
    }
    const wineKeys = wines.map((w) => w.wineKey);

    // Distinct source_key counts across fact_price + fact_rating, per wine
    const [priceSources, ratingSources] = await Promise.all([
      db
        .select({
          wineKey: factPrice.wineKey,
          sourceKey: factPrice.sourceKey,
        })
        .from(factPrice)
        .where(inArray(factPrice.wineKey, wineKeys))
        .groupBy(factPrice.wineKey, factPrice.sourceKey),
      db
        .select({
          wineKey: factRating.wineKey,
          sourceKey: factRating.sourceKey,
        })
        .from(factRating)
        .where(inArray(factRating.wineKey, wineKeys))
        .groupBy(factRating.wineKey, factRating.sourceKey),
    ]);

    const sourcesByWine = new Map<string, Set<number>>();
    for (const r of [...priceSources, ...ratingSources]) {
      if (!sourcesByWine.has(r.wineKey)) sourcesByWine.set(r.wineKey, new Set());
      sourcesByWine.get(r.wineKey)!.add(r.sourceKey);
    }

    const result: WineEntry[] = wines.map((w) => ({
      ...w,
      sourceCount: sourcesByWine.get(w.wineKey)?.size ?? 0,
    }));

    return NextResponse.json({ wines: result });
  } catch {
    return NextResponse.json({ error: "database error" }, { status: 500 });
  }
}
