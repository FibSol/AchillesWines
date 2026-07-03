/**
 * Wine-tasting flight engine. Owned by Helena (BA) / Hector (architect).
 *
 * Pure, DB-free logic so it is unit-testable and reusable. Given a pool of
 * in-stock cellar wines, it can:
 *   1. estimate a body/weight score per wine (light → full),
 *   2. select a 6-wine flight by one of several sommelier "logics" (modes),
 *   3. order the flight into the correct serving sequence,
 *   4. emit structured, i18n-ready directives for each wine and the flight.
 *
 * Sensory attributes (body, tannin, acidity, drinking window) are NOT stored in
 * the schema, so weight is inferred from color + alcohol + grape. It is an
 * estimate — the serving-order rule mostly depends on exactly these signals.
 *
 * Sources for the ordering rule and flight logics:
 *   - lightest→fullest, dry→sweet, sparkling first, dessert last (ABC Fine Wine,
 *     Vinesse), max ~6 wines per flight.
 *   - vertical / horizontal / regional / grape themes (Wine Spectator, Wine Folly).
 */

import type { WineColor } from "@/lib/pairing";

export type AppellationLevel =
  | "regional"
  | "village"
  | "premier_cru"
  | "grand_cru"
  | "iconic";

export type TastingMode =
  | "progressive"
  | "vertical"
  | "horizontal"
  | "regional"
  | "grape"
  | "drink_now";

export const TASTING_MODES: TastingMode[] = [
  "progressive",
  "vertical",
  "horizontal",
  "regional",
  "grape",
  "drink_now",
];

/** A cellar storage location holding some bottles of a wine. */
export interface WineLocation {
  locationId: number;
  name: string;
  qty: number;
}

/** A single in-stock candidate wine, enriched with everything the engine needs. */
export interface TastingCandidate {
  wineKey: string;
  producerName: string;
  cuveeName: string;
  canonicalName: string;
  vintage: number | null;
  isNonVintage: boolean;
  color: WineColor;
  alcoholPct: number | null;
  appellationName: string;
  countryCode: string;
  region: string;
  subregion: string | null;
  level: AppellationLevel;
  primaryVariety: string | null;
  /** Full grape blend, ordered by share (descending). */
  varieties: string[];
  avgRating: number | null;
  /** Vintage-chart score for this wine's region × vintage × color (/100). */
  vintageScore: number | null;
  avgPriceEur: number | null;
  qty: number;
  /** Cellar locations holding this wine (ordered by location id). */
  locations: WineLocation[];
}

/** Structured, translatable note: the client renders t(`tasting.notes.${key}`, params). */
export interface DirectiveNote {
  key: string;
  params?: Record<string, string | number>;
}

export type GlassType = "flute" | "white" | "red" | "universal";

/** One ordered stop in the flight, with display data and structured directives. */
export interface FlightStop {
  position: number;
  wineKey: string;
  producerName: string;
  cuveeName: string;
  canonicalName: string;
  vintage: number | null;
  color: WineColor;
  appellationName: string;
  region: string;
  level: AppellationLevel;
  primaryVariety: string | null;
  /** Full grape blend, ordered by share (descending). */
  grapes: string[];
  alcoholPct: number | null;
  avgRating: number | null;
  vintageScore: number | null;
  avgPriceEur: number | null;
  qty: number;
  weight: number;
  serveTempC: [number, number];
  decantMinutes: number;
  glassType: GlassType;
  /** Cellar locations holding this wine (ordered by location id). */
  locations: WineLocation[];
  notes: DirectiveNote[];
}

export interface TastingAxis {
  /** Stable id used to re-request this axis (e.g. producer name, vintage, region, grape). */
  id: string;
  label: string;
  /** How many candidate wines this axis would yield. */
  count: number;
}

export interface TastingFlight {
  mode: TastingMode;
  selectedAxis: TastingAxis | null;
  availableAxes: TastingAxis[];
  stops: FlightStop[];
  overall: DirectiveNote[];
  poolSize: number;
}

export interface SelectOptions {
  /** Target number of wines (clamped 2–8, default 6). */
  count?: number;
  /** Wines that must appear in the flight (the user "locked" them). */
  lockedWineKeys?: string[];
  /** Wines that must never be picked (the user removed them). */
  excludeWineKeys?: string[];
  /** For theme modes: the axis id to build around. If absent, the richest axis is chosen. */
  axisId?: string;
  /** Reference year for age / drink-now reasoning (defaults to a fixed value in tests). */
  currentYear: number;
}

