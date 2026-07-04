import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { tastingSessions, tastingSessionWines, dimWine, dimProducer } from "@/db/schema";
import { desc, eq, asc } from "drizzle-orm";
import { z } from "zod";
import { TASTING_MODES } from "@/lib/tasting/engine";

export const dynamic = "force-dynamic";

const PostBody = z.object({
  mode: z.enum(TASTING_MODES as [string, ...string[]]),
  wines: z
    .array(
      z.object({
        wineKey: z.string().min(1),
        position: z.number().int().min(1),
      }),
    )
    .min(1)
    .max(8),
});

/** Save the current flight as a tasting session. */
export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }
  const { mode, wines } = parsed.data;

  const [session] = await db
    .insert(tastingSessions)
    .values({ mode })
    .returning({ sessionId: tastingSessions.sessionId });

  await db.insert(tastingSessionWines).values(
    wines.map((w) => ({
      sessionId: session.sessionId,
      wineKey: w.wineKey,
      position: w.position,
    })),
  );

  return NextResponse.json({ sessionId: session.sessionId });
}

/** List saved tastings, newest first, with their wines in serving order. */
export async function GET() {
  const sessions = await db
    .select()
    .from(tastingSessions)
    .orderBy(desc(tastingSessions.createdAt), desc(tastingSessions.sessionId));

  const wineRows = await db
    .select({
      sessionId: tastingSessionWines.sessionId,
      wineKey: tastingSessionWines.wineKey,
      position: tastingSessionWines.position,
      personalScore: tastingSessionWines.personalScore,
      consumedAt: tastingSessionWines.consumedAt,
      producerName: dimProducer.producerName,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
    })
    .from(tastingSessionWines)
    .innerJoin(dimWine, eq(tastingSessionWines.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .orderBy(asc(tastingSessionWines.position));

  const bySession = new Map<number, typeof wineRows>();
  for (const w of wineRows) {
    if (!bySession.has(w.sessionId)) bySession.set(w.sessionId, []);
    bySession.get(w.sessionId)!.push(w);
  }

  return NextResponse.json({
    sessions: sessions.map((s) => ({
      sessionId: s.sessionId,
      mode: s.mode,
      createdAt: s.createdAt,
      wines: bySession.get(s.sessionId) ?? [],
    })),
  });
}
