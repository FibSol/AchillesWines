import { NextRequest, NextResponse } from "next/server";
import { getProducerDetail } from "@/lib/queries/producer-detail";

export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await params;
  const producerKey = Number.parseInt(id, 10);
  if (!Number.isFinite(producerKey)) {
    return NextResponse.json({ error: "invalid_producer_id" }, { status: 400 });
  }

  const detail = await getProducerDetail(producerKey);
  if (!detail) {
    return NextResponse.json({ error: "producer_not_found" }, { status: 404 });
  }

  return NextResponse.json(detail);
}
