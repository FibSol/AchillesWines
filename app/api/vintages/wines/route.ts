import { NextRequest, NextResponse } from "next/server";
import { getVintageWines } from "@/lib/queries/vintages";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const { searchParams } = new URL(req.url);
  const region = searchParams.get("region") ?? "";
  const vintage = parseInt(searchParams.get("vintage") ?? "", 10);

  if (!region || isNaN(vintage)) {
    return NextResponse.json({ error: "region and vintage required" }, { status: 400 });
  }

  try {
    const result = await getVintageWines(region, vintage);
    return NextResponse.json(result);
  } catch {
    return NextResponse.json({ error: "database error" }, { status: 500 });
  }
}
