import { db } from "@/db";
import {
  dimWine,
  dimProducer,
  dimSource,
  opsDeadLetter,
  opsBatchLog,
  factPrice,
  factRating,
  stagingPriceCandidates,
} from "@/db/schema";
import { sql, eq, desc, and, asc, count, countDistinct } from "drizzle-orm";
import type { AuthSourceRow } from "@/components/AuthSourceList";

/* ─── Quality overview ─────────────────────────────────────────────────────── */

export interface QualityOverview {
  totalWines: number;
  pricesTotal: number;
  ratingsTotal: number;
  pendingDlq: number;
  stagingPending: number;
  promotableCount: number;
  recentBatches: (typeof opsBatchLog.$inferSelect)[];
}

/**
 * Data-quality dashboard counters + the promote funnel + recent scraper
 * batches. Shared by the qualité page (SSR) and GET /api/quality/overview.
 */
export async function getQualityOverview(): Promise<QualityOverview> {
  const [totalWines] = await db.select({ n: sql<number>`count(*)` }).from(dimWine);
  const [pendingDlq] = await db
    .select({ n: sql<number>`count(*)` })
    .from(opsDeadLetter)
    .where(eq(opsDeadLetter.resolution, "pending"));
  const [pricesTotal] = await db.select({ n: sql<number>`count(*)` }).from(factPrice);
  const [ratingsTotal] = await db.select({ n: sql<number>`count(*)` }).from(factRating);

  const [stagingPending] = await db
    .select({ n: sql<number>`count(*)` })
    .from(stagingPriceCandidates)
    .where(eq(stagingPriceCandidates.needsReview, true));

  // Truly promotable: ≥2 distinct sources AND price spread within ±15% tolerance
  // MAX/MIN ≤ 1.35 approximates "both prices within ±15% of the median"
  const promotableRows = await db
    .select({ wineKey: stagingPriceCandidates.wineKey })
    .from(stagingPriceCandidates)
    .where(eq(stagingPriceCandidates.needsReview, true))
    .groupBy(stagingPriceCandidates.wineKey)
    .having(
      sql`count(distinct ${stagingPriceCandidates.sourceKey}) >= 2
        AND min(${stagingPriceCandidates.amountEur}) > 0
        AND max(${stagingPriceCandidates.amountEur}) / min(${stagingPriceCandidates.amountEur}) <= 1.35`
    );

  const recentBatches = await db
    .select()
    .from(opsBatchLog)
    .orderBy(desc(opsBatchLog.startedAt))
    .limit(20);

  return {
    totalWines: Number(totalWines?.n ?? 0),
    pricesTotal: Number(pricesTotal?.n ?? 0),
    ratingsTotal: Number(ratingsTotal?.n ?? 0),
    pendingDlq: Number(pendingDlq?.n ?? 0),
    stagingPending: Number(stagingPending?.n ?? 0),
    promotableCount: promotableRows.length,
    recentBatches,
  };
}

/* ─── Dead-letter queue (quarantine) ───────────────────────────────────────── */

// All valid error classes for the filter pills + query validation.
export const ERROR_CLASSES = [
  "network_error",
  "parse_error",
  "schema_drift",
  "auth_error",
  "validation_error",
  "region_gate",
  "critic_enum",
  "multi_source_rule",
  "reconcile_error",
  "fx_missing",
  "unresolved_dim",
  "unmatched_wine",
  "scraper_not_applicable",
  "source_dead",
] as const;

export type ErrorClass = (typeof ERROR_CLASSES)[number];

export function isErrorClass(v: string): v is ErrorClass {
  return (ERROR_CLASSES as readonly string[]).includes(v);
}

export interface DlqRow {
  dlq: typeof opsDeadLetter.$inferSelect;
  source: typeof dimSource.$inferSelect | null;
}

/**
 * Pending dead-letter (quarantine) records joined to their source, optionally
 * filtered by error class. Shared by the quarantaine page (SSR) and
 * GET /api/dlq.
 */
export async function getDlqRows(errorClass?: ErrorClass | null): Promise<DlqRow[]> {
  const whereClause = errorClass
    ? and(eq(opsDeadLetter.resolution, "pending"), eq(opsDeadLetter.errorClass, errorClass))
    : eq(opsDeadLetter.resolution, "pending");

  return db
    .select({ dlq: opsDeadLetter, source: dimSource })
    .from(opsDeadLetter)
    .leftJoin(dimSource, eq(opsDeadLetter.sourceKey, dimSource.sourceKey))
    .where(whereClause)
    .orderBy(desc(opsDeadLetter.createdAt))
    .limit(200);
}

/* ─── Auth-requiring sources ───────────────────────────────────────────────── */

function envKey(sourceCode: string): string {
  return sourceCode.toUpperCase().replace(/-/g, "_");
}

