import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { dimSource, opsScraperSchedule } from "@/db/schema";
import { asc, eq, sql } from "drizzle-orm";

export interface ScheduleRow {
  sourceCode: string;
  sourceName: string;
  sourceTier: string;
  cronExpr: string | null;
}

/** GET /api/schedules — all enabled sources with their cron schedule (if any). */
export async function GET() {
  const rows = await db
    .select({
      sourceCode: dimSource.sourceCode,
      sourceName: dimSource.sourceName,
      sourceTier: dimSource.sourceTier,
      cronExpr: opsScraperSchedule.cronExpr,
    })
    .from(dimSource)
    .leftJoin(
      opsScraperSchedule,
      eq(dimSource.sourceCode, opsScraperSchedule.sourceCode),
    )
    .where(eq(dimSource.enabled, true))
    .orderBy(asc(dimSource.sourceTier), asc(dimSource.sourceCode));

  return NextResponse.json({ sources: rows });
}

/** PATCH /api/schedules — upsert or clear a cron schedule for one source. */
export async function PATCH(req: NextRequest) {
  const body = await req.json().catch(() => null);

  if (
    !body ||
    typeof body.sourceCode !== "string" ||
    (body.cronExpr !== null && typeof body.cronExpr !== "string")
  ) {
    return NextResponse.json(
      { error: "body must be { sourceCode: string, cronExpr: string | null }" },
      { status: 400 },
    );
  }

  const { sourceCode, cronExpr } = body as { sourceCode: string; cronExpr: string | null };

  // Validate cron expression if provided
  if (cronExpr !== null) {
    const parts = cronExpr.trim().split(/\s+/);
    if (parts.length !== 5 || !parts.every((p) => /^[\d*/,\-]+$/.test(p))) {
      return NextResponse.json(
        { error: "Invalid cron expression — expected 5 space-separated fields" },
        { status: 400 },
      );
    }
  }

  await db
    .insert(opsScraperSchedule)
    .values({
      sourceCode,
      cronExpr: cronExpr ?? null,
      updatedAt: new Date(),
    })
    .onConflictDoUpdate({
      target: opsScraperSchedule.sourceCode,
      set: {
        cronExpr: cronExpr ?? null,
        updatedAt: sql`(unixepoch())`,
      },
    });

  return NextResponse.json({ ok: true, sourceCode, cronExpr });
}
