import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { loadTastingCandidates } from "@/lib/tasting/candidates";
import {
  buildFlight,
  guestToCandidate,
  isReadyToDrink,
  TASTING_MODES,
  type TastingMode,
} from "@/lib/tasting/engine";

const WINE_COLORS = ["red", "white", "rosé", "sparkling", "sweet", "fortified", "orange"] as const;
const APPELLATION_LEVELS = ["regional", "village", "premier_cru", "grand_cru", "iconic"] as const;

/** An off-cellar "guest" bottle folded into the flight for this request only (never persisted). */
const GuestWineSchema = z.object({
  wineKey: z.string().startsWith("guest:").max(80),
  producerName: z.string().min(1).max(120),
  cuveeName: z.string().max(120).default(""),
  vintage: z.number().int().min(1900).max(2100).nullable().default(null),
  color: z.enum(WINE_COLORS),
  appellationName: z.string().max(120).default(""),
  countryCode: z.string().min(2).max(3).default("FR"),
  region: z.string().max(120).default(""),
  level: z.enum(APPELLATION_LEVELS).default("regional"),
  varieties: z.array(z.string().max(60)).max(8).default([]),
  alcoholPct: z.number().min(0).max(25).nullable().default(null),
  avgPriceEur: z.number().nonnegative().nullable().default(null),
});

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
  /** Off-cellar bottles folded into the flight (max one full flight's worth). */
  guestWines: z.array(GuestWineSchema).max(8).default([]),
  /** "Surprise me": randomize the progressive selection. */
  shuffle: z.boolean().default(false),
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
  const { mode, count, axisId, lockedWineKeys, excludeWineKeys, filters, guestWines, shuffle } =
    parsed.data;
  const currentYear = new Date().getFullYear();

  // Guest bottles are always kept and always in the flight: treat them as locked
  // so they bypass the readiness filter, the user filters and the selection logic.
  const guests = guestWines.map(guestToCandidate);
  const guestKeys = guests.map((g) => g.wineKey);
  const effectiveLocked = [...new Set([...lockedWineKeys, ...guestKeys])];

  let pool = [...guests, ...(await loadTastingCandidates())];
  if (pool.length === 0) {
    return NextResponse.json({ flight: null, poolSize: 0, empty: true });
  }

  // Never propose a wine that is not ready to drink (too young for its style).
  // Locked / guest wines are the user's explicit choice and stay in.
  const lockedKeys = new Set(effectiveLocked);
  pool = pool.filter((c) => lockedKeys.has(c.wineKey) || isReadyToDrink(c, currentYear));
  if (pool.length === 0) {
    return NextResponse.json({ flight: null, poolSize: 0, empty: true });
  }

  // Apply filters (locked / guest wines are always kept regardless of filters)
  if (filters) {
    const lockedSet = new Set(effectiveLocked);
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
    lockedWineKeys: effectiveLocked,
    excludeWineKeys,
    currentYear,
    rng: shuffle ? Math.random : undefined,
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
