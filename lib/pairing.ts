/**
 * Wine-pairing heuristics. Owned by Helena (BA) — Sprint 6.
 *
 * v1 keyword-driven matcher: maps dish text → preferred wine colors with weights.
 * Replaceable by a richer ML model later. The scoring formula is intentionally
 * transparent so users understand why a pairing was suggested.
 */

export type CourseType =
  | "aperitif"
  | "entree"
  | "plat"
  | "fromage"
  | "dessert"
  | "other";

export type WineColor =
  | "red"
  | "white"
  | "rosé"
  | "sparkling"
  | "sweet"
  | "fortified"
  | "orange";

/** Color → score map by course default. Tuned by hand. */
const COURSE_COLOR_DEFAULTS: Record<CourseType, Partial<Record<WineColor, number>>> = {
  aperitif: { sparkling: 100, white: 75, rosé: 60, fortified: 50, orange: 40 },
  entree: { white: 90, rosé: 75, sparkling: 65, red: 40, orange: 50 },
  plat: { red: 80, white: 65, rosé: 45, sparkling: 25 },
  fromage: { red: 85, white: 70, fortified: 75, sweet: 60, orange: 50 },
  dessert: { sweet: 100, fortified: 85, sparkling: 65, white: 40 },
  other: { red: 60, white: 60, rosé: 50, sparkling: 50, sweet: 40, fortified: 40, orange: 40 },
};

/** Dish keyword → boost to a wine color, additive on top of course default. */
const DISH_KEYWORD_BOOSTS: Array<{
  pattern: RegExp;
  boosts: Partial<Record<WineColor, number>>;
}> = [
  // Red meat → red boost
  {
    pattern:
      /\b(b(oe|œ|o)uf|agneaux?|gibier|sangliers?|chevreuils?|cerfs?|canards?|magrets?|cassoulet|tartare|steaks?|c(o|ô)telettes?|gigots?)\b/i,
    boosts: { red: 35 },
  },
  // Truffle / mushroom → red boost
  {
    pattern: /\b(truffes?|champignons?|c(e|è)pes?|morilles?|girolles?)\b/i,
    boosts: { red: 25, white: 10 },
  },
  // Fish / shellfish → white boost
  {
    pattern:
      /\b(poissons?|saumons?|thons?|bar|dorades?|cabillauds?|soles?|sardines?|hu(i|î)tres?|crevettes?|moules?|coquilles?|saint-jacques|homards?|langoustes?|crabes?|lottes?)\b/i,
    boosts: { white: 40, sparkling: 15, rosé: 10 },
  },
  // Poultry / pork
  {
    pattern: /\b(volaille|poulet|dinde|pintade|porc|veau|escalope|jambon)\b/i,
    boosts: { white: 20, red: 25, rosé: 10 },
  },
  // Vegetarian / salad
  {
    pattern:
      /\b(salade|l(e|é)gume|tomate|aubergine|courgette|asperge|risotto|p(â|a)tes|pasta|v(e|é)g(e|é)tarien)\b/i,
    boosts: { white: 25, rosé: 25, orange: 15 },
  },
  // Cheese types
  {
    pattern: /\b(roquefort|bleu|stilton|gorgonzola)\b/i,
    boosts: { sweet: 50, fortified: 35 },
  },
  {
    pattern: /\b(camembert|brie|munster|reblochon|crottin|comt(e|é)|gruy(e|è)re)\b/i,
    boosts: { white: 25, red: 20 },
  },
  // Dessert flavors
  {
    pattern: /\b(chocolat|moelleux|fondant|brownie)\b/i,
    boosts: { fortified: 40, sweet: 30 },
  },
  {
    pattern: /\b(fruits?|tarte|cl(a|à)foutis|cr(e|é)pe|pomme|poire|p(ê|e)che|fraise|abricot)\b/i,
    boosts: { sweet: 50, sparkling: 25 },
  },
  // Spicy / Asian
  {
    pattern: /\b(curry|piment|(é|e)pic(é|e)|tha(i|ï)|indien|asiatique|sushi|tempura)\b/i,
    boosts: { white: 30, rosé: 20, sparkling: 25 },
  },
];

export interface ScoreInputs {
  course: CourseType;
  dishText: string;
  wineColor: WineColor;
  ratingNorm100: number | null;
  inventoryQty: number;
  pricePerGuestEur: number | null;
  budgetPerGuestEur: number | null;
}

export interface ScoreBreakdown {
  total: number;
  colorMatch: number;
  inventoryBonus: number;
  ratingScore: number;
  budgetPenalty: number;
}

/**
 * Pure scoring function. Higher is better. Breakdown returned so the UI can
 * show *why* a wine was picked.
 *
 * - colorMatch (0–135): course default + dish-keyword boosts for that color.
 * - inventoryBonus (0–30): bottle-in-cellar bonus, saturating around 6 bottles.
 * - ratingScore (0–30): critic rating /100 mapped linearly into 0–30.
 * - budgetPenalty (≤ 0): if pricePerGuest exceeds budget, subtract proportionally.
 */
export function scorePairing(input: ScoreInputs): ScoreBreakdown {
  const courseDefaults = COURSE_COLOR_DEFAULTS[input.course] ?? {};
  let colorMatch = courseDefaults[input.wineColor] ?? 0;

  const dish = input.dishText.toLowerCase();
  for (const { pattern, boosts } of DISH_KEYWORD_BOOSTS) {
    if (pattern.test(dish)) {
      const boost = boosts[input.wineColor];
      if (boost) colorMatch += boost;
    }
  }

  const inventoryBonus =
    input.inventoryQty > 0 ? Math.min(30, 10 + Math.log(input.inventoryQty + 1) * 8) : 0;

  const ratingScore = input.ratingNorm100 !== null ? Math.max(0, (input.ratingNorm100 - 70) * 1) : 0;

  let budgetPenalty = 0;
  if (
    input.budgetPerGuestEur !== null &&
    input.pricePerGuestEur !== null &&
    input.pricePerGuestEur > input.budgetPerGuestEur
  ) {
    const over = input.pricePerGuestEur - input.budgetPerGuestEur;
    budgetPenalty = -Math.min(40, (over / input.budgetPerGuestEur) * 30);
  }

  const total = colorMatch + inventoryBonus + ratingScore + budgetPenalty;
  return { total, colorMatch, inventoryBonus, ratingScore, budgetPenalty };
}
