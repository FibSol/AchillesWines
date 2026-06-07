import { NextResponse } from "next/server";
import { db } from "@/db/index";
import { opsDeadLetter } from "@/db/schema";
import { eq, count, sql } from "drizzle-orm";

export async function GET() {
  const [totalRow, pendingRow, byClass, byResolution] = await Promise.all([
    // total count
    db
      .select({ total: count() })
      .from(opsDeadLetter)
      .get(),

    // pending count
    db
      .select({ pending: count() })
      .from(opsDeadLetter)
      .where(eq(opsDeadLetter.resolution, "pending"))
      .get(),

    // breakdown by error_class (pending + total)
    db
      .select({
        errorClass: opsDeadLetter.errorClass,
        pending: sql<number>`SUM(CASE WHEN ${opsDeadLetter.resolution} = 'pending' THEN 1 ELSE 0 END)`,
        total: count(),
      })
      .from(opsDeadLetter)
      .groupBy(opsDeadLetter.errorClass)
      .orderBy(sql`total DESC`),

    // breakdown by resolution
    db
      .select({
        resolution: opsDeadLetter.resolution,
        count: count(),
      })
      .from(opsDeadLetter)
      .groupBy(opsDeadLetter.resolution)
      .orderBy(sql`count DESC`),
  ]);

  return NextResponse.json({
    total: totalRow?.total ?? 0,
    pending: pendingRow?.pending ?? 0,
    byClass: byClass.map((r) => ({
      errorClass: r.errorClass,
      pending: Number(r.pending),
      total: r.total,
    })),
    byResolution: byResolution.map((r) => ({
      resolution: r.resolution,
      count: r.count,
    })),
  });
}
