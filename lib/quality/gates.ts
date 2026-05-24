/**
 * Cassandra's anti-hallucination gates.
 *
 * These run BEFORE any write to dim_wine / fact_price / fact_rating.
 * They return either { ok: true, value } or { ok: false, dlqRecord }.
 */
import { normalizeScoreTo100, isAppellationAllowed } from "@/lib/identity";

// Kept in sync with VALID_CRITIC_CODES in scraper/achilles_scraper/scrapers/*.py.
// Any divergence between the two will silently misroute crowd-aggregator rows
// into the DLQ (or vice versa). Audited 2026-05-23.
export const CANONICAL_CRITIC_CODES = [
  "WA",        // Wine Advocate (Parker)
  "Vinous",    // Antonio Galloni / Vinous (formerly IWC)
  "BH",        // Burghound (Meadows)
  "JMIB",      // Jasper Morris / Inside Burgundy (and JR shares this slot historically)
  "RVF",       // La Revue du Vin de France
  "Decanter",
  "JS",        // James Suckling
  "JG",        // Jeb Dunnuck (column key 'JG' in CT exports)
  "WS",        // Wine Spectator
  "Hachette",  // Guide Hachette des Vins
  "CT",        // CellarTracker community avg
  "WE",        // Wine Enthusiast
  "WAL",       // Wine Align
  "WD",        // The Wine Doctor
  "GV",        // Gilbert & Gaillard
  "Halliday",  // James Halliday Wine Companion
  "VI",        // Vivino community average (tiebreaker only — ADR-013)
] as const;

export type CriticCode = (typeof CANONICAL_CRITIC_CODES)[number];

export type ScrapedPriceCandidate = {
  wineKey: string;
  retailer: string;
  /** dim_source.source_key — used to enforce the ≥2-distinct-sources rule (ADR-003). */
  sourceKey: number;
  amountLocal: number;
  currencyCode: string;
  amountEur: number;
  recordedAt: Date;
  sourceUrl: string;
  contentHash: string;
  batchId: string;
};

export type DlqRecord = {
  errorClass: string;
  errorMessage: string;
  rawRecord: Record<string, unknown>;
};

/* ----------------------------- region gate ------------------------------- */

export function regionGate(opts: {
  producer: { producerName: string; allowedAppellations: string[] };
  appellationNorm: string;
  rawRecord: Record<string, unknown>;
}): { ok: true } | { ok: false; dlqRecord: DlqRecord } {
  if (!isAppellationAllowed(opts.producer, opts.appellationNorm)) {
    return {
      ok: false,
      dlqRecord: {
        errorClass: "region_gate",
        errorMessage: `Producer '${opts.producer.producerName}' has appellation '${opts.appellationNorm}' not in allowed list ${JSON.stringify(opts.producer.allowedAppellations)}`,
        rawRecord: opts.rawRecord,
      },
    };
  }
  return { ok: true };
}

/* ----------------------------- critic enum ------------------------------- */

export function criticEnumGate(opts: {
  criticCode: string;
  rawRecord: Record<string, unknown>;
}):
  | { ok: true; criticCode: CriticCode }
  | { ok: false; dlqRecord: DlqRecord } {
  const found = CANONICAL_CRITIC_CODES.find((c) => c === opts.criticCode);
  if (!found) {
    return {
      ok: false,
      dlqRecord: {
        errorClass: "critic_enum",
        errorMessage: `Critic code '${opts.criticCode}' not in canonical enum ${JSON.stringify(CANONICAL_CRITIC_CODES)}`,
        rawRecord: opts.rawRecord,
      },
    };
  }
  return { ok: true, criticCode: found };
}

/* ----------------------------- multi-source rule ------------------------- */

/**
 * For each (wine_key, retailer) candidate, we promote to fact_price only when
 * ≥2 sources concord ±15% within the same week.
 *
 * This function is called by a batch promoter that runs after each scraping batch.
 */
export function applyTriSourceRule(opts: {
  candidates: ScrapedPriceCandidate[];
  toleranceFraction?: number;
  minSources?: number;
}): {
  promoted: ScrapedPriceCandidate[];
  pending: ScrapedPriceCandidate[];
} {
  const tolerance = opts.toleranceFraction ?? 0.15;
  const minSources = opts.minSources ?? 2;

  // Group by wine_key
  const byWine = new Map<string, ScrapedPriceCandidate[]>();
  for (const c of opts.candidates) {
    const arr = byWine.get(c.wineKey) ?? [];
    arr.push(c);
    byWine.set(c.wineKey, arr);
  }

  const promoted: ScrapedPriceCandidate[] = [];
  const pending: ScrapedPriceCandidate[] = [];

  for (const [, candidates] of byWine) {
    // ADR-003: require ≥minSources *distinct* sourceKeys, not just rows.
    const distinctSources = new Set(candidates.map((c) => c.sourceKey));
    if (distinctSources.size < minSources) {
      pending.push(...candidates);
      continue;
    }
    // Sort by amount, compute median, then check each candidate's deviation
    const sorted = [...candidates].sort((a, b) => a.amountEur - b.amountEur);
    const median = sorted[Math.floor(sorted.length / 2)].amountEur;
    const concordant = candidates.filter(
      (c) => Math.abs(c.amountEur - median) / median <= tolerance,
    );
    const concordantDistinct = new Set(concordant.map((c) => c.sourceKey));
    if (concordant.length >= minSources && concordantDistinct.size >= minSources) {
      promoted.push(...concordant);
      const outliers = candidates.filter(
        (c) => !concordant.some((cc) => cc.sourceUrl === c.sourceUrl),
      );
      pending.push(...outliers);
    } else {
      pending.push(...candidates);
    }
  }

  return { promoted, pending };
}

/* ----------------------------- score normalization ----------------------- */

export function normalizeRatingScore(opts: {
  score: number;
  scale: "/100" | "/20" | "/5" | "stars";
  rawRecord: Record<string, unknown>;
}):
  | { ok: true; scoreNormalized100: number }
  | { ok: false; dlqRecord: DlqRecord } {
  if (!Number.isFinite(opts.score)) {
    return {
      ok: false,
      dlqRecord: {
        errorClass: "validation_error",
        errorMessage: `Score is not finite: ${opts.score}`,
        rawRecord: opts.rawRecord,
      },
    };
  }
  const n = normalizeScoreTo100(opts.score, opts.scale);
  if (n < 0 || n > 100) {
    return {
      ok: false,
      dlqRecord: {
        errorClass: "validation_error",
        errorMessage: `Normalized score out of [0,100]: ${n}`,
        rawRecord: opts.rawRecord,
      },
    };
  }
  return { ok: true, scoreNormalized100: n };
}
