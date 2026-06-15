import { NextRequest, NextResponse } from "next/server";
import { getDlqRows, isErrorClass } from "@/lib/queries/ops";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  const classParam = new URL(req.url).searchParams.get("class");
  const errorClass = classParam && isErrorClass(classParam) ? classParam : null;
  const rows = await getDlqRows(errorClass);
  return NextResponse.json({ rows });
}
