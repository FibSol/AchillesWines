import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { wineSimilarity, dimWine, dimProducer, dimAppellation, factPrice, factRating } from "@/db/schema";
import { eq, sql } from "drizzle-orm";

export const dynamic = "force-dynamic";

export interface SimilarWineItem {
  wine_key: string;
  producer_name: string;
  cuvee_name: string;
  vintage: number | null;
  appellation_name: string;
  color: string;
  avg_score: number | null;
  min_price: number | null;
  similarity_score: number;
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ wineKey: string }> },
): Promise<NextResponse> {
  const { wineKey } = await params;

  // Verify the wine exists
  const wineExists = await db
    .select({ wineKey: dimWine.wineKey })
    .from(dimWine)
    .where(eq(dimWine.wineKey, wineKey))
    .limit(1);

  if (wineExists.length === 0) {
    return NextResponse.json({ error: "Wine not found" }, { status: 404 });
  }

  // Fetch top-10 similar wines with aggregated price/rating data
  const rows = await db
    .select({
      wine_key: wineSimilarity.similarWineKey,
      similarity_score: wineSimilarity.score,
      producer_name: dimProducer.producerName,
      cuvee_name: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      appellation_name: dimAppellation.appellationName,
      avg_score: sql<number | null>`(
        SELECT ROUND(AVG(fr.score_normalized_100), 1)
        FROM fact_rating fr
        WHERE fr.wine_key = ${wineSimilarity.similarWineKey}
      )`,
      min_price: sql<number | null>`(
        SELECT MIN(fp.amount_eur)
        FROM fact_price fp
        WHERE fp.wine_key = ${wineSimilarity.similarWineKey}
          AND fp.amount_eur > 0
      )`,
    })
    .from(wineSimilarity)
    .innerJoin(dimWine, eq(dimWine.wineKey, wineSimilarity.similarWineKey))
    .innerJoin(dimProducer, eq(dimProducer.producerKey, dimWine.producerKey))
    .innerJoin(dimAppellation, eq(dimAppellation.appellationKey, dimWine.appellationKey))
    .where(eq(wineSimilarity.wineKey, wineKey))
    .orderBy(sql`${wineSimilarity.score} DESC`)
    .limit(10);

  const items: SimilarWineItem[] = rows.map((r) => ({
    wine_key: r.wine_key,
    producer_name: r.producer_name,
    cuvee_name: r.cuvee_name,
    vintage: r.vintage,
    appellation_name: r.appellation_name,
    color: r.color,
    avg_score: r.avg_score,
    min_price: r.min_price,
    similarity_score: r.similarity_score,
  }));

  return NextResponse.json(items);
}
