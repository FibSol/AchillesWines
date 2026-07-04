import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { tastingSessionWines, cellarInventory, cellarConsumption } from "@/db/schema";
import { and, desc, eq, isNull } from "drizzle-orm";

/**
 * One-click removal: consume 1 bottle of every not-yet-consumed wine of the
 * session. Each removal logs a cellar_consumption row carrying the wine's
 * personal score; the row id is kept on the session wine so a rating set
 * later still reaches the drink log. Wines with no stock left are marked
 * consumed without a log row (the bottle is already gone).
 */
export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const sessionId = Number.parseInt(id, 10);
  if (!Number.isFinite(sessionId)) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const pending = await db
    .select()
    .from(tastingSessionWines)
    .where(
      and(
        eq(tastingSessionWines.sessionId, sessionId),
        isNull(tastingSessionWines.consumedAt),
      ),
    );

  let consumed = 0;
  let missing = 0;
  const now = new Date();

  for (const wine of pending) {
    // Pick the inventory row with the most bottles (same rule as consume-by-wine).
    const [inv] = await db
      .select()
      .from(cellarInventory)
      .where(eq(cellarInventory.wineKey, wine.wineKey))
      .orderBy(desc(cellarInventory.qty))
      .limit(1);

    let consumptionId: number | null = null;
    if (inv) {
      const [row] = await db
        .insert(cellarConsumption)
        .values({
          wineKey: wine.wineKey,
          locationId: inv.locationId,
          qty: 1,
          personalScore: wine.personalScore,
          occasion: "tasting",
          tastingNote: null,
        })
        .returning({ consumptionId: cellarConsumption.consumptionId });
      consumptionId = row.consumptionId;

      if (inv.qty <= 1) {
        await db.delete(cellarInventory).where(eq(cellarInventory.inventoryId, inv.inventoryId));
      } else {
        await db
          .update(cellarInventory)
          .set({ qty: inv.qty - 1 })
          .where(eq(cellarInventory.inventoryId, inv.inventoryId));
      }
      consumed++;
    } else {
      missing++;
    }

    await db
      .update(tastingSessionWines)
      .set({ consumedAt: now, consumptionId })
      .where(eq(tastingSessionWines.sessionWineId, wine.sessionWineId));
  }

  return NextResponse.json({ consumed, missing });
}