/* ============================================================================
 * WEIGHT / BODY ESTIMATION
 * ========================================================================== */

const COLOR_BASE_WEIGHT: Record<WineColor, number> = {
  sparkling: 18,
  white: 28,
  orange: 46,
  rosé: 32,
  red: 60,
  sweet: 70,
  fortified: 86,
};

/** Grape → body delta. Keyed on lowercased, accent-stripped variety names. */
const GRAPE_WEIGHT_DELTA: Array<{ test: RegExp; delta: number }> = [
  // Full-bodied reds
  { test: /cabernet sauvignon|syrah|shiraz|nebbiolo|malbec|tannat|mourv|petit verdot|petite sirah|zinfandel|aglianico|touriga/, delta: 14 },
  // Medium reds
  { test: /merlot|grenache|garnacha|sangiovese|tempranillo|cabernet franc|carmen|montepulciano|nero d|primitivo/, delta: 6 },
  // Light reds
  { test: /pinot noir|gamay|cinsault|poulsard|trousseau|schiava|frappato|zweigelt/, delta: -12 },
  // Rich / oaked whites
  { test: /chardonnay|viognier|roussanne|marsanne|s(e|é)millon|pinot gris/, delta: 10 },
  // Crisp / aromatic whites
  { test: /riesling|sauvignon|muscadet|melon|aligot(e|é)|gr(u|ü)ner|albari|verdejo|assyrtiko|picpoul|vermentino/, delta: -8 },
];

/**
 * Estimate body on a 0–100 light→full scale from color + alcohol + grape.
 * Deterministic and pure.
 */
export function estimateWeight(c: Pick<TastingCandidate, "color" | "alcoholPct" | "primaryVariety">): number {
  let w = COLOR_BASE_WEIGHT[c.color] ?? 50;

  if (c.alcoholPct !== null && c.alcoholPct > 0) {
    // Each point of alcohol away from 12.5% nudges body by ~4, capped ±16.
    w += clamp((c.alcoholPct - 12.5) * 4, -16, 16);
  }

  if (c.primaryVariety) {
    const v = stripAccents(c.primaryVariety.toLowerCase());
    for (const { test, delta } of GRAPE_WEIGHT_DELTA) {
      if (test.test(v)) {
        w += delta;
        break;
      }
    }
  }

  return Math.round(clamp(w, 0, 100));
}

/* ============================================================================
 * SERVING ORDER
 * ========================================================================== */

/** Coarse rank: sparkling first, then whites/orange/rosé, reds, then sweet/fortified last. */
const COLOR_SERVE_RANK: Record<WineColor, number> = {
  sparkling: 0,
  white: 1,
  orange: 2,
  rosé: 2,
  red: 3,
  sweet: 4,
  fortified: 5,
};

/**
 * Order wines into the canonical serving sequence:
 * sparkling → light → full, dry → sweet, young → old within ties.
 */
export function orderFlight(wines: TastingCandidate[]): TastingCandidate[] {
  return [...wines].sort((a, b) => {
    const ra = COLOR_SERVE_RANK[a.color] ?? 3;
    const rb = COLOR_SERVE_RANK[b.color] ?? 3;
    if (ra !== rb) return ra - rb;
    const wa = estimateWeight(a);
    const wb = estimateWeight(b);
    if (wa !== wb) return wa - wb;
    // Young before old: newer vintage first. NV (null) treated as youngest.
    const va = a.vintage ?? 9999;
    const vb = b.vintage ?? 9999;
    if (va !== vb) return vb - va;
    return a.canonicalName.localeCompare(b.canonicalName);
  });
}

/* ============================================================================
 * SELECTION STRATEGIES
 * ========================================================================== */

const DEFAULT_RATING = 80;

/** Desirability used to break ties when several wines fit the same slot. */
function desirability(c: TastingCandidate): number {
  const rating = c.avgRating ?? DEFAULT_RATING;
  const vintageBonus = c.vintageScore !== null ? (c.vintageScore - 80) * 0.2 : 0;
  return rating + vintageBonus;
}

function applyCount(count: number | undefined): number {
  return clamp(Math.round(count ?? 6), 2, 8);
}

