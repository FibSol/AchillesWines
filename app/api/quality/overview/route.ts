import { NextResponse } from "next/server";
import { getQualityOverview } from "@/lib/queries/ops";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const overview = await getQualityOverview();
  return NextResponse.json(overview);
}
