#!/usr/bin/env tsx
/**
 * scripts/import-vitis-epicuria.ts
 *
 * One-shot import of the Vitis Epicuria wine catalog into Achilles DB.
 * Source JSON: C:\Claude\.firecrawl\vitis-wines.json  (1 439 wines, sorted by price)
 *
 * Role   : Patroclus (Backend)
 * Run    : npx tsx scripts/import-vitis-epicuria.ts
 * Output : dim_producer, dim_appellation, dim_wine, staging_price_candidates, ops_batch_log
 */

import { readFileSync }  from "node:fs";
import { createHash, randomUUID } from "node:crypto";
import { eq, and }       from "drizzle-orm";
import { db, schema }    from "../db/index";
import {
  normText,
  computeWineKey,
  normalizeProducer,
  normalizeCuvee,
} from "../lib/identity";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface RawWine {
  name:        string;
  producer?:   string;
  appellation?: string;
  region?:     string;
  vintage?:    string;
  format?:     string;
  price_eur:   number;
  product_url?: string;
}

type WineColor = "red" | "white" | "rosé" | "sparkling" | "sweet" | "fortified" | "orange";
type AppLevel  = "regional" | "village" | "premier_cru" | "grand_cru" | "iconic";

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const SOURCE_CODE = "vitis_epicuria";
const RETAILER    = "Vitis Epicuria";
const BASE_URL    = "https://www.vitis-epicuria.com";
const JSON_PATH   = "C:\\Claude\\.firecrawl\\vitis-wines.json";

// ─────────────────────────────────────────────────────────────────────────────
// Inference helpers
// ─────────────────────────────────────────────────────────────────────────────

function inferColor(app: string, reg: string, name: string): WineColor {
  const a = app.toLowerCase();
  const r = reg.toLowerCase();
  const n = name.toLowerCase();

  // Fortified
  if (a.includes("cognac"))                                            return "fortified";
  if (a.includes("porto"))                                             return "fortified";

  // Sweet
  if (["sauternes","barsac","loupiac"].some(x => a.includes(x)))      return "sweet";
  if (["banyuls","maury","rivesaltes"].some(x => a.includes(x)))      return "sweet";

  // Sparkling
  if (a.includes("champagne") && !a.includes("coteaux champenois"))   return "sparkling";
  if (r.includes("petillant") || n.includes("pet nat"))               return "sparkling";
  if (a.includes("cremant"))                                           return "sparkling";

  // Rosé
  if (r.includes("rose") || a.endsWith("rose") || a.includes(" rose ")) return "rosé";
  if (n.includes(" rose") || n.includes("rosé"))                      return "rosé";

  // White markers (appellation & region slug)
  const WHITE = [
    "chablis","condrieu","corton charlemagne","meursault","puligny","chassagne",
    "batard","chevalier montrachet","montrachet ","muscadet","vouvray","savennieres",
    "saint peray","pouilly fume","pouilly fuisse","macon","saint veran","bouzeron",
    "bourgogne aligote","alsace","saint romain","saint aubin","auxey","pernand",
    "rully 1","chignin","jasnieres","coteaux du loir","trebbiano",
    "pessac leognan blanc","graves blanc","bordeaux blanc",
    "hermitage blanc","saint joseph blanc","montlouis","anjou blanc",
    "coulee de serrant","l etoile","chignin bergeron",
  ];
  if (WHITE.some(m => a.includes(m) || r.replace(/-/g," ").includes(m))) return "white";
  if (r.endsWith("-blanc") || a.endsWith(" blanc"))                    return "white";
  if (n.includes(" blanc") || n.includes("chardonnay") || n.includes("viognier")
      || n.includes("riesling") || n.includes("chenin") || n.includes("gewurztraminer")
      || n.includes("pinot gris") || n.includes("pinot blanc"))        return "white";

  // Red markers
  const RED = [
    "pomerol","saint emilion","pauillac","saint julien","margaux","saint estephe",
    "medoc","haut medoc","fronsac","canon fronsac","cotes de bourg","cotes de castillon",
    "cote rotie","cornas","gigondas","vacqueyras","chateauneuf du pape","lirac","vinsobres",
    "gevrey chambertin","chambolle musigny","vosne romanee","nuits saint georges",
    "pommard","volnay","beaune","savigny les beaune","morey saint denis","fixin","marsannay",
    "chambertin","echezeaux","musigny","richebourg","la grande rue","clos de tart",
    "clos des lambrays","clos de la roche","clos de vougeot",
    "barolo","barbaresco","chianti","amarone","toscane","pinot nero","toscana",
    "rioja","ribera del duero","priorat","bierzo","navarra","mentrida",
    "bandol","madiran","irancy","corton",
    "brouilly","fleurie","morgon","chenas","saint amour",
    "saumur champigny","chinon","bourgueil","saint nicolas de bourgueil",
    "languedoc","terrasses du larzac","la clape",
    "costieres de nimes","coteaux du lyonnais","collines rhodaniennes",
    "puisseguin","graves rouge","cotes de provence","sicile","venetie",
    "ombrie","latium","campanie","salento","victoria","barossa","eden valley","napa",
    "irancy","sancerre rouge","bourgogne rouge",
  ];
  if (RED.some(m => a.includes(m)))                                    return "red";
  if (r.endsWith("-rouge") || a.endsWith(" rouge"))                    return "red";
  if (n.includes(" rouge") || n.includes("pinot noir") || n.includes("syrah")
      || n.includes("grenache") || n.includes("cabernet") || n.includes("merlot")
      || n.includes("nebbiolo") || n.includes("sangiovese") || n.includes("gamay")) return "red";

  // Regional fallback
  if (a.includes("bourgogne") || a.includes("cote de nuits") || a.includes("cote de beaune")) return "red";
  if (a.includes("cotes du rhone") || a.includes("hermitage") || a.includes("bordeaux"))       return "red";
  return "red";
}