function partitionPool(pool: TastingCandidate[], locked: Set<string>, excluded: Set<string>) {
  const lockedWines = pool.filter((c) => locked.has(c.wineKey));
  const free = pool.filter((c) => !locked.has(c.wineKey) && !excluded.has(c.wineKey));
  return { lockedWines, free };
}

/**
 * PROGRESSIVE — a balanced flight spanning the light→full spectrum with color
 * variety. Splits the pool into `count` weight buckets and takes the most
 * desirable wine from each, avoiding repeated producers where possible.
 */
function selectProgressive(pool: TastingCandidate[], opts: SelectOptions): TastingCandidate[] {
  const count = applyCount(opts.count);
  const locked = new Set(opts.lockedWineKeys ?? []);
  const excluded = new Set(opts.excludeWineKeys ?? []);
  const { lockedWines, free } = partitionPool(pool, locked, excluded);

  const slots = count - lockedWines.length;
  if (slots <= 0) return lockedWines.slice(0, count);

  const byWeight = [...free].sort((a, b) => estimateWeight(a) - estimateWeight(b));
  if (byWeight.length === 0) return lockedWines;

  const chosen: TastingCandidate[] = [];
  const usedProducers = new Set(lockedWines.map((w) => w.producerName));
  const n = byWeight.length;

  for (let i = 0; i < slots; i++) {
    const start = Math.floor((i * n) / slots);
    const end = Math.max(start + 1, Math.floor(((i + 1) * n) / slots));
    const bucket = byWeight
      .slice(start, end)
      .filter((c) => !chosen.includes(c));
    if (bucket.length === 0) continue;
    // Prefer a new producer; fall back to most desirable.
    const fresh = bucket.filter((c) => !usedProducers.has(c.producerName));
    const pickFrom = fresh.length > 0 ? fresh : bucket;
    const pick = pickFrom.reduce((best, c) => (desirability(c) > desirability(best) ? c : best));
    chosen.push(pick);
    usedProducers.add(pick.producerName);
  }

  // Top up if buckets collapsed (small pools).
  if (chosen.length < slots) {
    for (const c of byWeight) {
      if (chosen.length >= slots) break;
      if (!chosen.includes(c)) chosen.push(c);
    }
  }

  return [...lockedWines, ...chosen];
}

/**
 * DRINK_NOW — cellar management. Prioritises older bottles, last bottles
 * (qty 1) and weaker-vintage wines so they get drunk before they fade.
 */
function selectDrinkNow(pool: TastingCandidate[], opts: SelectOptions): TastingCandidate[] {
  const count = applyCount(opts.count);
  const locked = new Set(opts.lockedWineKeys ?? []);
  const excluded = new Set(opts.excludeWineKeys ?? []);
  const { lockedWines, free } = partitionPool(pool, locked, excluded);
  const slots = count - lockedWines.length;
  if (slots <= 0) return lockedWines.slice(0, count);

  const urgency = (c: TastingCandidate): number => {
    const age = c.vintage !== null ? Math.max(0, opts.currentYear - c.vintage) : 0;
    let u = age * 3;
    if (c.qty === 1) u += 18; // last bottle — drink before it is forgotten
    if (c.vintageScore !== null && c.vintageScore < 85) u += (85 - c.vintageScore) * 0.6;
    return u;
  };

  const ranked = [...free].sort((a, b) => urgency(b) - urgency(a));
  const chosen: TastingCandidate[] = [];
  const usedProducers = new Set(lockedWines.map((w) => w.producerName));
  // First pass: enforce producer diversity.
  for (const c of ranked) {
    if (chosen.length >= slots) break;
    if (usedProducers.has(c.producerName)) continue;
    chosen.push(c);
    usedProducers.add(c.producerName);
  }
  // Second pass: fill remaining slots if diversity left us short.
  for (const c of ranked) {
    if (chosen.length >= slots) break;
    if (!chosen.includes(c)) chosen.push(c);
  }

  return [...lockedWines, ...chosen];
}

/* ---- Theme modes (axis-based): vertical / horizontal / regional / grape ---- */

function verticalAxisKey(c: TastingCandidate): string {
  return `${c.producerName} — ${c.cuveeName}`.trim();
}

