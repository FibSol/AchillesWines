import { describe, it, expect } from "vitest";
import { scorePairing, type CourseType, type WineColor } from "@/lib/pairing";

interface PartialInputs {
  course?: CourseType;
  dishText?: string;
  wineColor?: WineColor;
  ratingNorm100?: number | null;
  inventoryQty?: number;
  pricePerGuestEur?: number | null;
  budgetPerGuestEur?: number | null;
}

function mk(overrides: PartialInputs = {}) {
  return scorePairing({
    course: overrides.course ?? "plat",
    dishText: overrides.dishText ?? "",
    wineColor: overrides.wineColor ?? "red",
    ratingNorm100: overrides.ratingNorm100 ?? null,
    inventoryQty: overrides.inventoryQty ?? 0,
    pricePerGuestEur: overrides.pricePerGuestEur ?? null,
    budgetPerGuestEur: overrides.budgetPerGuestEur ?? null,
  });
}

describe("scorePairing — course color defaults", () => {
  it("apéritif favors sparkling over red", () => {
    const sparkling = mk({ course: "aperitif", wineColor: "sparkling" });
    const red = mk({ course: "aperitif", wineColor: "red" });
    expect(sparkling.colorMatch).toBeGreaterThan(red.colorMatch);
    expect(red.colorMatch).toBe(0);
  });

  it("dessert favors sweet over red", () => {
    const sweet = mk({ course: "dessert", wineColor: "sweet" });
    const red = mk({ course: "dessert", wineColor: "red" });
    expect(sweet.colorMatch).toBeGreaterThan(red.colorMatch);
    expect(red.colorMatch).toBe(0);
  });

  it("plat favors red over sparkling", () => {
    const red = mk({ course: "plat", wineColor: "red" });
    const sparkling = mk({ course: "plat", wineColor: "sparkling" });
    expect(red.colorMatch).toBeGreaterThan(sparkling.colorMatch);
  });

  it("fromage gives non-zero weight to red, white, fortified, sweet", () => {
    for (const color of ["red", "white", "fortified", "sweet"] as WineColor[]) {
      const s = mk({ course: "fromage", wineColor: color });
      expect(s.colorMatch).toBeGreaterThan(0);
    }
  });

  it("orange wine has fallback weight on aperitif and entree", () => {
    expect(mk({ course: "aperitif", wineColor: "orange" }).colorMatch).toBeGreaterThan(0);
    expect(mk({ course: "entree", wineColor: "orange" }).colorMatch).toBeGreaterThan(0);
  });
});

describe("scorePairing — dish keyword boosts", () => {
  it("boeuf bourguignon boosts red", () => {
    const plain = mk({ course: "plat", wineColor: "red", dishText: "" });
    const bourguignon = mk({ course: "plat", wineColor: "red", dishText: "boeuf bourguignon" });
    expect(bourguignon.colorMatch).toBeGreaterThan(plain.colorMatch);
  });

  it("magret de canard boosts red", () => {
    const s = mk({ course: "plat", wineColor: "red", dishText: "magret de canard aux cèpes" });
    expect(s.colorMatch).toBeGreaterThan(80);
  });

  it("saumon fumé boosts white but not red", () => {
    const white = mk({ course: "plat", wineColor: "white", dishText: "saumon fumé" });
    const red = mk({ course: "plat", wineColor: "red", dishText: "saumon fumé" });
    expect(white.colorMatch).toBeGreaterThan(red.colorMatch);
  });

  it("chocolat boosts fortified for dessert course", () => {
    const fortified = mk({ course: "dessert", wineColor: "fortified", dishText: "moelleux chocolat" });
    const baseline = mk({ course: "dessert", wineColor: "fortified", dishText: "" });
    expect(fortified.colorMatch).toBeGreaterThan(baseline.colorMatch);
  });

  it("roquefort boosts sweet and fortified", () => {
    const sweet = mk({ course: "fromage", wineColor: "sweet", dishText: "roquefort affiné" });
    const fortified = mk({ course: "fromage", wineColor: "fortified", dishText: "roquefort affiné" });
    const sweetBase = mk({ course: "fromage", wineColor: "sweet", dishText: "" });
    expect(sweet.colorMatch).toBeGreaterThan(sweetBase.colorMatch);
    expect(fortified.colorMatch).toBeGreaterThan(0);
  });

  it("English keywords work too (steak)", () => {
    const red = mk({ course: "plat", wineColor: "red", dishText: "ribeye steak" });
    const baseline = mk({ course: "plat", wineColor: "red", dishText: "" });
    expect(red.colorMatch).toBeGreaterThan(baseline.colorMatch);
  });

  it("vegetarian dish boosts white/rosé/orange not red", () => {
    const white = mk({ course: "plat", wineColor: "white", dishText: "risotto aux asperges" });
    const orange = mk({ course: "plat", wineColor: "orange", dishText: "risotto aux asperges" });
    const whiteBase = mk({ course: "plat", wineColor: "white", dishText: "" });
    expect(white.colorMatch).toBeGreaterThan(whiteBase.colorMatch);
    expect(orange.colorMatch).toBeGreaterThan(0);
  });

  it("multiple keywords stack additively when both match", () => {
    const both = mk({ course: "plat", wineColor: "red", dishText: "magret de canard aux truffes" });
    const single = mk({ course: "plat", wineColor: "red", dishText: "magret de canard" });
    expect(both.colorMatch).toBeGreaterThan(single.colorMatch);
  });

  it("regex is case-insensitive and accent-aware", () => {
    const upper = mk({ course: "plat", wineColor: "red", dishText: "AGNEAU rôti" });
    const accented = mk({ course: "plat", wineColor: "red", dishText: "côtelette d'agneau" });
    expect(upper.colorMatch).toBeGreaterThan(80);
    expect(accented.colorMatch).toBeGreaterThan(80);
  });
});

