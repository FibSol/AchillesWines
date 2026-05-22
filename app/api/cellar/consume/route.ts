import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { cellarInventory, cellarConsumption } from "@/db/schema";
import { eq } from "drizzle-orm";
import { z } from "zod";

const PostBody = z.object({
  inventoryId: z.number().int().positive(),
  qty: z.number().int().positive().default(1),
  personalScore: z.number().int().min(0).max(100).optional(),
  occasion: z.string().optional(),
  tastingNote: z.string().optional(),
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
  const { inventoryId, qty, personalScore, occasion, tastingNote } = parsed.data;

  const rows = await db
    .select()
    .from(cellarInventory)
    .where(eq(cellarInventory.inventoryId, inventoryId))
    .limit(1);
  if (rows.length === 0) return NextResponse.json({ error: "not_found" }, { status: 404 });
  const inv = rows[0];

  if (qty > inv.qty) {
    return NextResponse.json({ error: "qty_exceeds_stock", stock: inv.qty }, { status: 409 });
  }

  await db.insert(cellarConsumption).values({
    wineKey: inv.wineKey,
    locationId: inv.locationId,
    qty,
    personalScore: personalScore ?? null,
    occasion: occasion ?? null,
    tastingNote: tastingNote ?? null,
  });

  const remaining = inv.qty - qty;
  if (remaining === 0) {
    await db.delete(cellarInventory).where(eq(cellarInventory.inventoryId, inventoryId));
  } else {
    await db
      .update(cellarInventory)
      .set({ qty: remaining })
      .where(eq(cellarInventory.inventoryId, inventoryId));
  }

  return NextResponse.json({ inventoryId, remaining });
}
