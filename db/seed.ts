/**
 * Seed minimal data: sources, 20 cellar locations, a couple of placeholder producers/wines
 * so the UI has something to render before the producer registry import runs.
 *
 * Real producer registry import lives in scripts/import-from-burgundy-manager.ts.
 */
import { db } from "./index";
import {
  dimSource,
  cellarLocations,
  dimProducer,
  dimAppellation,
  dimWine,
} from "./schema";
import { eq } from "drizzle-orm";
import { createHash } from "node:crypto";

function normText(s: string): string {
  return s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[,.'"\/\-()[\]_&+]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function computeWineKey(
  producerNorm: string,
  cuveeNorm: string,
  vintage: number | null,
  appellationNorm: string,
  bottleMl = 750,
): string {
  const v = vintage === null ? "NV" : String(vintage);
  const raw = `${producerNorm}|${cuveeNorm}|${v}|${appellationNorm}|${bottleMl}`;
  return createHash("sha1").update(raw).digest("hex").slice(0, 16);
}

async function seed() {
  console.log("→ Seeding sources…");
  await db.insert(dimSource).values([
    { sourceCode: "burgundy_manager", sourceName: "Burgundy Manager Export", sourceTier: "A_official", cadence: "one_shot", countryCode: "FR" },
    { sourceCode: "millesima", sourceName: "Millesima", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "FR", baseUrl: "https://www.millesima.fr" },
    { sourceCode: "idealwine", sourceName: "iDealwine", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "FR", baseUrl: "https://www.idealwine.com" },
    { sourceCode: "cavissima", sourceName: "Cavissima", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "FR", baseUrl: "https://www.cavissima.com" },
    { sourceCode: "lavinia", sourceName: "Lavinia", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "FR", baseUrl: "https://www.lavinia.fr" },
    { sourceCode: "vinatis", sourceName: "Vinatis", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "FR", baseUrl: "https://www.vinatis.com" },
    { sourceCode: "wdc_be", sourceName: "WDC", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "BE", baseUrl: "https://www.wdc.be" },
    { sourceCode: "cinoco", sourceName: "Cinoco", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "BE", baseUrl: "https://www.cinoco.com" },
    { sourceCode: "wijnhuis", sourceName: "Wijnhuis", sourceTier: "B_retailer_major", cadence: "monthly", countryCode: "BE", baseUrl: "https://www.wijnhuis.be" },
    { sourceCode: "decanter", sourceName: "Decanter", sourceTier: "E_press_critic", cadence: "monthly", baseUrl: "https://www.decanter.com" },
    { sourceCode: "wine_spectator", sourceName: "Wine Spectator", sourceTier: "F_vintage_authority", cadence: "annual", baseUrl: "https://www.winespectator.com" },
    { sourceCode: "rvf", sourceName: "Revue du Vin de France", sourceTier: "E_press_critic", cadence: "monthly", baseUrl: "https://www.larvf.com" },
    { sourceCode: "xwines", sourceName: "X-Wines (CC0)", sourceTier: "D_user_aggregate", cadence: "annual", licenseClass: "open" },
  ]).onConflictDoNothing();

  console.log("→ Seeding 20 cellar locations…");
  const locations = Array.from({ length: 20 }, (_, i) => ({
    locationId: i + 1,
    name: `Emplacement ${String(i + 1).padStart(2, "0")}`,
    capacity: 200,
    temperatureZone: "cellar" as const,
  }));
  await db.insert(cellarLocations).values(locations).onConflictDoNothing();

  console.log("→ Seeding sample appellations (Bourgogne)…");
  const appellations = [
    { countryCode: "FR", region: "Bourgogne", subregion: "Côte de Beaune", appellationName: "Meursault", appellationNorm: "meursault", level: "village" as const, latitude: 46.9776, longitude: 4.7689 },
    { countryCode: "FR", region: "Bourgogne", subregion: "Côte de Beaune", appellationName: "Meursault 1er Cru", appellationNorm: "meursault premier cru", level: "premier_cru" as const, latitude: 46.9776, longitude: 4.7689 },
    { countryCode: "FR", region: "Bourgogne", subregion: "Côte de Nuits", appellationName: "Vosne-Romanée", appellationNorm: "vosne romanee", level: "village" as const, latitude: 47.1820, longitude: 4.9534 },
    { countryCode: "FR", region: "Bourgogne", subregion: "Chablis", appellationName: "Chablis Grand Cru", appellationNorm: "chablis grand cru", level: "grand_cru" as const, latitude: 47.8133, longitude: 3.7993 },
    { countryCode: "FR", region: "Bordeaux", subregion: "Médoc", appellationName: "Pauillac", appellationNorm: "pauillac", level: "village" as const, latitude: 45.1989, longitude: -0.7480 },
    { countryCode: "FR", region: "Champagne", appellationName: "Champagne", appellationNorm: "champagne", level: "regional" as const, latitude: 49.0537, longitude: 3.9333 },
    { countryCode: "IT", region: "Toscana", appellationName: "Brunello di Montalcino", appellationNorm: "brunello di montalcino", level: "village" as const, latitude: 43.0578, longitude: 11.4900 },
  ];
  await db.insert(dimAppellation).values(appellations).onConflictDoNothing();

  console.log("→ Seeding sample producers (3 emblematic ones for UI render)…");
  const sampleProducers = [
    {
      producerName: "Domaine Coche-Dury",
      producerNorm: normText("Domaine Coche-Dury"),
      countryCode: "FR",
      region: "Bourgogne",
      subregion: "Côte de Beaune",
      allowedAppellations: ["meursault", "meursault premier cru", "corton charlemagne", "puligny montrachet", "bourgogne"],
      website: "https://www.coche-dury.com",
      latitude: 46.9776,
      longitude: 4.7689,
      tier: 1,
    },
    {
      producerName: "Domaine de la Romanée-Conti",
      producerNorm: normText("Domaine de la Romanee-Conti"),
      countryCode: "FR",
      region: "Bourgogne",
      subregion: "Côte de Nuits",
      allowedAppellations: ["romanee conti", "la tache", "richebourg", "romanee saint vivant", "grands echezeaux", "echezeaux", "montrachet", "corton"],
      latitude: 47.1820,
      longitude: 4.9534,
      tier: 1,
    },
    {
      producerName: "Château Pétrus",
      producerNorm: normText("Chateau Petrus"),
      countryCode: "FR",
      region: "Bordeaux",
      subregion: "Pomerol",
      allowedAppellations: ["pomerol"],
      latitude: 44.9270,
      longitude: -0.1820,
      tier: 1,
    },
  ];
  await db.insert(dimProducer).values(sampleProducers).onConflictDoNothing();

  // Fetch keys for wine seeding
  const cocheDury = await db.select().from(dimProducer).where(eq(dimProducer.producerNorm, normText("Domaine Coche-Dury"))).get();
  const meursaultPremier = await db.select().from(dimAppellation).where(eq(dimAppellation.appellationNorm, "meursault premier cru")).get();

  if (cocheDury && meursaultPremier) {
    console.log("→ Seeding 1 demo wine (Coche-Dury Meursault Perrières 2020)…");
    const cuveeName = "Meursault Perrières";
    const cuveeNorm = normText(cuveeName);
    const vintage = 2020;
    const wineKey = computeWineKey(cocheDury.producerNorm, cuveeNorm, vintage, meursaultPremier.appellationNorm, 750);
    await db.insert(dimWine).values({
      wineKey,
      producerKey: cocheDury.producerKey,
      appellationKey: meursaultPremier.appellationKey,
      cuveeName,
      cuveeNorm,
      color: "white",
      vintage,
      isNonVintage: false,
      bottleMl: 750,
      alcoholPct: 13.5,
      canonicalName: `${cocheDury.producerName} · ${cuveeName} · ${vintage}`,
    }).onConflictDoNothing();
  }

  console.log("✓ Seed complete");
}

seed().catch((e) => {
  console.error(e);
  process.exit(1);
});