function inferCountry(app: string): string {
  const a = app.toLowerCase();
  if (["barolo","barbaresco","chianti","toscane","toscana","piemont","venetie","amarone",
       "sicile","ombrie","latium","abruzzes","campanie","langhe","frioul","alto adige",
       "veneto","veronese","salento","pinot nero","trebbiano"].some(x => a.includes(x))) return "IT";
  if (["rioja","ribera del duero","priorat","bierzo","emporda","navarra","mentrida"].some(x => a.includes(x))) return "ES";
  if (["barossa","eden valley","mclaren","clare valley","victoria","australie"].some(x => a.includes(x))) return "AU";
  if (["napa","californie","willamette","central coasaint","oregon"].some(x => a.includes(x))) return "US";
  if (a.includes("mendoza")) return "AR";
  if (a.includes("allemagne")) return "DE";
  if (a.includes("hongrie")) return "HU";
  if (a.includes("suisse")) return "CH";
  if (a.includes("porto")) return "PT";
  return "FR";
}

function inferRegion(app: string, country: string): string {
  const a = app.toLowerCase();
  if (country === "IT") {
    if (["barolo","barbaresco","langhe","piemont","alba"].some(x => a.includes(x))) return "Piémont";
    if (["toscane","toscana","chianti","brunello","pinot nero"].some(x => a.includes(x))) return "Toscane";
    if (["venetie","amarone","veneto","veronese"].some(x => a.includes(x))) return "Vénétie";
    if (a.includes("sicile")) return "Sicile";
    if (a.includes("ombrie")) return "Ombrie";
    if (["campanie","salento","pouilles","colli"].some(x => a.includes(x))) return "Italie du Sud";
    if (a.includes("frioul")) return "Frioul";
    if (a.includes("alto adige")) return "Trentin-Haut-Adige";
    if (["trebbiano","abruzzes"].some(x => a.includes(x))) return "Italie du Centre";
    return "Italie";
  }
  if (country === "ES") {
    if (a.includes("rioja")) return "Rioja";
    if (a.includes("ribera")) return "Ribera del Duero";
    if (["priorat","emporda"].some(x => a.includes(x))) return "Catalogne";
    return "Espagne";
  }
  if (country !== "FR") return country;

  const BDX = ["bordeaux","pomerol","saint emilion","pauillac","saint julien","margaux",
    "saint estephe","medoc","haut medoc","graves","pessac","sauternes","barsac","loupiac",
    "fronsac","canon fronsac","cotes de bourg","cotes de castillon","sainte foy","puisseguin"];
  if (BDX.some(x => a.includes(x))) return "Bordeaux";

  const BRG = ["chablis","bourgogne","gevrey","chambolle","vosne","nuits","pommard","volnay",
    "meursault","puligny","chassagne","corton","beaune","savigny","musigny","chambertin",
    "echezeaux","richebourg","romanee","la grande rue","clos de","morey","fixin","marsannay",
    "pernand","bouzeron","rully","mercurey","givry","macon","saint veran","pouilly fuisse",
    "auxey","santenay","irancy","saint aubin","saint romain","maranges","montrachet","batard",
    "chevalier","cote de nuits","cote de beaune","irancy"];
  if (BRG.some(x => a.includes(x))) return "Bourgogne";

  if (["champagne","coteaux champenois"].some(x => a.includes(x))) return "Champagne";
  if (a.includes("alsace")) return "Alsace";

  const RHN = ["cote rotie","condrieu","saint joseph","crozes hermitage","hermitage","cornas",
    "saint peray","cotes du rhone","gigondas","vacqueyras","chateauneuf","lirac","vinsobres",
    "beaumes de venise","ventoux","coteaux du lyonnais","collines rhodaniennes","costieres de nimes"];
  if (RHN.some(x => a.includes(x))) return "Rhône";

  const LRE = ["sancerre","pouilly fume","chinon","bourgueil","vouvray","montlouis",
    "muscadet","anjou","saumur","savennieres","jasnieres","coteaux du loir",
    "saint nicolas de bourgueil","val de loire","vin de france (loire)","vin de france loire"];
  if (LRE.some(x => a.includes(x))) return "Loire";

  if (["jura","l etoile","cotes du jura"].some(x => a.includes(x))) return "Jura";
  if (["savoie","chignin","mondeuse","allobroges","vin de savoie"].some(x => a.includes(x))) return "Savoie";

  const LGD = ["languedoc","terrasses du larzac","la clape","herault","minervois","corbieres",
    "faugeres","pezenas","coteaux du languedoc","igp gard","igp alpilles","igp pays herault"];
  if (LGD.some(x => a.includes(x))) return "Languedoc";

  const RSL = ["roussillon","banyuls","maury","rivesaltes","collioure","cotes catalanes","igp cotes catalanes"];
  if (RSL.some(x => a.includes(x))) return "Roussillon";

  const PRV = ["provence","bandol","palette","vin de corse","corse","bellet",
    "igp var","vdp du var","vin de france (provence)","cotes de provence"];
  if (PRV.some(x => a.includes(x))) return "Provence";

  if (["madiran","irouleguy","cahors","gaillac","bergerac","jurancon"].some(x => a.includes(x))) return "Sud-Ouest";

  if (["beaujolais","brouilly","fleurie","morgon","chenas","saint amour",
       "moulin a vent","chiroubles","julienas"].some(x => a.includes(x))) return "Beaujolais";

  return "France";
}