describe("scorePairing — inventory bonus", () => {
  it("is zero when nothing in cellar", () => {
    expect(mk({ inventoryQty: 0 }).inventoryBonus).toBe(0);
  });

  it("rewards owning the wine", () => {
    const owned = mk({ inventoryQty: 1 });
    expect(owned.inventoryBonus).toBeGreaterThan(0);
    expect(owned.inventoryBonus).toBeLessThanOrEqual(30);
  });

  it("saturates at 30 for high quantities", () => {
    const ten = mk({ inventoryQty: 10 });
    const fifty = mk({ inventoryQty: 50 });
    expect(fifty.inventoryBonus).toBeLessThanOrEqual(30);
    expect(fifty.inventoryBonus).toBeGreaterThanOrEqual(ten.inventoryBonus);
  });

  it("monotonically increases with qty (1 < 3 < 6)", () => {
    const one = mk({ inventoryQty: 1 }).inventoryBonus;
    const three = mk({ inventoryQty: 3 }).inventoryBonus;
    const six = mk({ inventoryQty: 6 }).inventoryBonus;
    expect(three).toBeGreaterThanOrEqual(one);
    expect(six).toBeGreaterThanOrEqual(three);
  });
});

describe("scorePairing — rating score", () => {
  it("is zero when rating null", () => {
    expect(mk({ ratingNorm100: null }).ratingScore).toBe(0);
  });

  it("clamps at 0 when rating below 70", () => {
    expect(mk({ ratingNorm100: 60 }).ratingScore).toBe(0);
    expect(mk({ ratingNorm100: 50 }).ratingScore).toBe(0);
  });

  it("scales linearly from 70", () => {
    expect(mk({ ratingNorm100: 70 }).ratingScore).toBe(0);
    expect(mk({ ratingNorm100: 90 }).ratingScore).toBe(20);
    expect(mk({ ratingNorm100: 100 }).ratingScore).toBe(30);
  });
});

describe("scorePairing — budget penalty", () => {
  it("is zero when no budget set", () => {
    const r = mk({ pricePerGuestEur: 50, budgetPerGuestEur: null });
    expect(r.budgetPenalty).toBe(0);
  });

  it("is zero when price within budget", () => {
    const r = mk({ pricePerGuestEur: 20, budgetPerGuestEur: 30 });
    expect(r.budgetPenalty).toBe(0);
  });

  it("is negative when price over budget", () => {
    const r = mk({ pricePerGuestEur: 40, budgetPerGuestEur: 20 });
    expect(r.budgetPenalty).toBeLessThan(0);
  });

  it("saturates at -40", () => {
    const r = mk({ pricePerGuestEur: 1000, budgetPerGuestEur: 10 });
    expect(r.budgetPenalty).toBeGreaterThanOrEqual(-40);
    expect(r.budgetPenalty).toBeLessThan(0);
  });
});

describe("scorePairing — total composition", () => {
  it("total equals the four parts summed", () => {
    const r = mk({
      course: "plat",
      wineColor: "red",
      dishText: "magret de canard",
      ratingNorm100: 95,
      inventoryQty: 4,
      pricePerGuestEur: 50,
      budgetPerGuestEur: 30,
    });
    const sum = r.colorMatch + r.inventoryBonus + r.ratingScore + r.budgetPenalty;
    expect(r.total).toBeCloseTo(sum, 6);
  });

  it("a perfect match scores high (>140)", () => {
    const r = mk({
      course: "plat",
      wineColor: "red",
      dishText: "boeuf bourguignon aux truffes",
      ratingNorm100: 96,
      inventoryQty: 6,
      pricePerGuestEur: null,
      budgetPerGuestEur: null,
    });
    expect(r.total).toBeGreaterThan(140);
  });

  it("a mismatched pairing scores low or zero", () => {
    const r = mk({
      course: "dessert",
      wineColor: "red",
      dishText: "tarte aux fraises",
      ratingNorm100: null,
      inventoryQty: 0,
      pricePerGuestEur: null,
      budgetPerGuestEur: null,
    });
    // red on dessert has no default; tarte/fraises doesn't boost red → all four parts 0
    expect(r.total).toBe(0);
  });
});
