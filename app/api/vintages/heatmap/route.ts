import { NextRequest, NextResponse } from "next/server";
import { getVintageHeatmap, getVintageDivergence } from "@/lib/queries/vintages";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const region = new URL(req.url).searchParams.get("region") ?? undefined;

  try {
    const [heatmap, divergence] = await Promise.all([
      getVintageHeatmap(),
      getVintageDivergence(region),
    ]);
    return NextResponse.json({ heatmap, divergence });
  } catch (err) {
    console.error("[vintages/heatmap] DB error", err);
    return NextResponse.json({ error: "database error" }, { status: 500 });
  }
}