function inferAppellationLevel(app: string): AppLevel {
  const a = app.toLowerCase();
  const GC = [
    "grand cru","grands echezeaux","richebourg","musigny","chambertin","romanee",
    "la tache","la grand rue","montrachet","batard","chevalier montrachet",
    "corton charlemagne","bonnes mares","clos de tart","clos des lambrays",
    "clos de la roche","clos de vougeot","echezeaux","hermitage","corton",
    "banyuls grand cru","sauternes","griotte","ruchottes","latricieres","mazis","mazoyeres",
    "charmes chambertin","chapelle chambertin","clos saint denis","clos du mesnil",
  ];
  if (GC.some(x => a.includes(x))) return "grand_cru";

  if (a.includes("premier cru") || a.includes("1er cru") || a.includes("1 er cru")) return "premier_cru";

  const VILLAGE = [
    "gevrey","chambolle","vosne","nuits saint georges","pommard","volnay",
    "meursault","puligny montrachet","chassagne montrachet","beaune","savigny",
    "morey saint denis","fixin","marsannay","pernand","auxey","saint aubin","saint romain",
    "santenay","pauillac","saint julien","margaux","saint estephe","pomerol","saint emilion",
    "barolo","barbaresco","cote rotie","condrieu","chateauneuf du pape","gigondas",
    "sancerre","chinon","vouvray","montlouis","chablis grand cru","chablis premier cru",
    "bandol","madiran","saint peray","cornas",
  ];
  if (VILLAGE.some(x => a.includes(x))) return "village";

  return "regional";
}

