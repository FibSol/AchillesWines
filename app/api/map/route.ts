import { NextRequest, NextResponse } from "next/server";
import { parseTiers, getMapData } from "@/lib/queries/map";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const tiers = new URL(req.url).searchParams.get("tiers") ?? undefined;
  const data = await getMapData(parseTiers(tiers));
  return NextResponse.json(data);
}
