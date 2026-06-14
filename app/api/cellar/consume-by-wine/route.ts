import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { cellarInventory, cellarConsumption } from "@/db/schema";
import { eq, desc } from "drizzle-orm";
import { z } from "zod";

const PostBody = z.object({
  wineKey: z.string().min(1),
  qty: z.number().int().positive().default(1),
  occasion: z.string().optional(),
  tastingNote: z.string().optional(),
});

/**
 * Consume bottles by wine_key — picks the inventory row with the most bottles
 * (or first found if tied). Used by the wine pairing page where only wineKey
 * is available, not inventoryId.
 */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }
  const { wineKey, qty, occasion, tastingNote } = parsed.data;

  // Pick the row with the most bottles for this wine_key
  const rows = await db
    .select()
    .from(cellarInventory)
    .where(eq(cellarInventory.wineKey, wineKey))
    .orderBy(desc(cellarInventory.qty))
    .limit(1);

  if (rows.length === 0) {
    return NextResponse.json({ error: "not_in_cellar" }, { status: 404 });
  }
  const inv = rows[0];

  if (qty > inv.qty) {
    return NextResponse.json({ error: "qty_exceeds_stock", stock: inv.qty }, { status: 409 });
  }

  await db.insert(cellarConsumption).values({
    wineKey: inv.wineKey,
    locationId: inv.locationId,
    qty,
    personalScore: null,
    occasion: occasion ?? null,
    tastingNote: tastingNote ?? null,
  });

  const remaining = inv.qty - qty;
  if (remaining === 0) {
    await db.delete(cellarInventory).where(eq(cellarInventory.inventoryId, inv.inventoryId));
  } else {
    await db
      .update(cellarInventory)
      .set({ qty: remaining })
      .where(eq(cellarInventory.inventoryId, inv.inventoryId));
  }

  return NextResponse.json({ wineKey, remaining });
}
