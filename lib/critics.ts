/**
 * Critic registry — single source of truth for how critic_code values are
 * displayed and ordered in the UI.
 *
 * Codes are the canonical DB values (see CANONICAL_CRITIC_CODES in
 * lib/quality/gates.ts). `label` is the short badge shown to the user; `name`
 * is the full critic/publication name. These are brand proper nouns and are
 * deliberately NOT translated (same rule as dim_wine.canonical_name).
 *
 * `official` marks Nicolas' curated primary-tier critics. Official critics sort
 * first everywhere; all other critics stay ingested and displayed as secondary.
 */

export interface CriticMeta {
  /** Short badge label (e.g. "RP"). */
  label: string;
  /** Full critic / publication name (e.g. "Parker"). */
  name: string;
  /** Primary-tier critic curated by Nicolas. */
  official: boolean;
}

/** The six primary-tier critics, in display order. */
export const OFFICIAL_CRITIC_CODES = [
  "WA", // Parker / Wine Advocate
  "Vinous",
  "JD", // Jeb Dunnuck
  "JMIB", // Jasper Morris
  "RVF", // Les Vins de France
  "Hachette",
] as const;

export const CRITIC_REGISTRY: Record<string, CriticMeta> = {
  // ── Official (primary tier) ──
  WA: { label: "RP", name: "Parker", official: true },
  Vinous: { label: "VN", name: "Vinous", official: true },
  JD: { label: "JD", name: "Jeb Dunnuck", official: true },
  JMIB: { label: "JM", name: "Jasper Morris", official: true },
  RVF: { label: "LVF", name: "Les Vins de France", official: true },
  Hachette: { label: "Hachette", name: "Guide Hachette", official: true },

  // ── Secondary critics ──
  BH: { label: "BH", name: "Burghound", official: false },
  Decanter: { label: "Decanter", name: "Decanter", official: false },
  JS: { label: "JS", name: "James Suckling", official: false },
  JG: { label: "JG", name: "John Gilman", official: false },
  WS: { label: "WS", name: "Wine Spectator", official: false },
  WE: { label: "WE", name: "Wine Enthusiast", official: false },
  WAL: { label: "WAL", name: "WineAlign", official: false },
  WD: { label: "WD", name: "The Wine Doctor", official: false },
  GV: { label: "G&G", name: "Gilbert & Gaillard", official: false },
  Halliday: { label: "JH", name: "Halliday", official: false },

  // ── User aggregates ──
  CT: { label: "CT", name: "CellarTracker", official: false },
  VI: { label: "VI", name: "Vivino", official: false },
  XW: { label: "XW", name: "X-Wines", official: false },
  SM: { label: "SM", name: "soMLier", official: false },
};

/** Full display order: official critics first (in OFFICIAL_CRITIC_CODES order), then the rest. */
export const CRITIC_DISPLAY_ORDER: string[] = [
  ...OFFICIAL_CRITIC_CODES,
  ...Object.keys(CRITIC_REGISTRY).filter(
    (code) => !CRITIC_REGISTRY[code].official,
  ),
];

const ORDER_INDEX = new Map(CRITIC_DISPLAY_ORDER.map((code, i) => [code, i]));

/** Short badge label for a critic code; falls back to the raw code. */
export function criticLabel(code: string): string {
  return CRITIC_REGISTRY[code]?.label ?? code;
}

/** Full critic name for a critic code; falls back to the raw code. */
export function criticName(code: string): string {
  return CRITIC_REGISTRY[code]?.name ?? code;
}

export function isOfficialCritic(code: string): boolean {
  return CRITIC_REGISTRY[code]?.official ?? false;
}

/** Sort comparator: official critics first, then registry order, unknown codes last. */
export function compareCriticCodes(a: string, b: string): number {
  const ia = ORDER_INDEX.get(a) ?? Number.MAX_SAFE_INTEGER;
  const ib = ORDER_INDEX.get(b) ?? Number.MAX_SAFE_INTEGER;
  if (ia !== ib) return ia - ib;
  return a.localeCompare(b);
}
