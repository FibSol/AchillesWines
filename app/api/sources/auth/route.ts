import { NextResponse } from "next/server";
import { getAuthSources } from "@/lib/queries/ops";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const rows = await getAuthSources();
  return NextResponse.json({ rows });
}
