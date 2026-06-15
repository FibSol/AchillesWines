import { db } from "@/db";
import { dimProducer } from "@/db/schema";
import { eq, desc, like, or, and, sql, asc, isNotNull, type SQL } from "drizzle-orm";

export const PRODUCERS_PAGE_SIZE = 100;

export interface ProducerFilters {
  q?: string;
  country?: string;
  region?: string;
  tier?: number;
}

export interface ProducerFacetCountry {
  code: string;
  count: number;
  regions: Array<{ name: string; count: number }>;
}

export type ProducerRow = typeof dimProducer.$inferSelect;

export interface ProducersResult {
  producers: ProducerRow[];
  totalMatching: number;
  totalAll: number;
  facets: {
    countries: ProducerFacetCountry[];
    tiers: number[];
  };
}

/**
 * Producer (domaine) directory: filtered list + sidebar country/region tree +
 * tier facets. Shared by the domaines page (SSR) and GET /api/producers.
 */
export async function getProducers(filters: ProducerFilters = {}): Promise<ProducersResult> {
  const conditions: SQL[] = [eq(dimProducer.status, "active")];

  if (filters.q && filters.q.trim()) {
    const needle = `%${filters.q.trim().toLowerCase()}%`;
    const orClause = or(
      like(sql<string>`lower(${dimProducer.producerName})`, needle),
      like(sql<string>`lower(${dimProducer.producerNorm})`, needle),
    );
    if (orClause) conditions.push(orClause);
  }
  if (filters.country) {
    conditions.push(eq(dimProducer.countryCode, filters.country));
  }
  if (filters.region) {
    conditions.push(eq(dimProducer.region, filters.region));
  }
  if (filters.tier !== undefined && Number.isFinite(filters.tier)) {
    conditions.push(eq(dimProducer.tier, filters.tier));
  }

  const whereExpr = conditions.length === 1 ? conditions[0] : and(...conditions);

  const [producers, [countRow], countryRegionCounts, tierRows] = await Promise.all([
    db
      .select()
      .from(dimProducer)
      .where(whereExpr)
      .orderBy(desc(dimProducer.tier), dimProducer.producerName)
      .limit(PRODUCERS_PAGE_SIZE),
    db
      .select({ total: sql<number>`count(*)` })
      .from(dimProducer)
      .where(whereExpr),
    db
      .select({
        country: dimProducer.countryCode,
        region: dimProducer.region,
        count: sql<number>`count(*)`,
      })
      .from(dimProducer)
      .where(eq(dimProducer.status, "active"))
      .groupBy(dimProducer.countryCode, dimProducer.region)
      .orderBy(asc(dimProducer.countryCode), asc(dimProducer.region)),
    db
      .selectDistinct({ tier: dimProducer.tier })
      .from(dimProducer)
      .where(and(eq(dimProducer.status, "active"), isNotNull(dimProducer.tier)))
      .orderBy(asc(dimProducer.tier)),
  ]);

  const totalMatching = Number(countRow?.total ?? 0);

  // Build sidebar tree: country → regions with counts
  const countryMap = new Map<string, { count: number; regions: Map<string, number> }>();
  for (const row of countryRegionCounts) {
    const code = row.country;
    if (!countryMap.has(code)) {
      countryMap.set(code, { count: 0, regions: new Map() });
    }
    const entry = countryMap.get(code)!;
    const n = Number(row.count);
    entry.count += n;
    if (row.region) {
      entry.regions.set(row.region, (entry.regions.get(row.region) ?? 0) + n);
    }
  }
  const countries: ProducerFacetCountry[] = Array.from(countryMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([code, { count, regions }]) => ({
      code,
      count,
      regions: Array.from(regions.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, cnt]) => ({ name, count: cnt })),
    }));
  const totalAll = countries.reduce((s, c) => s + c.count, 0);

  const tiers = tierRows
    .map((r) => r.tier)
    .filter((t): t is number => t !== null);

  return { producers, totalMatching, totalAll, facets: { countries, tiers } };
}
