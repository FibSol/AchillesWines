import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db/index";
import { opsJobQueue } from "@/db/schema";
import { eq, and } from "drizzle-orm";

export async function POST(
  _req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> }
) {
  const { jobId } = await params;
  const result = await db
    .update(opsJobQueue)
    .set({ status: "cancelled" })
    .where(and(eq(opsJobQueue.jobId, jobId), eq(opsJobQueue.status, "queued")));

  const changes = (result as any).changes ?? (result as any).rowsAffected ?? 0;
  if (changes === 0) {
    return NextResponse.json({ error: "Job not found or not in queued status" }, { status: 409 });
  }
  return NextResponse.json({ ok: true });
}
