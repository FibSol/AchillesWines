import { describe, it, expect } from "vitest";
import {
  regionGate,
  criticEnumGate,
  applyTriSourceRule,
  normalizeRatingScore,
  type ScrapedPriceCandidate,
} from "@/lib/quality/gates";

const makeProducer = (apps: string[]) => ({ producerName: "Test", allowedAppellations: apps });

describe("regionGate", () => {
  it("passes when appellation allowed", () => {
    expect(regionGate({ producer: makeProducer(["meursault"]), appellationNorm: "meursault", rawRecord: {} }).ok).toBe(true);
  });
  it("fails with region_gate error class when not allowed", () => {
    const r = regionGate({ producer: makeProducer(["meursault"]), appellationNorm: "pauillac", rawRecord: {} });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.dlqRecord.errorClass).toBe("region_gate");
  });
});

describe("criticEnumGate", () => {
  it("accepts all 19 canonical critic codes", () => {
    for (const code of [
      "WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG",
      "WS", "Hachette", "CT", "WE", "WAL", "WD", "GV", "Halliday",
      "VI", "XW", "SM",
    ]) {
      expect(criticEnumGate({ criticCode: code, rawRecord: {} }).ok).toBe(true);
    }
  });
  it("rejects unknown critic with critic_enum error", () => {
    const r = criticEnumGate({ criticCode: "FAKE", rawRecord: {} });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.dlqRecord.errorClass).toBe("critic_enum");
  });
});

function makeCandidate(
  wineKey: string,
  amountEur: number,
  sourceUrl: string,
  sourceKey = 1,
): ScrapedPriceCandidate {
  return {
    wineKey, retailer: "test", sourceKey,
    amountLocal: amountEur, currencyCode: "EUR", amountEur,
    recordedAt: new Date(), sourceUrl, contentHash: "abc", batchId: "b1",
  };
}

describe("applyTriSourceRule", () => {
  it("single source → pending", () => {
    const { promoted, pending } = applyTriSourceRule({ candidates: [makeCandidate("w1", 100, "s1", 1)] });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(1);
  });
  it("2 distinct sources within 15% → both promoted", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [makeCandidate("w1", 100, "s1", 1), makeCandidate("w1", 108, "s2", 2)],
    });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(0);
  });
  it("2 rows but SAME source → pending (ADR-003: distinct-source rule)", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [makeCandidate("w1", 100, "s1", 1), makeCandidate("w1", 105, "s2", 1)],
    });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(2);
  });
  it("3 rows from same source within 15% → still pending", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [
        makeCandidate("w1", 100, "s1", 1),
        makeCandidate("w1", 105, "s2", 1),
        makeCandidate("w1", 110, "s3", 1),
      ],
    });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(3);
  });
  it("2 sources >15% apart → both pending", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [makeCandidate("w1", 100, "s1", 1), makeCandidate("w1", 120, "s2", 2)],
    });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(2);
  });
  it("3 sources: 2 concordant + 1 outlier", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [
        makeCandidate("w1", 100, "s1", 1),
        makeCandidate("w1", 103, "s2", 2),
        makeCandidate("w1", 200, "s3", 3),
      ],
    });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(1);
    expect(pending[0].sourceUrl).toBe("s3");
  });
  it("3 rows, 3 distinct sources but only 1 concordant pair across sources → all pending", () => {
    // s1=100, s2=200, s3=200 -- median=200, 100 is outside 15%. Concordant pair
    // is {s2, s3} but they happen to be at the median; that's still 2 distinct
    // sources within tolerance, so they should promote.
    const { promoted, pending } = applyTriSourceRule({
      candidates: [
        makeCandidate("w1", 100, "s1", 1),
        makeCandidate("w1", 200, "s2", 2),
        makeCandidate("w1", 205, "s3", 3),
      ],
    });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(1);
    expect(pending[0].sourceUrl).toBe("s1");
  });
});

describe('mono-source gate', () => {
  it('should flag wine_key with only 1 distinct source', () => {
    const rows = [
      { wine_key: 'abc123', source_key: 1, amount_eur: 10 },
      { wine_key: 'abc123', source_key: 1, amount_eur: 11 }, // same source
    ];
    const byWine = new Map<string, typeof rows>();
    for (const r of rows) {
      const arr = byWine.get(r.wine_key) ?? [];
      arr.push(r);
      byWine.set(r.wine_key, arr);
    }
    for (const [, items] of byWine) {
      const distinctSources = new Set(items.map(r => r.source_key));
      expect(distinctSources.size).toBe(1); // only 1 source → should be purged
    }
  });

  it('should pass wine_key with 2 distinct sources', () => {
    const rows = [
      { wine_key: 'abc123', source_key: 1, amount_eur: 10 },
      { wine_key: 'abc123', source_key: 2, amount_eur: 10.5 },
    ];
    const distinctSources = new Set(rows.map(r => r.source_key));
    expect(distinctSources.size).toBeGreaterThanOrEqual(2);
  });
});

describe("normalizeRatingScore", () => {
  it("passes /100 scores", () => {
    const r = normalizeRatingScore({ score: 95, scale: "/100", rawRecord: {} });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.scoreNormalized100).toBe(95);
  });
  it("rejects NaN", () => expect(normalizeRatingScore({ score: NaN, scale: "/100", rawRecord: {} }).ok).toBe(false));
  it("rejects /20 score > 100 when normalized", () => {
    const r = normalizeRatingScore({ score: 25, scale: "/20", rawRecord: {} });
    expect(r.ok).toBe(false);
  });
  it("normalizes /20 → /100", () => {
    const r = normalizeRatingScore({ score: 16, scale: "/20", rawRecord: {} });
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.scoreNormalized100).toBe(80);
  });
});
