import { describe, it, expect } from "vitest";
import {
  normText,
  expandProducerPrefix,
  cleanCuveeTails,
  computeWineKey,
  isAppellationAllowed,
  normalizeScoreTo100,
} from "@/lib/identity";

describe("normText", () => {
  it("handles null/undefined/empty", () => {
    expect(normText(null)).toBe("");
    expect(normText(undefined)).toBe("");
    expect(normText("")).toBe("");
  });
  it("strips diacritics", () => {
    expect(normText("Château")).toBe("chateau");
    expect(normText("Côte de Nuits")).toBe("cote de nuits");
    expect(normText("Romanée-Conti")).toContain("romanee");
  });
  it("strips punctuation and collapses whitespace", () => {
    expect(normText("Dom. Leflaive")).toBe("dom leflaive");
    expect(normText("  many   spaces  ")).toBe("many spaces");
  });
  it("lowercases", () => {
    expect(normText("DOMAINE LEFLAIVE")).toBe("domaine leflaive");
  });
});

describe("expandProducerPrefix", () => {
  it("expands d + space", () => {
    expect(expandProducerPrefix("d leflaive")).toBe("domaine leflaive");
  });
  it("expands dom + space", () => {
    expect(expandProducerPrefix("dom leflaive")).toBe("domaine leflaive");
  });
  it("expands ch + space", () => {
    expect(expandProducerPrefix("ch petrus")).toBe("chateau petrus");
  });
  it("leaves other prefixes unchanged", () => {
    expect(expandProducerPrefix("maison leflaive")).toBe("maison leflaive");
  });
});

describe("cleanCuveeTails", () => {
  it("strips grand cru", () => {
    expect(cleanCuveeTails("montrachet grand cru")).not.toContain("grand cru");
  });
  it("strips premier cru", () => {
    const result = cleanCuveeTails("meursault 1er cru");
    expect(result).not.toMatch(/1\s*er/i);
  });
  it("strips vintage year", () => {
    expect(cleanCuveeTails("coche dury meursault 2021")).not.toContain("2021");
  });
  it("strips bottle sizes", () => {
    expect(cleanCuveeTails("petrus 750ml")).not.toMatch(/750\s*ml/i);
    expect(cleanCuveeTails("opus magnum")).not.toMatch(/magnum/i);
  });
});

describe("computeWineKey", () => {
  const base = { producerNorm: "domaine coche dury", cuveeNorm: "meursault perrieres", vintage: 2020, appellationNorm: "meursault premier cru" };
  it("is deterministic", () => {
    expect(computeWineKey(base)).toBe(computeWineKey(base));
  });
  it("returns 16-char hex", () => {
    const k = computeWineKey(base);
    expect(k).toHaveLength(16);
    expect(k).toMatch(/^[0-9a-f]{16}$/);
  });
  it("null vintage (NV) differs from year", () => {
    const kNV = computeWineKey({ ...base, vintage: null });
    expect(kNV).not.toBe(computeWineKey(base));
  });
  it("different vintages → different keys", () => {
    const k1 = computeWineKey({ ...base, vintage: 2019 });
    const k2 = computeWineKey({ ...base, vintage: 2020 });
    expect(k1).not.toBe(k2);
  });
});

describe("isAppellationAllowed", () => {
  it("true when in list", () => expect(isAppellationAllowed({ allowedAppellations: ["meursault"] }, "meursault")).toBe(true));
  it("false when not in list", () => expect(isAppellationAllowed({ allowedAppellations: ["meursault"] }, "pauillac")).toBe(false));
  it("false for empty list", () => expect(isAppellationAllowed({ allowedAppellations: [] }, "meursault")).toBe(false));
});

describe("normalizeScoreTo100", () => {
  it("/100 passthrough", () => expect(normalizeScoreTo100(95, "/100")).toBe(95));
  it("/20 scale", () => expect(normalizeScoreTo100(16, "/20")).toBe(80));
  it("/5 scale", () => expect(normalizeScoreTo100(4, "/5")).toBe(80));
  it("stars scale", () => expect(normalizeScoreTo100(5, "stars")).toBe(100));
});
