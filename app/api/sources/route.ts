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
  recommendedBatchSize: number | null;
  lastBenchmarkAt: number | null;
  benchmarkSuccessRate: number | null;
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
      recommendedBatchSize: dimSource.recommendedBatchSize,
      lastBenchmarkAt: dimSource.lastBenchmarkAt,
      benchmarkSuccessRate: dimSource.benchmarkSuccessRate,
    })
    .from(dimSource)
    .where(eq(dimSource.enabled, true))
    .orderBy(asc(dimSource.sourceTier), asc(dimSource.sourceName));
  return NextResponse.json({ sources: rows });
}