function hasCredentials(sourceCode: string): boolean {
  const k = envKey(sourceCode);
  const u = process.env[`ACHILLES_AUTH_${k}_USERNAME`]?.trim() ?? "";
  const p = process.env[`ACHILLES_AUTH_${k}_PASSWORD`] ?? "";
  return u.length > 0 && p.length > 0;
}

/**
 * Sources that require authentication, with the presence of their env-var
 * credentials resolved. Shared by the admin auth page (SSR) and
 * GET /api/sources/auth.
 */
export async function getAuthSources(): Promise<AuthSourceRow[]> {
  const sources = await db
    .select({
      sourceKey: dimSource.sourceKey,
      sourceCode: dimSource.sourceCode,
      sourceName: dimSource.sourceName,
      sourceTier: dimSource.sourceTier,
      baseUrl: dimSource.baseUrl,
      requiresAuth: dimSource.requiresAuth,
      enabled: dimSource.enabled,
    })
    .from(dimSource)
    .where(eq(dimSource.requiresAuth, true))
    .orderBy(asc(dimSource.sourceCode));

  return sources.map((s) => ({
    sourceKey: s.sourceKey,
    sourceCode: s.sourceCode,
    sourceName: s.sourceName,
    sourceTier: s.sourceTier,
    baseUrl: s.baseUrl,
    enabled: s.enabled,
    hasCredentials: hasCredentials(s.sourceCode),
    envUserVar: `ACHILLES_AUTH_${envKey(s.sourceCode)}_USERNAME`,
    envPassVar: `ACHILLES_AUTH_${envKey(s.sourceCode)}_PASSWORD`,
  }));
}

/* ─── Catalogue coverage ───────────────────────────────────────────────────── */

export interface CoverageRegionRow {
  region: string | null;
  total: number;
  withCuvee: number;
  withPrice: number;
  withRating: number;
}

interface CoverageTierRow {
  tier: string | null;
  n: number;
}

export interface CoverageData {
  total: number;
  withCuvee: number;
  withMultiPrice: number;
  withMultiRating: number;
  coverageScore: number;
  coverageScorePct: number;
  tierMap: Record<string, number>;
  regionBreakdown: CoverageRegionRow[];
}

/**
 * Catalogue coverage score (cuvée + multi-price + multi-rating completeness),
 * tier breakdown, and per-region breakdown. Shared by the admin coverage page
 * (SSR) and GET /api/coverage.
 */
export async function getCoverageData(): Promise<CoverageData> {
  const [{ total }] = await db.select({ total: count() }).from(dimProducer);

  const [{ withCuvee }] = await db
    .select({ withCuvee: countDistinct(dimWine.producerKey) })
    .from(dimWine);

  const multiPriceRows = await db
    .select({ wineKey: factPrice.wineKey })
    .from(factPrice)
    .groupBy(factPrice.wineKey)
    .having(sql`count(distinct ${factPrice.sourceKey}) >= 2`);

  const multiRatingRows = await db
    .select({ wineKey: factRating.wineKey })
    .from(factRating)
    .groupBy(factRating.wineKey)
    .having(sql`count(distinct ${factRating.criticCode}) >= 2`);

  const withMultiPrice = multiPriceRows.length;
  const withMultiRating = multiRatingRows.length;

  const coverageScore =
    total > 0 ? (withCuvee + withMultiPrice + withMultiRating) / (3 * total) : 0;

  const tierRows = (await db
    .select({ tier: dimProducer.coverageTier, n: count() })
    .from(dimProducer)
    .groupBy(dimProducer.coverageTier)) as CoverageTierRow[];

  // Per-region breakdown (French producers only, top 20 by total)
  // Using the underlying better-sqlite3 instance for the complex JOIN
  const sqlite = globalThis.__achillesSqlite!;
  const regionBreakdown = sqlite.prepare(`
    SELECT
      dp.region,
      COUNT(DISTINCT dp.producer_key) AS total,
      COUNT(DISTINCT dw.producer_key) AS with_cuvee,
      COUNT(DISTINCT CASE WHEN fp.wine_key IS NOT NULL THEN dw.producer_key END) AS with_price,
      COUNT(DISTINCT CASE WHEN fr.wine_key IS NOT NULL THEN dw.producer_key END) AS with_rating
    FROM dim_producer dp
    LEFT JOIN dim_wine dw ON dw.producer_key = dp.producer_key
    LEFT JOIN fact_price fp ON fp.wine_key = dw.wine_key
    LEFT JOIN fact_rating fr ON fr.wine_key = dw.wine_key
    WHERE dp.country_code = 'FR'
    GROUP BY dp.region
    ORDER BY total DESC
    LIMIT 20
  `).all() as CoverageRegionRow[];

  const tierMap: Record<string, number> = {};
  for (const row of tierRows) {
    tierMap[row.tier ?? "unknown"] = row.n;
  }

  return {
    total,
    withCuvee,
    withMultiPrice,
    withMultiRating,
    coverageScore,
    coverageScorePct: Math.round(coverageScore * 100),
    tierMap,
    regionBreakdown,
  };
}
