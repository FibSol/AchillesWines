import { NextResponse } from "next/server";
import { loadTastingCandidates } from "@/lib/tasting/candidates";
import { TASTING_MODES, modeFeasibility, type TastingMode } from "@/lib/tasting/engine";

export const dynamic = "force-dynamic";

/**
 * Reports how many wines are in stock and which tasting modes are feasible.
 * Also returns the pool summary (country, region, color, price, rating) for
 * building the filter UI client-side.
 */
export async function GET() {
  const pool = await loadTastingCandidates();
  const modes: Record<TastingMode, { feasible: boolean; axesCount: number; wineCount: number }> =
    {} as Record<TastingMode, { feasible: boolean; axesCount: number; wineCount: number }>;
  for (const m of TASTING_MODES) {
    modes[m] = modeFeasibility(m, pool);
  }

  const countries = [...new Set(pool.map((c) => c.countryCode).filter(Boolean))].sort();
  const regions = [...new Set(pool.map((c) => c.region).filter(Boolean))].sort();
  const colors = [...new Set(pool.map((c) => c.color).filter(Boolean))].sort();

  return NextResponse.json({ poolSize: pool.length, modes, countries, regions, colors });
}
