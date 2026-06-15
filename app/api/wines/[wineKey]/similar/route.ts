import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { dimWine } from "@/db/schema";
import { eq } from "drizzle-orm";
import { getSimilarWines } from "@/lib/queries/similar";

// Re-exported so existing importers of this path keep working.
export type { SimilarWineItem } from "@/lib/queries/similar";

export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ wineKey: string }> },
): Promise<NextResponse> {
  const { wineKey } = await params;

  // Verify the wine exists
  const wineExists = await db
    .select({ wineKey: dimWine.wineKey })
    .from(dimWine)
    .where(eq(dimWine.wineKey, wineKey))
    .limit(1);

  if (wineExists.length === 0) {
    return NextResponse.json({ error: "Wine not found" }, { status: 404 });
  }

  const items = await getSimilarWines(wineKey, 10);
  return NextResponse.json(items);
}
