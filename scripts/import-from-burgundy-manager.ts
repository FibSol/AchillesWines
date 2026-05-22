/**
 * One-shot import: burgundy-manager → achilles-wines dim_producer + dim_appellation + dim_wine.
 * Run: npx tsx scripts/import-from-burgundy-manager.ts
 * Stage 1: dim_appellation   (~200 AOC rows)
 * Stage 2: dim_producer      (~8 700 domaines)
 * Stage 3: dim_wine          (~5 800 cuvées, imported as NV — no vintage in BM source)
 */
import BetterSqlite3 from "better-sqlite3";
import { db } from "../db/index";
import { dimProducer, dimAppellation, dimWine } from "../db/schema";
import { normText, expandProducerPrefix, cleanCuveeTails, computeWineKey } from "../lib/identity";

const BM_DB = "C:\\Users\\Nicolas\\Bourgogne\\burgundy-manager\\data\\burgundy.db";

function normalizeProducer(name: string): string {
  return expandProducerPrefix(normText(name));
}

function mapLevel(level: string | null): "regional" | "village" | "premier_cru" | "grand_cru" | "iconic" {
  const l = (level ?? "").toLowerCase();
  if (l.includes("grand cru")) return "grand_cru";
  if (l.includes("premier cru") || l.includes("1er cru") || l.includes("1 er cru")) return "premier_cru";
  if (l.includes("village") || l.includes("commune")) return "village";
  if (l.includes("iconic")) return "iconic";
  return "regional";
}

