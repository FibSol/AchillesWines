import { getTranslations, setRequestLocale } from "next-intl/server";
import { Wine, Warehouse, TrendingDown, Star } from "lucide-react";
import { getCellar } from "@/lib/queries/cellar";
import { PageShell } from "@/components/page-shell";
import { CellarBoard, type CellarBottleRow, type CellarLabels } from "@/components/CellarBoard";
import { CellarCsvActions, type CsvLabels } from "@/components/CellarCsvActions";

export const dynamic = "force-dynamic";

export default async function CellarPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("cellar");

  const { locations, bottles, kpis } = await getCellar();
  const { totalBottles, totalCapacity, uniqueWines, cellarValue, locationsInUse, avgCriticRating } = kpis;

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
    filterSearch: t("filterSearch"),
    filterAllColors: t("filterAllColors"),
    filterAllRegions: t("filterAllRegions"),
    filterVintageFrom: t("filterVintageFrom"),
    filterVintageTo: t("filterVintageTo"),
    filterReset: t("filterReset"),
    filterResultsSuffix: t("filterResultsSuffix"),
    colorLabels: {
      red: t("colorRed"),
      white: t("colorWhite"),
      "rosé": t("colorRose"),
      sparkling: t("colorSparkling"),
      sweet: t("colorSweet"),
      fortified: t("colorFortified"),
      orange: t("colorOrange"),
    },
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
          <Wine className="size-4 text-[color:var(--color-champagne-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{uniqueWines}</div>
          <div className="stat-card-label">{t("kpi.uniqueWines")}</div>
        </div>
        <div className="stat-card">
          <TrendingDown className="size-4 text-[color:var(--color-champagne-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{cellarValue > 0 ? fmtEur.format(cellarValue) : "—"}</div>
          <div className="stat-card-label">{t("kpi.cellarValue")}</div>
        </div>
        <div className="stat-card">
          <Star className="size-4 text-[color:var(--color-champagne-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">
            {avgCriticRating !== null ? `${Math.round(avgCriticRating)}/100` : "—"}
          </div>
          <div className="stat-card-label">{t("kpi.avgRating")}</div>
        </div>
        <div className="stat-card">
          <Warehouse className="size-4 text-[color:var(--color-champagne-400)]" strokeWidth={2} />
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
