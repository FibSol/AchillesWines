import { describe, it, expect } from "vitest";
import {
  estimateWeight,
  orderFlight,
  buildFlight,
  modeFeasibility,
  type TastingCandidate,
} from "@/lib/tasting/engine";
import type { WineColor } from "@/lib/pairing";

let seq = 0;
function mk(o: Partial<TastingCandidate> = {}): TastingCandidate {
  seq += 1;
  return {
    wineKey: o.wineKey ?? `w${seq}`,
    producerName: o.producerName ?? `Producer ${seq}`,
    cuveeName: o.cuveeName ?? "Cuvée",
    canonicalName: o.canonicalName ?? `Wine ${seq}`,
    vintage: o.vintage ?? 2018,
    isNonVintage: o.isNonVintage ?? false,
    color: o.color ?? "red",
    alcoholPct: o.alcoholPct ?? 13,
    appellationName: o.appellationName ?? "AOC",
    countryCode: o.countryCode ?? "FR",
    region: o.region ?? "Bourgogne",
    subregion: o.subregion ?? null,
    level: o.level ?? "village",
    primaryVariety: o.primaryVariety ?? null,
    varieties: o.varieties ?? (o.primaryVariety ? [o.primaryVariety] : []),
    avgRating: o.avgRating ?? null,
    vintageScore: o.vintageScore ?? null,
    avgPriceEur: o.avgPriceEur ?? null,
    qty: o.qty ?? 3,
    locations: o.locations ?? [],
  };
}

const YEAR = 2026;

describe("estimateWeight", () => {
  it("ranks colors light → full", () => {
    const sparkling = estimateWeight({ color: "sparkling", alcoholPct: 12, primaryVariety: null });
    const white = estimateWeight({ color: "white", alcoholPct: 12, primaryVariety: null });
    const red = estimateWeight({ color: "red", alcoholPct: 12, primaryVariety: null });
    const fortified = estimateWeight({ color: "fortified", alcoholPct: 19, primaryVariety: null });
    expect(sparkling).toBeLessThan(white);
    expect(white).toBeLessThan(red);
    expect(red).toBeLessThan(fortified);
  });

  it("higher alcohol increases body", () => {
    const low = estimateWeight({ color: "red", alcoholPct: 11, primaryVariety: null });
    const high = estimateWeight({ color: "red", alcoholPct: 15, primaryVariety: null });
    expect(high).toBeGreaterThan(low);
  });

  it("grape shifts body (cabernet > pinot noir)", () => {
    const cab = estimateWeight({ color: "red", alcoholPct: 13, primaryVariety: "Cabernet Sauvignon" });
    const pinot = estimateWeight({ color: "red", alcoholPct: 13, primaryVariety: "Pinot Noir" });
    expect(cab).toBeGreaterThan(pinot);
  });

  it("stays within 0–100", () => {
    expect(estimateWeight({ color: "sparkling", alcoholPct: 6, primaryVariety: "Riesling" })).toBeGreaterThanOrEqual(0);
    expect(estimateWeight({ color: "fortified", alcoholPct: 22, primaryVariety: "Touriga" })).toBeLessThanOrEqual(100);
  });
});

describe("orderFlight — serving sequence", () => {
  it("sparkling first, fortified last, reds after whites", () => {
    const wines = [
      mk({ wineKey: "red", color: "red" }),
      mk({ wineKey: "fort", color: "fortified" }),
      mk({ wineKey: "spark", color: "sparkling" }),
      mk({ wineKey: "white", color: "white" }),
    ];
    const ordered = orderFlight(wines).map((w) => w.wineKey);
    expect(ordered[0]).toBe("spark");
    expect(ordered[ordered.length - 1]).toBe("fort");
    expect(ordered.indexOf("white")).toBeLessThan(ordered.indexOf("red"));
  });

  it("within a color, lighter before fuller", () => {
    const wines = [
      mk({ wineKey: "big", color: "red", primaryVariety: "Syrah", alcoholPct: 15 }),
      mk({ wineKey: "light", color: "red", primaryVariety: "Pinot Noir", alcoholPct: 12 }),
    ];
    const ordered = orderFlight(wines).map((w) => w.wineKey);
    expect(ordered).toEqual(["light", "big"]);
  });

  it("young before old on ties", () => {
    const wines = [
      mk({ wineKey: "old", color: "red", vintage: 2005, primaryVariety: "Merlot", alcoholPct: 13 }),
      mk({ wineKey: "young", color: "red", vintage: 2020, primaryVariety: "Merlot", alcoholPct: 13 }),
    ];
    const ordered = orderFlight(wines).map((w) => w.wineKey);
    expect(ordered).toEqual(["young", "old"]);
  });
});