function extractCuveeName(name: string, producer: string, appellation: string): string {
  const nUp = name.toUpperCase().trim();
  const pUp = producer.toUpperCase().trim();

  let cuvee = (pUp && nUp.startsWith(pUp))
    ? name.slice(producer.length).trim()
    : name.trim();

  // Strip trailing "2023 PRIMEUR" or "2023"
  cuvee = cuvee.replace(/\s+\d{4}(\s+PRIMEUR)?\s*$/i, "").trim();
  // Strip any other inline years
  cuvee = cuvee.replace(/\b(19|20)\d{2}\b/g, "").replace(/\s+/g, " ").trim();

  return cuvee || appellation || producer;
}

function inferBottleMl(format: string | undefined, name: string): number {
  const f = (format ?? "").toLowerCase();
  const n = name.toLowerCase();
  if (f.includes("double magnum") || n.includes("double magnum")) return 3000;
  if (f.includes("magnum")        || n.includes(" magnum"))       return 1500;
  if (f.includes("jeroboam")      || n.includes("jeroboam"))      return 3000;
  if (f.includes("petit")         || f.includes("half"))           return 375;
  return 750;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────

function main() {
  console.log("📥  Loading Vitis Epicuria catalog…");

  const raw = readFileSync(JSON_PATH, "utf-8");
  const s   = raw.indexOf("[");
  const e   = raw.lastIndexOf("]") + 1;
  const wines: RawWine[] = JSON.parse(raw.slice(s, e));

  console.log(`   ${wines.length} wines in JSON\n`);

  const batchId = randomUUID();
  let   sourceKey: number;

  // ── 1. Upsert source ──────────────────────────────────────────────────────
  const existingSrc = db
    .select({ sourceKey: schema.dimSource.sourceKey })
    .from(schema.dimSource)
    .where(eq(schema.dimSource.sourceCode, SOURCE_CODE))
    .get();

  if (existingSrc) {
    sourceKey = existingSrc.sourceKey;
    console.log(`ℹ️   Source '${SOURCE_CODE}' exists (key=${sourceKey})`);
  } else {
    const [src] = db
      .insert(schema.dimSource)
      .values({
        sourceCode: SOURCE_CODE,
        sourceName: RETAILER,
        sourceTier: "B_retailer_major",
        countryCode: "FR",
        baseUrl: BASE_URL,
        licenseClass: "public_check_terms",
        cadence: "monthly",
        enabled: true,
      })
      .returning({ sourceKey: schema.dimSource.sourceKey })
      .all();
    sourceKey = src.sourceKey;
    console.log(`✅  Created source '${SOURCE_CODE}' (key=${sourceKey})`);
  }

  // ── 2. Start batch log ────────────────────────────────────────────────────
  db.insert(schema.opsBatchLog).values({
    batchId,
    sourceKey,
    startedAt: new Date(),
    status: "running",
    rowsFetched: wines.length,
  }).run();

  // ── 3. Process wines ──────────────────────────────────────────────────────
  let winesInserted = 0;
  let winesUpdated  = 0;
  let pricesStaged  = 0;
  let dlqCount      = 0;

  const producerCache    = new Map<string, number>();  // `norm|CC` → producerKey
  const appellationCache = new Map<string, number>();  // `norm|CC` → appellationKey
  const now = new Date();

  for (let i = 0; i < wines.length; i++) {
    const wine = wines[i];

    // Progress heartbeat
    if ((i + 1) % 200 === 0) {
      console.log(`   … ${i + 1}/${wines.length} processed`);
    }

    try {
      const app      = (wine.appellation ?? "").trim();
      const reg      = (wine.region      ?? "").trim();
      const rawName  = (wine.name        ?? "").trim();
      const rawProd  = (wine.producer    ?? "").trim();

      if (!rawName) throw new Error("Empty wine name");

      const country  = inferCountry(app);
      const region   = inferRegion(app, country);
      const color    = inferColor(app, reg, rawName);
      const vintage  = wine.vintage ? parseInt(wine.vintage, 10) : null;
      const isNV     = vintage === null;
      const bottleMl = inferBottleMl(wine.format, rawName);

      const cuveeName    = extractCuveeName(rawName, rawProd, app);
      const producerNorm = normalizeProducer(rawProd || rawName);
      const cuveeNorm    = normalizeCuvee(cuveeName, [producerNorm]);
      const appNorm      = normText(app);

      // ── 3a. Upsert producer ───────────────────────────────────────────────
      const pCacheKey = `${producerNorm}|${country}`;
      if (!producerCache.has(pCacheKey)) {
        const ex = db
          .select({ producerKey: schema.dimProducer.producerKey })
          .from(schema.dimProducer)
          .where(and(
            eq(schema.dimProducer.producerNorm, producerNorm),
            eq(schema.dimProducer.countryCode, country),
          ))
          .get();

        if (ex) {
          db.update(schema.dimProducer)
            .set({ lastSeenAt: now })
            .where(eq(schema.dimProducer.producerKey, ex.producerKey))
            .run();
          producerCache.set(pCacheKey, ex.producerKey);
        } else {
          const [p] = db
            .insert(schema.dimProducer)
            .values({
              producerName: rawProd || cuveeName,
              producerNorm,
              countryCode: country,
              region,
              allowedAppellations: [appNorm],
              aliases: [],
              status: "active",
              coverageTier: "long_tail",
            })
            .returning({ producerKey: schema.dimProducer.producerKey })
            .all();
          producerCache.set(pCacheKey, p.producerKey);
        }
      }
      const producerKey = producerCache.get(pCacheKey)!;

      // ── 3b. Upsert appellation ────────────────────────────────────────────
      const aCacheKey = `${appNorm}|${country}`;
      if (!appellationCache.has(aCacheKey)) {
        const ex = db
          .select({ appellationKey: schema.dimAppellation.appellationKey })
          .from(schema.dimAppellation)
          .where(and(
            eq(schema.dimAppellation.appellationNorm, appNorm),
            eq(schema.dimAppellation.countryCode, country),
          ))
          .get();

        if (ex) {
          appellationCache.set(aCacheKey, ex.appellationKey);
        } else {
          const [a] = db
            .insert(schema.dimAppellation)
            .values({
              countryCode: country,
              region,
              appellationName: app,
              appellationNorm: appNorm,
              level: inferAppellationLevel(app),
            })
            .returning({ appellationKey: schema.dimAppellation.appellationKey })
            .all();
          appellationCache.set(aCacheKey, a.appellationKey);
        }
      }
      const appellationKey = appellationCache.get(aCacheKey)!;

      // ── 3c. Upsert dim_wine ───────────────────────────────────────────────
      const wineKey = computeWineKey({ producerNorm, cuveeNorm, vintage, bottleMl });

      const exWine = db
        .select({ wineKey: schema.dimWine.wineKey })
        .from(schema.dimWine)
        .where(eq(schema.dimWine.wineKey, wineKey))
        .get();

      if (exWine) {
        db.update(schema.dimWine)
          .set({ lastSeenAt: now })
          .where(eq(schema.dimWine.wineKey, wineKey))
          .run();
        winesUpdated++;
      } else {
        const canonicalName = [
          rawProd || cuveeName,
          cuveeName !== rawProd ? cuveeName : null,
          vintage ? String(vintage) : "NV",
        ].filter(Boolean).join(" · ");

        db.insert(schema.dimWine).values({
          wineKey,
          producerKey,
          appellationKey,
          cuveeName,
          cuveeNorm,
          color,
          vintage,
          isNonVintage: isNV,
          bottleMl,
          canonicalName,
        }).run();
        winesInserted++;
      }

      // ── 3d. Stage price ───────────────────────────────────────────────────
      if (wine.price_eur > 0) {
        const contentHash = createHash("sha1")
          .update(`${wineKey}|${wine.price_eur}|${wine.product_url ?? ""}`)
          .digest("hex")
          .slice(0, 32);

        try {
          db.insert(schema.stagingPriceCandidates).values({
            wineKey,
            sourceKey,
            retailer: RETAILER,
            recordedAt: now,
            currencyCode: "EUR",
            amountLocal: wine.price_eur,
            amountEur:   wine.price_eur,
            sourceUrl:   wine.product_url ?? null,
            contentHash,
            batchId,
            needsReview: false,   // trusted retailer catalog, no manual review needed
          }).run();
          pricesStaged++;
        } catch {
          // Duplicate content hash — already staged, skip
        }
      }

    } catch (err) {
      // Dead-letter queue
      try {
        db.insert(schema.opsDeadLetter).values({
          sourceKey,
          batchId,
          errorClass: "validation_error",
          errorMessage: String(err),
          sourceRecordId: wine.product_url ?? wine.name,
          rawRecord: JSON.stringify(wine),
          resolution: "pending",
        }).run();
      } catch { /* ignore DLQ insert failure */ }

      dlqCount++;
      if (dlqCount <= 10) console.warn(`  ⚠  DLQ [${dlqCount}]: ${wine.name} — ${err}`);
    }
  }

  // ── 4. Finalise batch log ─────────────────────────────────────────────────
  const status = dlqCount > wines.length * 0.1 ? "partial" : "success";
  db.update(schema.opsBatchLog)
    .set({
      finishedAt:   now,
      status,
      rowsInserted: winesInserted,
      rowsUpdated:  winesUpdated,
      rowsDlq:      dlqCount,
    })
    .where(eq(schema.opsBatchLog.batchId, batchId))
    .run();

  // ── 5. Summary ────────────────────────────────────────────────────────────
  console.log("\n════════════════════════════════════════");
  console.log("  Vitis Epicuria import — COMPLETE");
  console.log("════════════════════════════════════════");
  console.log(`  Wines new      : ${winesInserted}`);
  console.log(`  Wines touched  : ${winesUpdated}`);
  console.log(`  Prices staged  : ${pricesStaged}`);
  console.log(`  DLQ            : ${dlqCount}`);
  console.log(`  Status         : ${status}`);
  console.log(`  Batch ID       : ${batchId}`);
  console.log(`  Producers seen : ${producerCache.size}`);
  console.log(`  Appellations   : ${appellationCache.size}`);
  console.log("════════════════════════════════════════\n");
}

main();
