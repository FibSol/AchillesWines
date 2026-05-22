import { NextResponse } from "next/server";
import { db } from "@/db";
import { dimProducer } from "@/db/schema";
import { asc } from "drizzle-orm";
import { csvStringify } from "@/lib/csv";

const HEADER = [
  "producer_name",
  "country_code",
  "region",
  "subregion",
  "tier",
  "status",
  "website",
  "latitude",
  "longitude",
  // Semicolon-separated lists — round-trip via /import.
  "allowed_appellations",
  "aliases",
  "notes",
] as const;

export async function GET() {
  const rows = await db
    .select()
    .from(dimProducer)
    .orderBy(asc(dimProducer.countryCode), asc(dimProducer.region), asc(dimProducer.producerName));

  const csvRows: Array<Array<string | number | null>> = [Array.from(HEADER)];
  for (const r of rows) {
    csvRows.push([
      r.producerName,
      r.countryCode,
      r.region,
      r.subregion,
      r.tier,
      r.status,
      r.website,
      r.latitude,
      r.longitude,
      (r.allowedAppellations ?? []).join("; "),
      (r.aliases ?? []).join("; "),
      r.notes,
    ]);
  }
  const csv = csvStringify(csvRows);
  const today = new Date().toISOString().slice(0, 10);
  return new NextResponse(csv, {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": `attachment; filename="achilles-producers-${today}.csv"`,
    },
  });
}