describe("buildFlight — progressive", () => {
  const pool = [
    mk({ color: "sparkling", alcoholPct: 12 }),
    mk({ color: "white", alcoholPct: 12.5, primaryVariety: "Sauvignon Blanc" }),
    mk({ color: "white", alcoholPct: 14, primaryVariety: "Chardonnay" }),
    mk({ color: "red", alcoholPct: 12.5, primaryVariety: "Pinot Noir" }),
    mk({ color: "red", alcoholPct: 14.5, primaryVariety: "Syrah" }),
    mk({ color: "fortified", alcoholPct: 19 }),
    mk({ color: "rosé", alcoholPct: 12 }),
    mk({ color: "red", alcoholPct: 13.5, primaryVariety: "Merlot" }),
  ];

  it("returns the requested count, ordered, with directives", () => {
    const flight = buildFlight("progressive", pool, { count: 6, currentYear: YEAR });
    expect(flight.stops).toHaveLength(6);
    // Positions are 1..n in serving order.
    expect(flight.stops.map((s) => s.position)).toEqual([1, 2, 3, 4, 5, 6]);
    // Weight should be non-decreasing within the same serving rank — sanity: first lighter than last.
    expect(flight.stops[0].weight).toBeLessThan(flight.stops[flight.stops.length - 1].weight);
    expect(flight.overall.length).toBeGreaterThan(0);
  });

  it("honours locked and excluded wines", () => {
    const flight = buildFlight("progressive", pool, {
      count: 4,
      currentYear: YEAR,
      lockedWineKeys: [pool[5].wineKey], // fortified
      excludeWineKeys: [pool[0].wineKey], // sparkling
    });
    const keys = flight.stops.map((s) => s.wineKey);
    expect(keys).toContain(pool[5].wineKey);
    expect(keys).not.toContain(pool[0].wineKey);
    expect(flight.stops).toHaveLength(4);
  });
});

describe("buildFlight — theme modes", () => {
  it("vertical groups one producer/cuvée across vintages", () => {
    const pool = [
      mk({ wineKey: "a18", producerName: "Domaine X", cuveeName: "Clos", vintage: 2018 }),
      mk({ wineKey: "a19", producerName: "Domaine X", cuveeName: "Clos", vintage: 2019 }),
      mk({ wineKey: "a20", producerName: "Domaine X", cuveeName: "Clos", vintage: 2020 }),
      mk({ wineKey: "other", producerName: "Domaine Y", cuveeName: "Autre", vintage: 2019 }),
    ];
    const flight = buildFlight("vertical", pool, { count: 6, currentYear: YEAR });
    expect(flight.selectedAxis?.label).toContain("Domaine X");
    const keys = flight.stops.map((s) => s.wineKey).sort();
    expect(keys).toEqual(["a18", "a19", "a20"]);
  });

  it("horizontal groups one vintage across producers", () => {
    const pool = [
      mk({ wineKey: "p1", producerName: "P1", vintage: 2019 }),
      mk({ wineKey: "p2", producerName: "P2", vintage: 2019 }),
      mk({ wineKey: "p3", producerName: "P3", vintage: 2015 }),
    ];
    const flight = buildFlight("horizontal", pool, { count: 6, currentYear: YEAR });
    expect(flight.selectedAxis?.id).toBe("2019");
    expect(flight.stops).toHaveLength(2);
  });

  it("grape groups one variety across regions", () => {
    const pool = [
      mk({ wineKey: "g1", primaryVariety: "Chardonnay", color: "white", region: "Bourgogne" }),
      mk({ wineKey: "g2", primaryVariety: "Chardonnay", color: "white", region: "Champagne" }),
      mk({ wineKey: "g3", primaryVariety: "Merlot", color: "red", region: "Bordeaux" }),
    ];
    const flight = buildFlight("grape", pool, { count: 6, currentYear: YEAR });
    expect(flight.stops.map((s) => s.wineKey).sort()).toEqual(["g1", "g2"]);
  });

  it("returns an empty flight when no axis is feasible", () => {
    const pool = [mk({ wineKey: "solo", producerName: "Solo", cuveeName: "One", vintage: 2019 })];
    const flight = buildFlight("vertical", pool, { count: 6, currentYear: YEAR });
    expect(flight.stops).toHaveLength(0);
    expect(flight.availableAxes).toHaveLength(0);
  });
});

describe("buildFlight — drink_now", () => {
  it("prioritises older bottles and last bottles", () => {
    const pool = [
      mk({ wineKey: "fresh", vintage: 2023, qty: 6 }),
      mk({ wineKey: "old", vintage: 2008, qty: 3 }),
      mk({ wineKey: "lastold", vintage: 2010, qty: 1 }),
    ];
    const flight = buildFlight("drink_now", pool, { count: 2, currentYear: YEAR });
    const keys = flight.stops.map((s) => s.wineKey);
    expect(keys).not.toContain("fresh");
    expect(keys).toContain("old");
    expect(keys).toContain("lastold");
  });
});

describe("modeFeasibility", () => {
  it("progressive feasible with ≥2 wines", () => {
    expect(modeFeasibility("progressive", [mk(), mk()]).feasible).toBe(true);
    expect(modeFeasibility("progressive", [mk()]).feasible).toBe(false);
  });

  it("vertical needs a producer with ≥2 vintages", () => {
    const noVertical = [mk({ producerName: "A", vintage: 2019 }), mk({ producerName: "B", vintage: 2019 })];
    expect(modeFeasibility("vertical", noVertical).feasible).toBe(false);
    const yesVertical = [
      mk({ producerName: "A", cuveeName: "C", vintage: 2019 }),
      mk({ producerName: "A", cuveeName: "C", vintage: 2020 }),
    ];
    expect(modeFeasibility("vertical", yesVertical).feasible).toBe(true);
  });
});
