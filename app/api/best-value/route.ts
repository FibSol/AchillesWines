import { NextRequest, NextResponse } from "next/server";
import { getBestValueWines, type FilterParams, type DrinkingIntent } from "@/lib/queries/best-value";

export const dynamic = "force-dynamic";

function num(v: string | null): number | undefined {
  if (v === null || v === "") return undefined;
  const n = Number(v);
  return Number.isNaN(n) ? undefined : n;
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const sp = new URL(req.url).searchParams;
  const intentRaw = sp.get("drinkingIntent") ?? "";
  const drinkingIntent = (["drink_now", "cellar_10", "invest"].includes(intentRaw)
    ? intentRaw
    : undefined) as DrinkingIntent | undefined;

  const filters: FilterParams = {
    country: sp.get("country") || undefined,
    region: sp.get("region") || undefined,
    vintage: num(sp.get("vintage")),
    color: sp.get("color") || undefined,
    minPrice: num(sp.get("minPrice")),
    maxPrice: num(sp.get("maxPrice")),
    minRating: num(sp.get("minRating")),
    maxRating: num(sp.get("maxRating")),
    drinkingIntent,
  };

  const { wines, ratingMode } = await getBestValueWines(filters);
  return NextResponse.json({ wines, ratingMode });
}
