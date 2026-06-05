import { NextResponse } from "next/server";
import { loadTastingCandidates } from "@/lib/tasting/candidates";
import { TASTING_MODES, modeFeasibility, type TastingMode } from "@/lib/tasting/engine";

export const dynamic = "force-dynamic";

/**
 * Reports how many wines are in stock and which tasting modes are feasible.
 * Powers the mode picker (greys out modes the cellar can't support yet).
 */
export async function GET() {
  const pool = await loadTastingCandidates();
  const modes: Record<TastingMode, { feasible: boolean; axesCount: number; wineCount: number }> =
    {} as Record<TastingMode, { feasible: boolean; axesCount: number; wineCount: number }>;
  for (const m of TASTING_MODES) {
    modes[m] = modeFeasibility(m, pool);
  }
  return NextResponse.json({ poolSize: pool.length, modes });
}
