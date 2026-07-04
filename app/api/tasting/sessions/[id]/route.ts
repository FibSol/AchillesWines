import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { tastingSessions, tastingSessionWines, cellarConsumption } from "@/db/schema";
import { and, eq } from "drizzle-orm";
import { z } from "zod";

const PatchBody = z.object({
  wines: z
    .array(
      z.object({
        wineKey: z.string().min(1),
        personalScore: z.number().int().min(0).max(100).nullable(),
      }),
    )
    .min(1),
});

/** Save ratings for wines of a session. Syncs the drink log if already consumed. */
export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const sessionId = Number.parseInt(id, 10);
  if (!Number.isFinite(sessionId)) {
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

  for (const w of parsed.data.wines) {
    const [row] = await db
      .update(tastingSessionWines)
      .set({ personalScore: w.personalScore })
      .where(
        and(
          eq(tastingSessionWines.sessionId, sessionId),
          eq(tastingSessionWines.wineKey, w.wineKey),
        ),
      )
      .returning({ consumptionId: tastingSessionWines.consumptionId });

    // Rating set after the bottle was removed → keep the drink log in sync.
    if (row?.consumptionId != null) {
      await db
        .update(cellarConsumption)
        .set({ personalScore: w.personalScore })
        .where(eq(cellarConsumption.consumptionId, row.consumptionId));
    }
  }

  return NextResponse.json({ ok: true });
}

/** Delete a saved tasting (the drink log is untouched). */
export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const sessionId = Number.parseInt(id, 10);
  if (!Number.isFinite(sessionId)) {
    return NextResponse.json({ error: "invalid_id" }, { status: 400 });
  }

  await db.delete(tastingSessionWines).where(eq(tastingSessionWines.sessionId, sessionId));
  await db.delete(tastingSessions).where(eq(tastingSessions.sessionId, sessionId));

  return NextResponse.json({ ok: true });
}
