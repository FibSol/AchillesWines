/**
 * One-shot import: burgundy-manager → achilles-wines dim_producer + dim_appellation.
 * Run: npx tsx scripts/import-from-burgundy-manager.ts
 */
import BetterSqlite3 from "better-sqlite3";
import { db } from "../db/index";
import { dimProducer, dimAppellation } from "../db/schema";
import { normText, expandProducerPrefix } from "../lib/identity";

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

  bm.close();
  console.log("✓ Import complete");
  process.exit(0);
}

main().catch((e) => { console.error(e); process.exit(1); });
