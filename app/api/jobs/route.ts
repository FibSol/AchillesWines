import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db/index";
import { opsJobQueue } from "@/db/schema";
import { eq, desc, and, type SQL } from "drizzle-orm";
import { z } from "zod";
import { audit } from "@/lib/audit";

// Constrain params to scalar values only (no nested objects/arrays) — the job
// runner reads scalar keys like `limit`/`test_auth`. Prevents arbitrary nested
// JSON payloads from being persisted/enqueued.
const PostBody = z.object({
  sourceKey: z.number().int().positive(),
  params: z
    .record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()]))
    .optional(),
});

const VALID_STATUSES = ["queued", "running", "done", "failed", "cancelled"] as const;
type JobStatus = (typeof VALID_STATUSES)[number];

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: parsed.error.issues.map((i) => i.message).join(", ") }, { status: 400 });
  }
  const jobId = crypto.randomUUID();
  await db.insert(opsJobQueue).values({
    jobId,
    sourceKey: parsed.data.sourceKey,
    requestedBy: "ui",
    params: parsed.data.params ?? null,
  });
  await audit("job.create", { jobId, sourceKey: parsed.data.sourceKey }, req);
  return NextResponse.json({ jobId }, { status: 201 });
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const sourceKeyParam = searchParams.get("sourceKey");
  const limit = Math.min(parseInt(searchParams.get("limit") ?? "50", 10), 200);

  const conditions: SQL[] = [];
  if (status && (VALID_STATUSES as readonly string[]).includes(status)) {
    conditions.push(eq(opsJobQueue.status, status as JobStatus));
  }
  if (sourceKeyParam && Number.isInteger(Number(sourceKeyParam))) {
    conditions.push(eq(opsJobQueue.sourceKey, parseInt(sourceKeyParam, 10)));
  }

  const rows = await db
    .select()
    .from(opsJobQueue)
    .where(conditions.length > 0 ? and(...conditions) : undefined)
    .orderBy(desc(opsJobQueue.requestedAt))
    .limit(limit);

  return NextResponse.json(rows);
}
