import { NextRequest, NextResponse } from "next/server";
import { getBestValueFilterOptions } from "@/lib/queries/best-value";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const sp = new URL(req.url).searchParams;
  const locale = sp.get("locale") || "fr";
  const country = sp.get("country") || undefined;
  const options = await getBestValueFilterOptions(locale, country);
  return NextResponse.json(options);
}
