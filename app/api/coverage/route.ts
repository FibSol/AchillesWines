import { NextResponse } from "next/server";
import { getCoverageData } from "@/lib/queries/ops";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const coverage = await getCoverageData();
  return NextResponse.json(coverage);
}
