import { NextResponse } from "next/server";
import { db } from "@/db";
import { dimSource } from "@/db/schema";
import { asc, eq } from "drizzle-orm";

export interface SourceRow {
  sourceKey: number;
  sourceCode: string;
  sourceName: string;
  sourceTier: string;
  countryCode: string | null;
  cadence: string;
  requiresAuth: boolean;
}

export async function GET() {
  const rows = await db
    .select({
      sourceKey: dimSource.sourceKey,
      sourceCode: dimSource.sourceCode,
      sourceName: dimSource.sourceName,
      sourceTier: dimSource.sourceTier,
      countryCode: dimSource.countryCode,
      cadence: dimSource.cadence,
      requiresAuth: dimSource.requiresAuth,
    })
    .from(dimSource)
    .where(eq(dimSource.enabled, true))
    .orderBy(asc(dimSource.sourceTier), asc(dimSource.sourceName));
  return NextResponse.json({ sources: rows });
}
