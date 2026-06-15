import { db } from "@/db";
import { wineSimilarity, dimWine, dimProducer, dimAppellation } from "@/db/schema";
import { eq, sql } from "drizzle-orm";

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

/**
 * Top-N similar wines (by precomputed cosine similarity) with aggregated
 * rating/price. Shared by GET /api/wines/[wineKey]/similar and the domaine
 * detail page (SSR).
 */
export async function getSimilarWines(wineKey: string, limit = 10): Promise<SimilarWineItem[]> {
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
    .limit(limit);

  return rows.map((r) => ({
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
}
