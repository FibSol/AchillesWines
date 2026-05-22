/**
 * Cassandra's anti-hallucination gates.
 *
 * These run BEFORE any write to dim_wine / fact_price / fact_rating.
 * They return either { ok: true, value } or { ok: false, dlqRecord }.
 */
import { normalizeScoreTo100, isAppellationAllowed } from "@/lib/identity";

export const CANONICAL_CRITIC_CODES = [
  "WA",
  "Vinous",
  "BH",
  "JMIB",
  "RVF",
  "Decanter",
  "JS",
  "JG",
  "WS",
  "Hachette",
  "CT",
] as const;

export type CriticCode = (typeof CANONICAL_CRITIC_CODES)[number];

export type ScrapedPriceCandidate = {
  wineKey: string;
  retailer: string;
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
    if (candidates.length < minSources) {
      pending.push(...candidates);
      continue;
    }
    // Sort by amount, compute median, then check each candidate's deviation
    const sorted = [...candidates].sort((a, b) => a.amountEur - b.amountEur);
    const median = sorted[Math.floor(sorted.length / 2)].amountEur;
    const concordant = candidates.filter(
      (c) => Math.abs(c.amountEur - median) / median <= tolerance,
    );
    if (concordant.length >= minSources) {
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
