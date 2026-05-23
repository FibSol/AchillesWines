import { NextResponse } from "next/server";
import { db } from "@/db";
import { dimSource, opsScraperSchedule } from "@/db/schema";
import { asc, eq } from "drizzle-orm";
import { z } from "zod";

export const dynamic = "force-dynamic";

export async function GET() {
  const rows = await db
    .select({
      sourceKey: dimSource.sourceKey,
      sourceCode: dimSource.sourceCode,
      sourceName: dimSource.sourceName,
      sourceTier: dimSource.sourceTier,
      enabled: dimSource.enabled,
      cronExpr: opsScraperSchedule.cronExpr,
    })
    .from(dimSource)
    .leftJoin(
      opsScraperSchedule,
      eq(dimSource.sourceCode, opsScraperSchedule.sourceCode)
    )
    .orderBy(asc(dimSource.sourceTier), asc(dimSource.sourceCode));

  return NextResponse.json({ sources: rows });
}

const upsertSchema = z.object({
  sourceCode: z.string().min(1),
  cronExpr: z.string().nullable(),
});

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const parsed = upsertSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.issues[0].message }, { status: 422 });
  }

  const { sourceCode, cronExpr } = parsed.data;

  if (cronExpr !== null && cronExpr.trim() !== "") {
    const parts = cronExpr.trim().split(/\s+/);
    if (parts.length !== 5) {
      return NextResponse.json(
        { error: "Cron expression must have exactly 5 fields" },
        { status: 422 }
      );
    }
  }

  if (!cronExpr || cronExpr.trim() === "") {
    await db
      .delete(opsScraperSchedule)
      .where(eq(opsScraperSchedule.sourceCode, sourceCode));
  } else {
    await db
      .insert(opsScraperSchedule)
      .values({ sourceCode, cronExpr: cronExpr.trim(), updatedAt: new Date() })
      .onConflictDoUpdate({
        target: opsScraperSchedule.sourceCode,
        set: { cronExpr: cronExpr.trim(), updatedAt: new Date() },
      });
  }

  return NextResponse.json({ ok: true });
}
