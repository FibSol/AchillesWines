/**
 * Identity normalization helpers.
 * Owner: Patroclus (Backend) · Validated by: Cassandra (QA)
 *
 * THE BACKBONE OF ANTI-HALLUCINATION:
 *  - normText() strips diacritics and punctuation
 *  - expandProducerPrefix() expands "D." → "Domaine", "Ch." → "Château"
 *  - cleanCuveeTails() strips classification tails ("Grand Cru Classé") and vintages
 *  - computeWineKey() produces a 16-char sha1 prefix for canonical dedup
 *
 * Mirror these in scrapers/achilles_scraper/identity.py (must produce identical output).
 */
import { createHash } from "node:crypto";

export function normText(s: string | null | undefined): string {
  if (!s) return "";
  let out = s.normalize("NFKD").replace(/[̀-ͯ]/g, "");
  out = out.toLowerCase();
  out = out.replace(/[,.'"\/\-()[\]_&+]/g, " ");
  return out.replace(/\s+/g, " ").trim();
}

const PRODUCER_PREFIX_MAP: Array<[RegExp, string]> = [
  [/^d\s+/, "domaine "],
  [/^dom\s+/, "domaine "],
  [/^ch\s+/, "chateau "],
];

export function expandProducerPrefix(normalized: string): string {
  let out = normalized;
  for (const [re, repl] of PRODUCER_PREFIX_MAP) {
    if (re.test(out)) {
      out = out.replace(re, repl);
      break;
    }
  }
  return out;
}

const CUVEE_TAIL_STRIPS: RegExp[] = [
  /\b1\s*er\s+(grand\s+)?cru(\s+classe)?\b/g,
  /\b[2-5](\s*e|eme|ème)\s+cru(\s+classe)?\b/g,
  /\bgrand\s+cru(\s+classe)?\b/g,
  /\baoc?\s+[a-z\- ]+$/g,
  /\b(19|20)\d{2}\b/g,
  /\b\d+\s*ml\b/g,
  /\b\d+\s*cl\b/g,
  /\b(magnum|jeroboam|mathusalem|salmanazar|balthazar|nabuchodonosor)\b/g,
];

export function cleanCuveeTails(normalized: string): string {
  let out = normalized;
  for (const re of CUVEE_TAIL_STRIPS) {
    out = out.replace(re, " ");
  }
  return out.replace(/\s+/g, " ").trim();
}

export function normalizeProducer(name: string): string {
  return expandProducerPrefix(normText(name));
}

export function normalizeCuvee(name: string): string {
  return cleanCuveeTails(normText(name));
}

export function computeWineKey(opts: {
  producerNorm: string;
  cuveeNorm: string;
  vintage: number | null;
  appellationNorm: string;
  bottleMl?: number;
}): string {
  const { producerNorm, cuveeNorm, vintage, appellationNorm, bottleMl = 750 } = opts;
  const v = vintage === null ? "NV" : String(vintage);
  const raw = `${producerNorm}|${cuveeNorm}|${v}|${appellationNorm}|${bottleMl}`;
  return createHash("sha1").update(raw).digest("hex").slice(0, 16);
}

/** Normalize any rating to /100 for cross-source comparison. */
export function normalizeScoreTo100(score: number, scale: "/100" | "/20" | "/5" | "stars"): number {
  switch (scale) {
    case "/100":
      return score;
    case "/20":
      return (score / 20) * 100;
    case "/5":
      return (score / 5) * 100;
    case "stars":
      return (score / 5) * 100;
  }
}

/** Hard region gate: does this producer make wines in this appellation? */
export function isAppellationAllowed(producer: { allowedAppellations: string[] }, appellationNorm: string): boolean {
  return producer.allowedAppellations.includes(appellationNorm);
}
