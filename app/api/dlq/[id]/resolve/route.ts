import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db/index";
import { opsDeadLetter } from "@/db/schema";
import { eq, sql } from "drizzle-orm";

const VALID_RESOLUTIONS = ["approved_manual", "blacklisted", "ignored"] as const;
type ManualResolution = (typeof VALID_RESOLUTIONS)[number];

function isValidResolution(value: unknown): value is ManualResolution {
  return VALID_RESOLUTIONS.includes(value as ManualResolution);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const dlqId = Number(id);

  if (!Number.isInteger(dlqId) || dlqId <= 0) {
    return NextResponse.json({ error: "Invalid id" }, { status: 400 });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const resolution = (body as Record<string, unknown>)?.resolution;
  if (!isValidResolution(resolution)) {
    return NextResponse.json(
      {
        error: `Invalid resolution. Must be one of: ${VALID_RESOLUTIONS.join(", ")}`,
      },
      { status: 400 }
    );
  }

  // Check existence first
  const existing = await db
    .select({ dlqId: opsDeadLetter.dlqId })
    .from(opsDeadLetter)
    .where(eq(opsDeadLetter.dlqId, dlqId))
    .get();

  if (!existing) {
    return NextResponse.json({ error: "DLQ record not found" }, { status: 404 });
  }

  await db
    .update(opsDeadLetter)
    .set({
      resolution,
      resolvedAt: sql`(unixepoch())`,
      resolvedBy: "manual",
    })
    .where(eq(opsDeadLetter.dlqId, dlqId));

  return NextResponse.json({ ok: true, dlqId, resolution });
}
