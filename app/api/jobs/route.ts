import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db/index";
import { opsJobQueue } from "@/db/schema";
import { eq, desc, and, type SQL } from "drizzle-orm";
import { z } from "zod";

const PostBody = z.object({
  sourceKey: z.number().int().positive(),
  params: z.record(z.string(), z.unknown()).optional(),
});

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
  return NextResponse.json({ jobId }, { status: 201 });
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const sourceKeyParam = searchParams.get("sourceKey");
  const limit = Math.min(parseInt(searchParams.get("limit") ?? "50", 10), 200);

  const conditions: SQL[] = [];
  if (status) conditions.push(eq(opsJobQueue.status, status as "queued" | "running" | "done" | "failed" | "cancelled"));
  if (sourceKeyParam) conditions.push(eq(opsJobQueue.sourceKey, parseInt(sourceKeyParam)));

  const rows = await db
    .select()
    .from(opsJobQueue)
    .where(conditions.length > 0 ? and(...conditions) : undefined)
    .orderBy(desc(opsJobQueue.requestedAt))
    .limit(limit);

  return NextResponse.json(rows);
}
