import { NextResponse } from "next/server";
import { getCellar } from "@/lib/queries/cellar";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  const cellar = await getCellar();
  return NextResponse.json(cellar);
}
