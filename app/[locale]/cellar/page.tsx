import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import {
  cellarLocations,
  cellarInventory,
  dimWine,
  dimProducer,
  dimAppellation,
  dimVariety,
  bridgeWineVariety,
  factRating,
  factPrice,
} from "@/db/schema";
import { eq, sql, inArray } from "drizzle-orm";
import { Wine, Warehouse, TrendingDown, Star } from "lucide-react";
import { PageShell } from "@/components/page-shell";
import { CellarBoard, type CellarBottleRow, type CellarLabels } from "@/components/CellarBoard";
import { CellarCsvActions, type CsvLabels } from "@/components/CellarCsvActions";

export const dynamic = "force-dynamic";

export default async function CellarPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("cellar");

  const locations = await db.select().from(cellarLocations).orderBy(cellarLocations.locationId);

  const inventoryRows = await db
    .select({
      inventoryId: cellarInventory.inventoryId,
      wineKey: cellarInventory.wineKey,
      locationId: cellarInventory.locationId,
      qty: cellarInventory.qty,
      purchasePriceEur: cellarInventory.purchasePriceEur,
      purchaseDate: cellarInventory.purchaseDate,
      purchaseSource: cellarInventory.purchaseSource,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      alcoholPct: dimWine.alcoholPct,
      producerName: dimProducer.producerName,
      appellationName: dimAppellation.appellationName,
      region: dimAppellation.region,
    })
    .from(cellarInventory)
    .innerJoin(dimWine, eq(cellarInventory.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey));

  // Per-wine enrichment for the hover ID card: dominant grape, avg critic
  // rating, avg market price. One grouped query each, keyed by wine_key.
  const wineKeys = [...new Set(inventoryRows.map((r) => r.wineKey))];
  const ratingByWine = new Map<string, number>();
  const priceByWine = new Map<string, number>();
  const grapeByWine = new Map<string, { name: string; share: number }>();
  if (wineKeys.length > 0) {
    const [ratingRows, priceRows, varietyRows] = await Promise.all([
      db
        .select({ wineKey: factRating.wineKey, avg: sql<number>`avg(${factRating.scoreNormalized100})` })
        .from(factRating)
        .where(inArray(factRating.wineKey, wineKeys))
        .groupBy(factRating.wineKey),
      db
        .select({ wineKey: factPrice.wineKey, avg: sql<number>`avg(${factPrice.amountEur})` })
        .from(factPrice)
        .where(inArray(factPrice.wineKey, wineKeys))
        .groupBy(factPrice.wineKey),
      db
        .select({ wineKey: bridgeWineVariety.wineKey, name: dimVariety.varietyName, share: bridgeWineVariety.sharePct })
        .from(bridgeWineVariety)
        .innerJoin(dimVariety, eq(bridgeWineVariety.varietyKey, dimVariety.varietyKey))
        .where(inArray(bridgeWineVariety.wineKey, wineKeys)),
    ]);
    for (const r of ratingRows) if (r.avg !== null) ratingByWine.set(r.wineKey, Number(r.avg));
    for (const r of priceRows) if (r.avg !== null && r.avg > 0) priceByWine.set(r.wineKey, Number(r.avg));
    for (const v of varietyRows) {
      const s = v.share ?? 0;
      const cur = grapeByWine.get(v.wineKey);
      if (!cur || s > cur.share) grapeByWine.set(v.wineKey, { name: v.name, share: s });
    }
  }

  const bottles: CellarBottleRow[] = inventoryRows.map((r) => ({
    inventoryId: r.inventoryId,
    wineKey: r.wineKey,
    locationId: r.locationId,
    qty: r.qty,
    purchasePriceEur: r.purchasePriceEur ?? null,
    purchaseDate: r.purchaseDate ?? null,
    purchaseSource: r.purchaseSource ?? null,
    cuveeName: r.cuveeName,
    producerName: r.producerName,
    vintage: r.vintage,
    color: r.color,
    appellationName: r.appellationName,
    region: r.region,
    primaryVariety: grapeByWine.get(r.wineKey)?.name ?? null,
    alcoholPct: r.alcoholPct ?? null,
    avgRating: ratingByWine.get(r.wineKey) ?? null,
    avgPriceEur: priceByWine.get(r.wineKey) ?? null,
  }));

  const totalBottles = bottles.reduce((a, b) => a + b.qty, 0);
  const totalCapacity = locations.reduce((a, l) => a + l.capacity, 0);
  const uniqueWines = new Set(bottles.map((b) => b.wineKey)).size;
  const cellarValue = inventoryRows.reduce(
    (a, r) => a + (r.qty * (r.purchasePriceEur ?? 0)),
    0,
  );
  const locationsInUse = new Set(bottles.map((b) => b.locationId)).size;

  // KPI: average critic rating across wines in cellar (mean of per-wine averages)
  const avgCriticRating =
    ratingByWine.size > 0
      ? [...ratingByWine.values()].reduce((a, b) => a + b, 0) / ratingByWine.size
      : null;

  const labels: CellarLabels = {
    addBottle: t("addBottle"),
    consume: t("consume"),
    move: t("move"),
    qty: t("qty"),
    wine: t("wine"),
    location: t("location"),
    search: t("searchPlaceholder"),
    noResults: t("noResults"),
    cancel: t("cancel"),
    save: t("save"),
    capacityFull: t("capacityFull"),
    capacityExceeded: t("capacityExceeded"),
    personalScore: t("personalScore"),
    occasion: t("occasion"),
    tastingNote: t("tastingNote"),
    consumed: t("consumed"),
    moved: t("moved"),
    empty: t("emptyLocation"),
    dragHint: t("dragHint"),
    ocrScan: t("ocrScan"),
    ocrScanning: t("ocrScanning"),
    ocrError: t("ocrError"),
    editDetails: t("editDetails"),
    purchasePrice: t("purchasePrice"),
    purchaseDate: t("purchaseDate"),
    purchaseSource: t("purchaseSource"),
    marketPrice: t("marketPrice"),
    criticScore: t("criticScore"),
    noRatings: t("noRatings"),
    noPrices: t("noPrices"),
    saved: t("saved"),
  };

  const csvLabels: CsvLabels = {
    importBtn: t("import"),
    exportBtn: t("exportCsv"),
    templateBtn: t("downloadTemplate"),
    importTitle: t("csv.importTitle"),
    importing: t("csv.importing"),
    close: t("csv.close"),
    resultAccepted: t("csv.accepted"),
    resultInserted: t("csv.inserted"),
    resultMerged: t("csv.merged"),
    resultRejected: t("csv.rejected"),
    resultDetails: t("csv.details"),
    resultDone: t("csv.done"),
    uploadError: t("csv.uploadError"),
  };

  const fmtEur = new Intl.NumberFormat(locale === "fr" ? "fr-FR" : locale, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  });

  return (
    <PageShell
      title={t("title")}
      subtitle={t("subtitle")}
      badge={`${totalBottles} / ${totalCapacity}`}
    >
      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <div className="stat-card">
          <Wine className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{uniqueWines}</div>
          <div className="stat-card-label">{t("kpi.uniqueWines")}</div>
        </div>
        <div className="stat-card">
          <TrendingDown className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{cellarValue > 0 ? fmtEur.format(cellarValue) : "—"}</div>
          <div className="stat-card-label">{t("kpi.cellarValue")}</div>
        </div>
        <div className="stat-card">
          <Star className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">
            {avgCriticRating !== null ? `${Math.round(avgCriticRating)}/100` : "—"}
          </div>
          <div className="stat-card-label">{t("kpi.avgRating")}</div>
        </div>
        <div className="stat-card">
          <Warehouse className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{locationsInUse}</div>
          <div className="stat-card-label">{t("kpi.locations")}</div>
        </div>
      </div>

      <div className="mb-6">
        <CellarCsvActions labels={csvLabels} />
      </div>

      <CellarBoard locations={locations} bottles={bottles} labels={labels} />
    </PageShell>
  );
}