/** Build available axes for a theme mode and group wines under each. */
function buildAxes(
  pool: TastingCandidate[],
  keyOf: (c: TastingCandidate) => string | null,
  labelOf: (c: TastingCandidate) => string,
  minWines: number,
): { axes: TastingAxis[]; groups: Map<string, TastingCandidate[]> } {
  const groups = new Map<string, TastingCandidate[]>();
  const labels = new Map<string, string>();
  for (const c of pool) {
    const k = keyOf(c);
    if (k === null) continue;
    if (!groups.has(k)) {
      groups.set(k, []);
      labels.set(k, labelOf(c));
    }
    groups.get(k)!.push(c);
  }
  const axes: TastingAxis[] = [];
  for (const [id, wines] of groups) {
    if (wines.length >= minWines) {
      axes.push({ id, label: labels.get(id) ?? id, count: wines.length });
    }
  }
  axes.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  return { axes, groups };
}

interface ThemeConfig {
  keyOf: (c: TastingCandidate) => string | null;
  labelOf: (c: TastingCandidate) => string;
  minWines: number;
  /** How to rank wines within the chosen axis before slicing to `count`. */
  rankWithin: (wines: TastingCandidate[], opts: SelectOptions) => TastingCandidate[];
}

function distinctVintages(wines: TastingCandidate[]): number {
  return new Set(wines.map((w) => w.vintage)).size;
}
function distinctProducers(wines: TastingCandidate[]): number {
  return new Set(wines.map((w) => w.producerName)).size;
}

const THEME_CONFIG: Record<"vertical" | "horizontal" | "regional" | "grape", ThemeConfig> = {
  // Same producer+cuvée across ≥2 vintages.
  vertical: {
    keyOf: (c) => (c.vintage !== null ? verticalAxisKey(c) : null),
    labelOf: (c) => verticalAxisKey(c),
    minWines: 2,
    rankWithin: (wines) =>
      [...wines].sort((a, b) => (b.vintage ?? 0) - (a.vintage ?? 0)), // newest first
  },
  // Same vintage across ≥2 producers.
  horizontal: {
    keyOf: (c) => (c.vintage !== null ? String(c.vintage) : null),
    labelOf: (c) => String(c.vintage),
    minWines: 2,
    rankWithin: (wines) => {
      // Prefer producer diversity, then desirability.
      const seen = new Set<string>();
      const primary: TastingCandidate[] = [];
      const rest: TastingCandidate[] = [];
      for (const w of [...wines].sort((a, b) => desirability(b) - desirability(a))) {
        if (seen.has(w.producerName)) rest.push(w);
        else {
          primary.push(w);
          seen.add(w.producerName);
        }
      }
      return [...primary, ...rest];
    },
  },
  // Same region, climbing the appellation ladder.
  regional: {
    keyOf: (c) => `${c.countryCode}:${c.region}`,
    labelOf: (c) => c.region,
    minWines: 2,
    rankWithin: (wines) => {
      const levelRank: Record<AppellationLevel, number> = {
        regional: 0,
        village: 1,
        premier_cru: 2,
        grand_cru: 3,
        iconic: 4,
      };
      // Spread across levels: one per level by desirability, then fill.
      const byLevel = new Map<AppellationLevel, TastingCandidate[]>();
      for (const w of wines) {
        if (!byLevel.has(w.level)) byLevel.set(w.level, []);
        byLevel.get(w.level)!.push(w);
      }
      const spread: TastingCandidate[] = [];
      const levels = [...byLevel.keys()].sort((a, b) => levelRank[a] - levelRank[b]);
      for (const lvl of levels) {
        const best = byLevel.get(lvl)!.reduce((x, y) => (desirability(y) > desirability(x) ? y : x));
        spread.push(best);
      }
      const rest = wines
        .filter((w) => !spread.includes(w))
        .sort((a, b) => desirability(b) - desirability(a));
      return [...spread, ...rest];
    },
  },
  // Same grape across regions/styles.
  grape: {
    keyOf: (c) => (c.primaryVariety ? stripAccents(c.primaryVariety.toLowerCase()) : null),
    labelOf: (c) => c.primaryVariety ?? "",
    minWines: 2,
    rankWithin: (wines) => {
      // Prefer region diversity, then desirability.
      const seen = new Set<string>();
      const primary: TastingCandidate[] = [];
      const rest: TastingCandidate[] = [];
      for (const w of [...wines].sort((a, b) => desirability(b) - desirability(a))) {
        if (seen.has(w.region)) rest.push(w);
        else {
          primary.push(w);
          seen.add(w.region);
        }
      }
      return [...primary, ...rest];
    },
  },
};

