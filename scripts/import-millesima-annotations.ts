#!/usr/bin/env tsx
/**
 * scripts/import-millesima-annotations.ts
 *
 * Millésima is already a scraped source (source_key=2) — its prices are covered,
 * but the scraper captures NO critic annotations. This pass adds ONLY the critic
 * scores from the merchant CSV, matched to the scraper's EXISTING dim_wine rows.
 * It creates no producers and no wines, and never touches fact_price.
 *
 * Match: producer_norm (bare / "chateau " / "domaine " expansion) + vintage,
 * restricted to wines the millesima scraper actually staged. 750ml preferred.
 *
 * Run preview : npx tsx scripts/import-millesima-annotations.ts --dry
 * Run for real: npx tsx scripts/import-millesima-annotations.ts
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { db, schema } from "../db/index";
import { normalizeProducer, normalizeCuvee, normalizeScoreTo100 } from "../lib/identity";

const CSV = "C:\\Users\\Nicolas\\Downloads\\Millesimes_tarifs_ht.csv";
const SOURCE_KEY = 2;
const DRY = process.argv.includes("--dry");

type CriticCode = "WA" | "WS" | "JS" | "JMQ" | "Vinous" | "RVF" | "JR" | "JD";
type Scale = "/100" | "/20" | "/5" | "stars";

function parseCsv(path: string): Record<string, string>[] {
  const text = new TextDecoder("windows-1252").decode(readFileSync(path));
  const rows: string[][] = [];
  let field = "", row: string[] = [], inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) { if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else inQ = false; } else field += c; }
    else if (c === '"') inQ = true;
    else if (c === ";") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c === "\r") { /* skip */ }
    else field += c;
  }
  if (field.length || row.length) { row.push(field); rows.push(row); }
  const header = rows.shift()!.map((h) => h.trim());
  return rows.filter((r) => r.length > 1).map((r) => Object.fromEntries(header.map((h, i) => [h, (r[i] ?? "").trim()])));
}

function cleanNom(nom: string): string {
  return nom
    .replace(/\s+(ex|réserve|reserve|ex\.?)\s+(château|chateau|propriété|propriete|négoce|negoce)\s*\d{0,4}/gi, " ")
    .replace(/\s+(ex|réserve|reserve)\s+\d{4}\b/gi, " ")
    .replace(/\s+\d{4}\s*$/g, " ")
    .replace(/\s+/g, " ").trim();
}

const CRITIC_MAP: Record<string, { code: CriticCode; scale: Scale }> = {
  RP: { code: "WA", scale: "/100" }, WS: { code: "WS", scale: "/100" }, JS: { code: "JS", scale: "/100" },
  JMQ: { code: "JMQ", scale: "/100" }, VN: { code: "Vinous", scale: "/100" }, RVF: { code: "RVF", scale: "/20" },
  JR: { code: "JR", scale: "/20" }, JD: { code: "JD", scale: "/100" },
};
function parseScore(raw: string): number | null {
  let s = raw.replace("+", "").trim();
  if (s.includes("-")) { const [a, b] = s.split("-").map(Number); if (!isNaN(a) && !isNaN(b)) return (a + b) / 2; }
  const v = Number(s); return isNaN(v) ? null : v;
}
function parseNotes(note: string): { code: CriticCode; scale: Scale; score: number }[] {
  if (!note) return [];
  const out: { code: CriticCode; scale: Scale; score: number }[] = [];
  for (const part of note.split("/")) {
    const m = part.trim().match(/^([A-Za-z]{2,4})\s+([\d.,+\-]+)/);
    if (!m) continue;
    const map = CRITIC_MAP[m[1].toUpperCase()]; if (!map) continue;
    const score = parseScore(m[2].replace(",", ".")); if (score === null) continue;
    if (map.scale === "/100" && (score < 50 || score > 100)) continue;
    if (map.scale === "/20" && (score < 5 || score > 20)) continue;
    out.push({ code: map.code, scale: map.scale, score });
  }
  return out;
}

