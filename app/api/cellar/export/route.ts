import { NextResponse } from "next/server";
import { db } from "@/db";
import {
  cellarInventory,
  dimWine,
  dimProducer,
  dimAppellation,
} from "@/db/schema";
import { eq, asc } from "drizzle-orm";
import { csvStringify } from "@/lib/csv";

const HEADER = [
  "wine_key",
  "producer_name",
  "cuvee_name",
  "vintage",
  "appellation_name",
  "color",
  "location_id",
  "qty",
  "purchase_price_eur",
  "purchase_source",
  "notes",
] as const;

function tsToIso(ts: Date | number | null | undefined): string | null {
  if (ts === null || ts === undefined) return null;
  const d = ts instanceof Date ? ts : new Date(ts * 1000);
  return d.toISOString().slice(0, 10);
}

export async function GET() {
  const rows = await db
    .select({
      wineKey: cellarInventory.wineKey,
      producerName: dimProducer.producerName,
      cuveeName: dimWine.cuveeName,
      vintage: dimWine.vintage,
      appellationName: dimAppellation.appellationName,
      color: dimWine.color,
      locationId: cellarInventory.locationId,
      qty: cellarInventory.qty,
      purchasePriceEur: cellarInventory.purchasePriceEur,
      purchaseDate: cellarInventory.purchaseDate,
      purchaseSource: cellarInventory.purchaseSource,
      notes: cellarInventory.notes,
    })
    .from(cellarInventory)
    .innerJoin(dimWine, eq(cellarInventory.wineKey, dimWine.wineKey))
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .orderBy(asc(cellarInventory.locationId), asc(dimProducer.producerName), asc(dimWine.cuveeName));

  const header = [...HEADER, "purchase_date"];
  const csvRows: Array<Array<string | number | null>> = [Array.from(header)];
  for (const r of rows) {
    csvRows.push([
      r.wineKey,
      r.producerName,
      r.cuveeName,
      r.vintage,
      r.appellationName,
      r.color,
      r.locationId,
      r.qty,
      r.purchasePriceEur,
      r.purchaseSource,
      r.notes,
      tsToIso(r.purchaseDate),
    ]);
  }
  const csv = csvStringify(csvRows);
  const today = new Date().toISOString().slice(0, 10);

  return new NextResponse(csv, {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="achilles-cellar-${today}.csv"`,
    },
  });
}