function selectTheme(
  mode: "vertical" | "horizontal" | "regional" | "grape",
  pool: TastingCandidate[],
  opts: SelectOptions,
): { wines: TastingCandidate[]; selectedAxis: TastingAxis | null; availableAxes: TastingAxis[] } {
  const count = applyCount(opts.count);
  const excluded = new Set(opts.excludeWineKeys ?? []);
  const usablePool = pool.filter((c) => !excluded.has(c.wineKey));
  const cfg = THEME_CONFIG[mode];
  const { axes, groups } = buildAxes(usablePool, cfg.keyOf, cfg.labelOf, cfg.minWines);

  if (axes.length === 0) {
    return { wines: [], selectedAxis: null, availableAxes: [] };
  }

  const selectedAxis =
    (opts.axisId && axes.find((a) => a.id === opts.axisId)) || axes[0];
  const wines = cfg.rankWithin(groups.get(selectedAxis.id) ?? [], opts).slice(0, count);
  return { wines, selectedAxis, availableAxes: axes };
}

/* ============================================================================
 * DIRECTIVES
 * ========================================================================== */

function serveTemp(color: WineColor, weight: number): [number, number] {
  switch (color) {
    case "sparkling":
      return [6, 8];
    case "white":
      return weight > 40 ? [10, 12] : [8, 10];
    case "rosé":
      return [8, 10];
    case "orange":
      return [10, 12];
    case "sweet":
      return [7, 10];
    case "fortified":
      return [12, 16];
    case "red":
    default:
      return weight > 70 ? [16, 18] : [14, 16];
  }
}

function decantMinutes(c: TastingCandidate, weight: number, currentYear: number): number {
  if (c.color !== "red") return 0;
  const age = c.vintage !== null ? currentYear - c.vintage : 0;
  if (weight >= 70 && age < 8) return 60; // young & powerful — needs air
  if (weight >= 55 && age < 5) return 45;
  if (age >= 20) return 30; // old wine: short decant off any sediment
  return weight >= 60 ? 30 : 0;
}

function glassFor(color: WineColor): GlassType {
  if (color === "sparkling") return "flute";
  if (color === "white" || color === "rosé" || color === "sweet") return "white";
  if (color === "red") return "red";
  return "universal";
}

function lookForKey(color: WineColor): string {
  switch (color) {
    case "sparkling":
      return "lookForSparkling";
    case "white":
      return "lookForWhite";
    case "rosé":
      return "lookForRose";
    case "orange":
      return "lookForOrange";
    case "sweet":
      return "lookForSweet";
    case "fortified":
      return "lookForFortified";
    case "red":
    default:
      return "lookForRed";
  }
}

function buildStop(
  c: TastingCandidate,
  position: number,
  total: number,
  currentYear: number,
): FlightStop {
  const weight = estimateWeight(c);
  const temp = serveTemp(c.color, weight);
  const decant = decantMinutes(c, weight, currentYear);
  const notes: DirectiveNote[] = [];

  // Position note.
  if (position === 1) notes.push({ key: "positionFirst" });
  else if (position === total) notes.push({ key: "positionLast" });

  // What to look for (color-specific). Serving temp / decant / glass are
  // surfaced as quick facts on the card, not repeated as prose here.
  notes.push({ key: lookForKey(c.color) });

  // Quality / vintage signals.
  if (c.avgRating !== null && c.avgRating >= 92) {
    notes.push({ key: "criticAcclaim", params: { score: Math.round(c.avgRating) } });
  }
  if (c.vintageScore !== null && c.vintageScore >= 92) {
    notes.push({ key: "greatVintage", params: { score: Math.round(c.vintageScore) } });
  }

  // Age / cellar signals.
  const age = c.vintage !== null ? currentYear - c.vintage : null;
  if (age !== null && age >= 15) notes.push({ key: "agedBottle", params: { years: age } });
  if (c.qty === 1) notes.push({ key: "lastBottle" });

  return {
    position,
    wineKey: c.wineKey,
    producerName: c.producerName,
    cuveeName: c.cuveeName,
    canonicalName: c.canonicalName,
    vintage: c.vintage,
    color: c.color,
    appellationName: c.appellationName,
    region: c.region,
    level: c.level,
    primaryVariety: c.primaryVariety,
    grapes: c.varieties,
    alcoholPct: c.alcoholPct,
    avgRating: c.avgRating,
    vintageScore: c.vintageScore,
    avgPriceEur: c.avgPriceEur,
    qty: c.qty,
    locations: c.locations,
    weight,
    serveTempC: temp,
    decantMinutes: decant,
    glassType: glassFor(c.color),
    notes,
  };
}

