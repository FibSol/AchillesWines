import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import {
  cellarLocations,
  cellarInventory,
  dimWine,
  dimProducer,
} from "@/db/schema";
import { eq } from "drizzle-orm";
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
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      producerName: dimProducer.producerName,
    })
    .from(cellarInventory)
    .innerJoin(dimWine, eq(cellarInventory.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey));

  const bottles: CellarBottleRow[] = inventoryRows.map((r) => ({
    inventoryId: r.inventoryId,
    wineKey: r.wineKey,
    locationId: r.locationId,
    qty: r.qty,
    cuveeName: r.cuveeName,
    producerName: r.producerName,
    vintage: r.vintage,
    color: r.color,
  }));

  const totalBottles = bottles.reduce((a, b) => a + b.qty, 0);
  const totalCapacity = locations.reduce((a, l) => a + l.capacity, 0);

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

  return (
    <PageShell
      title={t("title")}
      subtitle={t("subtitle")}
      badge={`${totalBottles} / ${totalCapacity}`}
    >
      <div className="mb-6">
        <CellarCsvActions labels={csvLabels} />
      </div>

      <CellarBoard locations={locations} bottles={bottles} labels={labels} />
    </PageShell>
  );
}
