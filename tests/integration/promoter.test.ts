import { describe, it, expect } from "vitest";
import { applyTriSourceRule, type ScrapedPriceCandidate } from "@/lib/quality/gates";

function makeCandidate(wineKey: string, amountEur: number, sourceUrl: string): ScrapedPriceCandidate {
  return { wineKey, retailer: "test", amountLocal: amountEur, currencyCode: "EUR", amountEur, recordedAt: new Date(), sourceUrl, contentHash: "h", batchId: "b1" };
}

describe("Tri-source rule integration", () => {
  it("promotes 2 concordant candidates (same wine, prices within 15%)", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [
        makeCandidate("wine1", 120, "https://millesima.fr/1"),
        makeCandidate("wine1", 125, "https://idealwine.com/1"),
      ],
    });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(0);
  });

  it("does not promote when prices diverge >15%", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [
        makeCandidate("wine2", 100, "https://millesima.fr/2"),
        makeCandidate("wine2", 150, "https://idealwine.com/2"),
      ],
    });
    expect(promoted).toHaveLength(0);
    expect(pending).toHaveLength(2);
  });

  it("handles mixed wines correctly", () => {
    const { promoted, pending } = applyTriSourceRule({
      candidates: [
        makeCandidate("wine3", 200, "s1"),
        makeCandidate("wine3", 205, "s2"),
        makeCandidate("wine4", 100, "s3"),  // single wine4 → pending
      ],
    });
    expect(promoted).toHaveLength(2);
    expect(pending).toHaveLength(1);
    expect(pending[0].wineKey).toBe("wine4");
  });
});