function overallNotes(
  mode: TastingMode,
  ordered: TastingCandidate[],
  selectedAxis: TastingAxis | null,
): DirectiveNote[] {
  const out: DirectiveNote[] = [];
  out.push({ key: "count", params: { n: ordered.length } });

  // Theme line.
  switch (mode) {
    case "progressive":
      out.push({ key: "themeProgressive" });
      break;
    case "vertical":
      out.push({ key: "themeVertical", params: { axis: selectedAxis?.label ?? "" } });
      break;
    case "horizontal":
      out.push({ key: "themeHorizontal", params: { axis: selectedAxis?.label ?? "" } });
      break;
    case "regional":
      out.push({ key: "themeRegional", params: { axis: selectedAxis?.label ?? "" } });
      break;
    case "grape":
      out.push({ key: "themeGrape", params: { axis: selectedAxis?.label ?? "" } });
      break;
    case "drink_now":
      out.push({ key: "themeDrinkNow" });
      break;
  }

  out.push({ key: "serveOrder" });
  out.push({ key: "water" });

  // Palate break when the flight crosses from white-family to reds.
  const hasWhiteFamily = ordered.some((w) => COLOR_SERVE_RANK[w.color] <= 2);
  const hasRed = ordered.some((w) => w.color === "red");
  if (hasWhiteFamily && hasRed) out.push({ key: "palateBreak" });

  out.push({ key: "glasses" });
  return out;
}

/* ============================================================================
 * PUBLIC ENTRY POINT
 * ========================================================================== */

/** Whether a mode can produce a flight from the given pool, and how many axes/wines. */
export function modeFeasibility(
  mode: TastingMode,
  pool: TastingCandidate[],
): { feasible: boolean; axesCount: number; wineCount: number } {
  if (mode === "progressive" || mode === "drink_now") {
    return { feasible: pool.length >= 2, axesCount: 0, wineCount: pool.length };
  }
  const cfg = THEME_CONFIG[mode];
  const { axes } = buildAxes(pool, cfg.keyOf, cfg.labelOf, cfg.minWines);
  const wineCount = axes.reduce((a, x) => a + x.count, 0);
  return { feasible: axes.length > 0, axesCount: axes.length, wineCount };
}

/** Build a complete, ordered flight with directives for the given mode. */
export function buildFlight(
  mode: TastingMode,
  pool: TastingCandidate[],
  opts: SelectOptions,
): TastingFlight {
  let selected: TastingCandidate[];
  let selectedAxis: TastingAxis | null = null;
  let availableAxes: TastingAxis[] = [];

  if (mode === "progressive") {
    selected = selectProgressive(pool, opts);
  } else if (mode === "drink_now") {
    selected = selectDrinkNow(pool, opts);
  } else {
    const theme = selectTheme(mode, pool, opts);
    // Locked wines are honoured even in theme modes (user pinned them).
    const locked = new Set(opts.lockedWineKeys ?? []);
    const lockedWines = pool.filter((c) => locked.has(c.wineKey));
    const merged = [...lockedWines];
    for (const w of theme.wines) {
      if (!merged.some((m) => m.wineKey === w.wineKey)) merged.push(w);
    }
    selected = merged.slice(0, applyCount(opts.count));
    selectedAxis = theme.selectedAxis;
    availableAxes = theme.availableAxes;
  }

  const ordered = orderFlight(dedupe(selected));
  const stops = ordered.map((c, i) => buildStop(c, i + 1, ordered.length, opts.currentYear));
  const overall = overallNotes(mode, ordered, selectedAxis);

  return {
    mode,
    selectedAxis,
    availableAxes,
    stops,
    overall,
    poolSize: pool.length,
  };
}

/* ============================================================================
 * UTILITIES
 * ========================================================================== */

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}

const COMBINING_MARKS = new RegExp("[\\u0300-\\u036f]", "g");
function stripAccents(s: string): string {
  return s.normalize("NFD").replace(COMBINING_MARKS, "");
}

function dedupe(wines: TastingCandidate[]): TastingCandidate[] {
  const seen = new Set<string>();
  const out: TastingCandidate[] = [];
  for (const w of wines) {
    if (seen.has(w.wineKey)) continue;
    seen.add(w.wineKey);
    out.push(w);
  }
  return out;
}
