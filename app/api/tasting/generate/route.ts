import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { loadTastingCandidates } from "@/lib/tasting/candidates";
import { buildFlight, TASTING_MODES, type TastingMode } from "@/lib/tasting/engine";

export const dynamic = "force-dynamic";

const FiltersSchema = z.object({
  countries: z.array(z.string()).default([]),
  regions: z.array(z.string()).default([]),
  colors: z.array(z.string()).default([]),
  minRating: z.number().min(0).max(100).nullable().default(null),
  maxPriceEur: z.number().nonnegative().nullable().default(null),
});

const PostBody = z.object({
  mode: z.enum(TASTING_MODES as [string, ...string[]]),
  count: z.number().int().min(2).max(8).default(6),
  axisId: z.string().optional(),
  lockedWineKeys: z.array(z.string()).max(8).default([]),
  excludeWineKeys: z.array(z.string()).max(200).default([]),
  filters: FiltersSchema.optional(),
});

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = PostBody.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues.map((i) => i.message).join(", ") },
      { status: 400 },
    );
  }
  const { mode, count, axisId, lockedWineKeys, excludeWineKeys, filters } = parsed.data;

  let pool = await loadTastingCandidates();
  if (pool.length === 0) {
    return NextResponse.json({ flight: null, poolSize: 0, empty: true });
  }

  // Apply filters (locked wines are always kept regardless of filters)
  if (filters) {
    const lockedSet = new Set(lockedWineKeys);
    pool = pool.filter((c) => {
      if (lockedSet.has(c.wineKey)) return true;
      if (filters.countries.length > 0 && !filters.countries.includes(c.countryCode)) return false;
      if (filters.regions.length > 0 && !filters.regions.includes(c.region)) return false;
      if (filters.colors.length > 0 && !filters.colors.includes(c.color)) return false;
      if (filters.minRating !== null) {
        const rating = c.avgRating ?? 0;
        if (rating < filters.minRating) return false;
      }
      if (filters.maxPriceEur !== null) {
        const price = c.avgPriceEur ?? 0;
        if (price > filters.maxPriceEur) return false;
      }
      return true;
    });
    if (pool.length === 0) {
      return NextResponse.json({ flight: null, poolSize: 0, empty: true, filteredEmpty: true });
    }
  }

  const flight = buildFlight(mode as TastingMode, pool, {
    count,
    axisId,
    lockedWineKeys,
    excludeWineKeys,
    currentYear: new Date().getFullYear(),
  });

  // Minimal pool list for the "add / swap from cellar" picker.
  const poolWines = pool
    .map((p) => ({
      wineKey: p.wineKey,
      producerName: p.producerName,
      cuveeName: p.cuveeName,
      vintage: p.vintage,
      color: p.color,
      region: p.region,
      qty: p.qty,
    }))
    .sort((a, b) => a.producerName.localeCompare(b.producerName));

  return NextResponse.json({ flight, poolWines, poolSize: pool.length, empty: false });
}
