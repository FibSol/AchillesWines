import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { cellarInventory, cellarLocations } from "@/db/schema";
import { eq, and, ne } from "drizzle-orm";
import { z } from "zod";

const PatchBody = z
  .object({
    locationId: z.number().int().positive().optional(),
    qty: z.number().int().min(0).optional(),
    notes: z.string().nullable().optional(),
    purchasePriceEur: z.number().nonnegative().nullable().optional(),
    purchaseDate: z.string().nullable().optional(),
    purchaseSource: z.string().max(200).nullable().optional(),
  })
  .refine(
    (v) =>
      v.locationId !== undefined ||
      v.qty !== undefined ||
      v.notes !== undefined ||
      v.purchasePriceEur !== undefined ||
      v.purchaseDate !== undefined ||
      v.purchaseSource !== undefined,
    { message: "no fields to update" },
  );

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const inventoryId = Number.parseInt(id, 10);
  if (!Number.isFinite(inventoryId)) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  const body = await req.json().catch(() => null);
  const parsed = PatchBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }

  const existing = await db
    .select()
    .from(cellarInventory)
    .where(eq(cellarInventory.inventoryId, inventoryId))
    .limit(1);
  if (existing.length === 0) {
    return NextResponse.json({ error: "not_found" }, { status: 404 });
  }
  const row = existing[0];

  // Moving to a different location: check capacity, merge into existing row if any
  if (parsed.data.locationId !== undefined && parsed.data.locationId !== row.locationId) {
    const newLocId = parsed.data.locationId;
    const newLoc = await db
      .select()
      .from(cellarLocations)
      .where(eq(cellarLocations.locationId, newLocId))
      .limit(1);
    if (newLoc.length === 0) {
      return NextResponse.json({ error: "location_not_found" }, { status: 404 });
    }
    const others = await db
      .select({ qty: cellarInventory.qty })
      .from(cellarInventory)
      .where(
        and(eq(cellarInventory.locationId, newLocId), ne(cellarInventory.inventoryId, inventoryId)),
      );
    const used = others.reduce((a, r) => a + r.qty, 0);
    if (used + row.qty > newLoc[0].capacity) {
      return NextResponse.json(
        { error: "capacity_exceeded", used, capacity: newLoc[0].capacity },
        { status: 409 },
      );
    }

    // Merge with existing inventory row at destination if same wine
    const dup = await db
      .select()
      .from(cellarInventory)
      .where(
        and(
          eq(cellarInventory.wineKey, row.wineKey),
          eq(cellarInventory.locationId, newLocId),
        ),
      )
      .limit(1);

    if (dup.length > 0) {
      await db
        .update(cellarInventory)
        .set({ qty: dup[0].qty + row.qty })
        .where(eq(cellarInventory.inventoryId, dup[0].inventoryId));
      await db.delete(cellarInventory).where(eq(cellarInventory.inventoryId, inventoryId));
      return NextResponse.json({ inventoryId: dup[0].inventoryId, merged: true, qty: dup[0].qty + row.qty });
    }
    await db
      .update(cellarInventory)
      .set({ locationId: newLocId })
      .where(eq(cellarInventory.inventoryId, inventoryId));
  }

  if (parsed.data.qty !== undefined) {
    if (parsed.data.qty === 0) {
      await db.delete(cellarInventory).where(eq(cellarInventory.inventoryId, inventoryId));
      return NextResponse.json({ inventoryId, deleted: true });
    }
    await db
      .update(cellarInventory)
      .set({ qty: parsed.data.qty })
      .where(eq(cellarInventory.inventoryId, inventoryId));
  }
  const detailUpdates: Record<string, unknown> = {};
  if (parsed.data.notes !== undefined) detailUpdates.notes = parsed.data.notes;
  if (parsed.data.purchasePriceEur !== undefined) detailUpdates.purchasePriceEur = parsed.data.purchasePriceEur;
  if (parsed.data.purchaseSource !== undefined) detailUpdates.purchaseSource = parsed.data.purchaseSource;
  if (parsed.data.purchaseDate !== undefined) {
    detailUpdates.purchaseDate = parsed.data.purchaseDate
      ? new Date(parsed.data.purchaseDate)
      : null;
  }
  if (Object.keys(detailUpdates).length > 0) {
    await db
      .update(cellarInventory)
      .set(detailUpdates)
      .where(eq(cellarInventory.inventoryId, inventoryId));
  }

  return NextResponse.json({ inventoryId, ok: true });
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const inventoryId = Number.parseInt(id, 10);
  if (!Number.isFinite(inventoryId)) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }
  await db.delete(cellarInventory).where(eq(cellarInventory.inventoryId, inventoryId));
  return NextResponse.json({ ok: true });
}
