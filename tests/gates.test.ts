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
  it("accepts all canonical critic codes", () => {
    for (const code of ["WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT"]) {
      expect(criticEnumGate({ criticCode: code, rawRecord: {} }).ok).toBe(true);
    }
  });
  it("rejects unknown critic with critic_enum error", () => {
    const r = criticEnumGate({ criticCode: "FAKE", rawRecord: {} });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.dlqRecord.errorClass).toBe("critic_enum");
  });
});

function makeCandidate(wineKey: string, amountEur: number, sourceUrl: string): ScrapedPriceCandidate {
  return { wineKey, retailer: "test", amountLocal: amountEur, currencyCode: "EUR", amountEur, recordedAt: new Date(), sourceUrl, contentHash: "abc", batchId: "b1" };
}

describe("applyTriSourceRule", () => {
  it("single source → pending", () => {
    const { promoted, pending } = applyTriSourceRule({ candidates: [makeCandidate("w1", 100, "s1")] });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(1);
  });
  it("2 sources within 15% → both promoted", () => {
    const { promoted, pending } = applyTriSourceRule({ candidates: [makeCandidate("w1", 100, "s1"), makeCandidate("w1", 108, "s2")] });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(0);
  });
  it("2 sources >15% apart → both pending", () => {
    const { promoted, pending } = applyTriSourceRule({ candidates: [makeCandidate("w1", 100, "s1"), makeCandidate("w1", 120, "s2")] });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(2);
  });
  it("3 sources: 2 concordant + 1 outlier", () => {
    const { promoted, pending } = applyTriSourceRule({ candidates: [makeCandidate("w1", 100, "s1"), makeCandidate("w1", 103, "s2"), makeCandidate("w1", 200, "s3")] });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(1);
    expect(pending[0].sourceUrl).toBe("s3");
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
