import { NextResponse } from "next/server";
import { csvStringify } from "@/lib/csv";

export async function GET() {
  const csv = csvStringify([
    [
      "producer_name",
      "country_code",
      "region",
      "subregion",
      "tier",
      "status",
      "website",
      "latitude",
      "longitude",
      "allowed_appellations",
      "aliases",
      "notes",
    ],
    [
      "Domaine Coche-Dury",
      "FR",
      "Bourgogne",
      "Côte de Beaune",
      1,
      "active",
      "https://example.com",
      46.97,
      4.79,
      "Meursault; Corton-Charlemagne; Meursault Perrières",
      "Coche-Dury; Coche Dury",
      "Imported from registry",
    ],
  ]);
  return new NextResponse(csv, {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="achilles-producers-template.csv"',
    },
  });
}
