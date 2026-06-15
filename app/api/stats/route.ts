import { NextResponse } from "next/server";
import { getDashboardStats } from "@/lib/queries/stats";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const stats = await getDashboardStats();
  return NextResponse.json({ stats });
}
