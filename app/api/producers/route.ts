import { NextRequest, NextResponse } from "next/server";
import { getProducers } from "@/lib/queries/producers";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const sp = new URL(req.url).searchParams;
  const tierRaw = sp.get("tier");
  const result = await getProducers({
    q: sp.get("q") || undefined,
    country: sp.get("country") || undefined,
    region: sp.get("region") || undefined,
    tier: tierRaw ? Number.parseInt(tierRaw, 10) : undefined,
  });
  return NextResponse.json(result);
}