// Find the scraper's existing wine for this row. Restrict to wines the millesima
// source actually staged, so we never attach to a homonym from another source.
const sqlite = (globalThis as { __achillesSqlite?: import("better-sqlite3").Database }).__achillesSqlite!;
// Tier 1: a wine the millesima scraper actually staged (most specific).
const findWineMill = sqlite.prepare(`
  SELECT w.wine_key
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  WHERE p.producer_norm = ?
    AND ((? IS NULL AND w.vintage IS NULL) OR w.vintage = ?)
    AND w.wine_key IN (SELECT wine_key FROM staging_price_candidates WHERE source_key = ${SOURCE_KEY})
  ORDER BY CASE w.bottle_ml WHEN 750 THEN 0 ELSE 1 END
  LIMIT 1
`);
// Tier 2: the canonical 750ml wine for this producer+vintage+cuvée from ANY
// source. The cuvee_norm match prevents cross-cuvée mismatches (Burgundy);
// among same-wine duplicates we take the most-referenced (canonical) row.
const findWineAny = sqlite.prepare(`
  SELECT w.wine_key,
    (SELECT count(*) FROM fact_price fp WHERE fp.wine_key=w.wine_key) +
    (SELECT count(*) FROM staging_price_candidates sp WHERE sp.wine_key=w.wine_key) +
    (SELECT count(*) FROM fact_rating fr WHERE fr.wine_key=w.wine_key) +
    (SELECT count(*) FROM staging_rating_candidates sr WHERE sr.wine_key=w.wine_key) AS refs
  FROM dim_wine w
  JOIN dim_producer p ON p.producer_key = w.producer_key
  WHERE p.producer_norm = ?
    AND ((? IS NULL AND w.vintage IS NULL) OR w.vintage = ?)
    AND w.bottle_ml = 750
    AND w.cuvee_norm = ?
  ORDER BY refs DESC
  LIMIT 1
`);

function matchWine(nom: string, vintage: number | null): string | null {
  const base = normalizeProducer(nom);
  const cuveeNorm = normalizeCuvee(nom, [base]);
  const candidates = [base, `chateau ${base}`, `domaine ${base}`];
  for (const norm of candidates) {
    const r = findWineMill.get(norm, vintage, vintage) as { wine_key: string } | undefined;
    if (r) return r.wine_key;
  }
  for (const norm of candidates) {
    const r = findWineAny.get(norm, vintage, vintage, cuveeNorm) as { wine_key: string } | undefined;
    if (r) return r.wine_key;
  }
  return null;
}

function main() {
  const rows = parseCsv(CSV);
  const annotated = rows
    .map((r) => ({ r, notes: parseNotes(r["Note"] || "") }))
    .filter((x) => x.notes.length > 0);
  console.log(`📥  ${rows.length} rows; ${annotated.length} with parseable critic notes`);

  let matched = 0, unmatched = 0, staged = 0;
  const unmatchedSamples: string[] = [];
  const seen = new Set<string>(); // de-dup (wine|critic|score|vintage) within this run

  const work = () => {
    for (const { r, notes } of annotated) {
      const nom = cleanNom(r["Nom"] || "");
      const vintage = /^\d{4}$/.test(r["Millésime"] || "") ? Number(r["Millésime"]) : null;
      const wineKey = matchWine(nom, vintage);
      if (!wineKey) {
        unmatched++;
        if (unmatchedSamples.length < 15) unmatchedSamples.push(`${r["Nom"]} ${vintage ?? "NV"} [${r["Région"]}]`);
        if (!DRY) {
          db.insert(schema.opsDeadLetter).values({
            sourceKey: SOURCE_KEY, batchId: "millesima-annotations-csv", errorClass: "unmatched_wine",
            errorMessage: `No scraper wine for "${r["Nom"]}" ${vintage ?? "NV"}; notes ${r["Note"]}`.slice(0, 400),
            rawRecord: JSON.stringify(r), resolution: "pending",
          }).run();
        }
        continue;
      }
      matched++;
      for (const n of notes) {
        const dedup = `${wineKey}|${n.code}|${n.score}|${vintage}`;
        if (seen.has(dedup)) continue;
        seen.add(dedup);
        if (DRY) { staged++; continue; }
        const ch = createHash("sha1").update(dedup).digest("hex").slice(0, 32);
        try {
          db.insert(schema.stagingRatingCandidates).values({
            wineKey, sourceKey: SOURCE_KEY, criticCode: n.code as never, reviewerType: "critic",
            score: n.score, scale: n.scale, scoreNormalized100: normalizeScoreTo100(n.score, n.scale),
            recordedAt: new Date(), contentHash: ch, batchId: "millesima-annotations-csv", needsReview: true,
          }).run();
          staged++;
        } catch { /* dup vs existing */ }
      }
    }
  };

  if (DRY) work();
  else sqlite.transaction(work)();

  console.log(`\n${DRY ? "── DRY RUN ──" : "✅  annotations staged"}`);
  console.log(`   rows matched to scraper wines : ${matched}`);
  console.log(`   rows unmatched                : ${unmatched}`);
  console.log(`   rating rows ${DRY ? "would stage" : "staged"}        : ${staged}`);
  if (unmatched) console.log(`   unmatched samples:\n     ${unmatchedSamples.join("\n     ")}`);
}

main();