async function main() {
  const bm = new BetterSqlite3(BM_DB, { readonly: true });

  // --- 1. Import appellations ---
  console.log("→ Reading appellations from burgundy-manager…");
  const bmAppellations = bm.prepare("SELECT * FROM appellations").all() as any[];

  // Most common region per appellation_id from domaines/cuvees
  const appellationRegionMap = new Map<number, string>();
  const regionRows = bm.prepare(`
    SELECT c.appellation_id, d.region, COUNT(*) as cnt
    FROM cuvees c JOIN domaines d ON c.domaine_id = d.id
    WHERE c.appellation_id IS NOT NULL
    GROUP BY c.appellation_id, d.region
    ORDER BY cnt DESC
  `).all() as any[];
  for (const row of regionRows) {
    if (!appellationRegionMap.has(row.appellation_id)) {
      appellationRegionMap.set(row.appellation_id, row.region);
    }
  }

  // Centroid coords per appellation from linked domaines
  const coordsMap = new Map<number, { lat: number; lng: number }>();
  const coordRows = bm.prepare(`
    SELECT c.appellation_id, AVG(d.lat) as lat, AVG(d.lng) as lng
    FROM cuvees c JOIN domaines d ON c.domaine_id = d.id
    WHERE c.appellation_id IS NOT NULL AND d.lat IS NOT NULL AND d.lng IS NOT NULL
    GROUP BY c.appellation_id
  `).all() as any[];
  for (const row of coordRows) {
    if (row.lat && row.lng) coordsMap.set(row.appellation_id, { lat: row.lat, lng: row.lng });
  }

  let appInserted = 0, appSkipped = 0;
  for (const a of bmAppellations) {
    const appellationNorm = normText(a.name);
    if (!appellationNorm) { appSkipped++; continue; }
    const region = appellationRegionMap.get(a.id) ?? "Bourgogne";
    const coords = coordsMap.get(a.id);
    try {
      await db.insert(dimAppellation).values({
        countryCode: "FR",
        region,
        appellationName: a.name,
        appellationNorm,
        level: mapLevel(a.level),
        geoPolygon: a.geo_polygon ?? null,
        latitude: coords?.lat ?? null,
        longitude: coords?.lng ?? null,
      }).onConflictDoNothing();
      appInserted++;
    } catch { appSkipped++; }
  }
  console.log(`  ✓ Appellations: ${appInserted} inserted, ${appSkipped} skipped`);

  // --- 2. Build allowedAppellations per domaine ---
  console.log("→ Building allowedAppellations map…");
  const allowedApps = new Map<number, Set<string>>();
  const cuveeRows = bm.prepare(`
    SELECT domaine_id, appellation_name FROM cuvees
    WHERE appellation_name IS NOT NULL AND appellation_name != ''
  `).all() as any[];
  for (const c of cuveeRows) {
    const norm = normText(c.appellation_name);
    if (!norm) continue;
    if (!allowedApps.has(c.domaine_id)) allowedApps.set(c.domaine_id, new Set());
    allowedApps.get(c.domaine_id)!.add(norm);
  }

  // --- 3. Import producers ---
  console.log("→ Reading ~8,700 domaines…");
  const bmDomaines = bm.prepare("SELECT * FROM domaines").all() as any[];
  let prodInserted = 0, prodSkipped = 0;

  for (let i = 0; i < bmDomaines.length; i++) {
    const d = bmDomaines[i] as any;
    const producerNorm = normalizeProducer(d.name);
    if (!producerNorm) { prodSkipped++; continue; }
    const allowed = Array.from(allowedApps.get(d.id) ?? []);
    try {
      await db.insert(dimProducer).values({
        producerName: d.name,
        producerNorm,
        countryCode: "FR",
        region: d.region ?? null,
        subregion: d.commune ?? null,
        allowedAppellations: allowed,
        aliases: [],
        latitude: d.lat ?? null,
        longitude: d.lng ?? null,
        tier: d.tier ?? null,
        status: "active",
      }).onConflictDoNothing();
      prodInserted++;
    } catch { prodSkipped++; }
    if (i % 500 === 0) process.stdout.write(`  ${i}/${bmDomaines.length}\r`);
  }
  console.log(`\n  ✓ Producers: ${prodInserted} inserted, ${prodSkipped} skipped`);

  // --- Stage 3: Import cuvées → dim_wine (as NV — BM has no vintage column) ---
  console.log("\n→ Stage 3: importing cuvées → dim_wine…");

  // Build lookup: producerNorm → producerKey (from freshly imported dim_producer)
  const producerLookup = new Map<string, number>();
  const allProducers = await db.select({ producerKey: dimProducer.producerKey, producerNorm: dimProducer.producerNorm }).from(dimProducer);
  for (const row of allProducers) {
    producerLookup.set(row.producerNorm, row.producerKey);
  }
  console.log(`  loaded ${producerLookup.size} producers`);

  // Build lookup: appellationNorm → appellationKey
  const appellationLookup = new Map<string, number>();
  const allAppellations = await db.select({ appellationKey: dimAppellation.appellationKey, appellationNorm: dimAppellation.appellationNorm }).from(dimAppellation);
  for (const row of allAppellations) {
    appellationLookup.set(row.appellationNorm, row.appellationKey);
  }
  console.log(`  loaded ${appellationLookup.size} appellations`);

  function mapColor(bmColor: string): "red" | "white" | "rosé" | "sparkling" | "sweet" | "fortified" | "orange" {
    switch (bmColor) {
      case "R": return "red";
      case "W": return "white";
      case "S": return "sparkling";
      case "P": return "rosé";
      default:  return "red";
    }
  }

  const bmCuvees = bm.prepare(`
    SELECT c.id, c.domaine_id, c.name, c.appellation_name, c.color,
           d.name as producer_name
    FROM cuvees c
    JOIN domaines d ON c.domaine_id = d.id
  `).all() as any[];

  let wineSkipped = 0;
  type WineRow = typeof dimWine.$inferInsert;
  const wineRows: WineRow[] = [];
  const seenKeys = new Set<string>();

  for (const c of bmCuvees as any[]) {
    const producerNorm = normalizeProducer(c.producer_name);
    const producerKey = producerLookup.get(producerNorm);
    if (!producerKey) { wineSkipped++; continue; }

    const appellationNorm = normText(c.appellation_name ?? "");
    const appellationKey = appellationLookup.get(appellationNorm);
    if (!appellationKey) { wineSkipped++; continue; }

    const cuveeName = c.name as string;
    const cuveeNorm = cleanCuveeTails(normText(cuveeName));
    if (!cuveeNorm) { wineSkipped++; continue; }

    const wineKey = computeWineKey({ producerNorm, cuveeNorm, vintage: null, appellationNorm });
    if (seenKeys.has(wineKey)) continue; // dedup within batch
    seenKeys.add(wineKey);

    wineRows.push({
      wineKey,
      producerKey,
      appellationKey,
      cuveeName,
      cuveeNorm,
      color: mapColor(c.color),
      vintage: null,
      isNonVintage: true,
      bottleMl: 750,
      canonicalName: `${c.producer_name} ${cuveeName}`,
    });
  }

  // Insert in batches of 500 (SQLite variable limit)
  const BATCH = 500;
  let wineInserted = 0;
  for (let i = 0; i < wineRows.length; i += BATCH) {
    const batch = wineRows.slice(i, i + BATCH);
    try {
      await db.insert(dimWine).values(batch).onConflictDoNothing();
      wineInserted += batch.length;
    } catch { wineSkipped += batch.length; }
    process.stdout.write(`  ${Math.min(i + BATCH, wineRows.length)}/${wineRows.length}\r`);
  }
  console.log(`\n  ✓ Wines: ${wineInserted} inserted, ${wineSkipped} skipped (${bmCuvees.length} raw cuvées)`);

  bm.close();
  console.log("✓ Import complete");
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });
