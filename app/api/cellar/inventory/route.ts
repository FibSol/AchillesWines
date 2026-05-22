import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { cellarInventory, cellarLocations, dimWine } from "@/db/schema";
import { eq, and } from "drizzle-orm";
import { z } from "zod";

const PostBody = z.object({
  wineKey: z.string().min(1),
  locationId: z.number().int().positive(),
  qty: z.number().int().positive(),
  purchasePriceEur: z.number().positive().optional(),
  purchaseSource: z.string().optional(),
  notes: z.string().optional(),
});

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }
  const { wineKey, locationId, qty, purchasePriceEur, purchaseSource, notes } = parsed.data;

  const wine = await db.select({ wineKey: dimWine.wineKey }).from(dimWine).where(eq(dimWine.wineKey, wineKey)).limit(1);
  if (wine.length === 0) return NextResponse.json({ error: "wine_not_found" }, { status: 404 });
  const loc = await db.select({ locationId: cellarLocations.locationId, capacity: cellarLocations.capacity }).from(cellarLocations).where(eq(cellarLocations.locationId, locationId)).limit(1);
  if (loc.length === 0) return NextResponse.json({ error: "location_not_found" }, { status: 404 });

  // Capacity check
  const allAtLoc = await db
    .select({ qty: cellarInventory.qty })
    .from(cellarInventory)
    .where(eq(cellarInventory.locationId, locationId));
  const used = allAtLoc.reduce((a, r) => a + r.qty, 0);
  if (used + qty > loc[0].capacity) {
    return NextResponse.json({ error: "capacity_exceeded", used, capacity: loc[0].capacity }, { status: 409 });
  }

  // Upsert by (wineKey, locationId)
  const existing = await db
    .select()
    .from(cellarInventory)
    .where(and(eq(cellarInventory.wineKey, wineKey), eq(cellarInventory.locationId, locationId)))
    .limit(1);

  if (existing.length > 0) {
    await db
      .update(cellarInventory)
      .set({ qty: existing[0].qty + qty })
      .where(eq(cellarInventory.inventoryId, existing[0].inventoryId));
    return NextResponse.json({ inventoryId: existing[0].inventoryId, qty: existing[0].qty + qty });
  }

  const [{ inventoryId }] = await db
    .insert(cellarInventory)
    .values({
      wineKey,
      locationId,
      qty,
      purchasePriceEur: purchasePriceEur ?? null,
      purchaseSource: purchaseSource ?? null,
      notes: notes ?? null,
    })
    .returning({ inventoryId: cellarInventory.inventoryId });

  return NextResponse.json({ inventoryId, qty }, { status: 201 });
}
