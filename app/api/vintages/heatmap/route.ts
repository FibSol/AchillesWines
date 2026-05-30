import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { dimWine, dimAppellation, factRating, dimSource } from "@/db/schema";
import { eq, and, gte, lte, sql } from "drizzle-orm";

export interface HeatmapCell {
  year: number;
  critic: string;
  avg: number;
  count: number;
  divergence: number;
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const { searchParams } = new URL(req.url);
  const region = searchParams.get("region") ?? "";

  try {
    // Build the query joining fact_rating → dim_wine → dim_appellation
    // Group by (vintage_year, critic_code), filter year 1990–2024
    const rows = await db
      .select({
        year: dimWine.vintage,
        critic: factRating.criticCode,
        avg: sql<number>`round(avg(${factRating.scoreNormalized100}), 1)`,
        count: sql<number>`cast(count(*) as integer)`,
        // SQLite doesn't have STDEV — approximate with sqrt(avg(x^2) - avg(x)^2)
        divergence: sql<number>`round(
          sqrt(
            max(0,
              avg(${factRating.scoreNormalized100} * ${factRating.scoreNormalized100})
              - avg(${factRating.scoreNormalized100}) * avg(${factRating.scoreNormalized100})
            )
          ),
          1
        )`,
      })
      .from(factRating)
      .innerJoin(dimWine, eq(factRating.wineKey, dimWine.wineKey))
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .where(
        and(
          gte(dimWine.vintage, 1990),
          lte(dimWine.vintage, 2024),
          ...(region ? [eq(dimAppellation.region, region)] : [])
        )
      )
      .groupBy(dimWine.vintage, factRating.criticCode)
      .having(sql`count(*) >= 3`);

    // Filter out nulls (wines without a set vintage)
    const cells: HeatmapCell[] = rows
      .filter((r) => r.year !== null)
      .map((r) => ({
        year: r.year as number,
        critic: r.critic,
        avg: Number(r.avg),
        count: Number(r.count),
        divergence: Number(r.divergence),
      }));

    return NextResponse.json({ cells });
  } catch (err) {
    console.error("[vintages/heatmap] DB error", err);
    return NextResponse.json({ error: "database error" }, { status: 500 });
  }
}
