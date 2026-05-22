import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { dimWine, dimProducer, dimAppellation } from "@/db/schema";
import { eq, like, or, asc } from "drizzle-orm";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const q = (searchParams.get("q") ?? "").trim().toLowerCase();
  const limit = Math.min(Number.parseInt(searchParams.get("limit") ?? "20", 10) || 20, 100);

  const baseSelect = db
    .select({
      wineKey: dimWine.wineKey,
      canonicalName: dimWine.canonicalName,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      producerName: dimProducer.producerName,
      appellationName: dimAppellation.appellationName,
    })
    .from(dimWine)
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey));

  const rows = q
    ? await baseSelect
        .where(
          or(
            like(dimWine.canonicalName, `%${q}%`),
            like(dimWine.cuveeName, `%${q}%`),
            like(dimProducer.producerName, `%${q}%`),
          ),
        )
        .orderBy(asc(dimProducer.producerName), asc(dimWine.cuveeName))
        .limit(limit)
    : await baseSelect
        .orderBy(asc(dimProducer.producerName), asc(dimWine.cuveeName))
        .limit(limit);

  return NextResponse.json({ wines: rows });
}
