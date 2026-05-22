import { NextResponse } from "next/server";
import { csvStringify } from "@/lib/csv";

export async function GET() {
  const csv = csvStringify([
    [
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
      "purchase_date",
    ],
    // Example row — fill wine_key from /domaines/[id] or leave blank and use producer + cuvee + vintage
    [
      "abc1234567890def",
      "Domaine Coche-Dury",
      "Meursault Perrières 1er Cru",
      2020,
      "Meursault",
      "white",
      1,
      6,
      280.0,
      "Millesima",
      "Cave principale rang B",
      "2024-09-15",
    ],
  ]);

  return new NextResponse(csv, {
    status: 200,
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="achilles-cellar-template.csv"',
    },
  });
}
