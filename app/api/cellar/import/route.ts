import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import {
  cellarInventory,
  cellarLocations,
  dimWine,
  dimProducer,
  dimAppellation,
} from "@/db/schema";
import { eq, and, sql } from "drizzle-orm";
import { csvParse } from "@/lib/csv";
import { normText, expandProducerPrefix } from "@/lib/identity";

interface ImportRow {
  rowNum: number;
  wineKey?: string;
  producerName?: string;
  cuveeName?: string;
  vintage?: number;
  appellationName?: string;
  locationId: number;
  qty: number;
  purchasePriceEur?: number;
  purchaseSource?: string;
  notes?: string;
  purchaseDate?: Date;
}

interface RejectedRow {
  row: number;
  reason: string;
  data?: Record<string, unknown>;
}

function parseNum(v: string | undefined): number | undefined {
  if (v === undefined || v === "") return undefined;
  const n = Number(v.replace(",", "."));
  return Number.isFinite(n) ? n : undefined;
}

function parseInt10(v: string | undefined): number | undefined {
  if (v === undefined || v === "") return undefined;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : undefined;
}

function parseDate(v: string | undefined): Date | undefined {
  if (!v) return undefined;
  const d = new Date(v);
  return Number.isFinite(d.getTime()) ? d : undefined;
}

async function resolveWineKey(
  row: ImportRow,
): Promise<{ wineKey: string } | { error: string }> {
  if (row.wineKey) {
    const found = await db
      .select({ wineKey: dimWine.wineKey })
      .from(dimWine)
      .where(eq(dimWine.wineKey, row.wineKey))
      .limit(1);
    if (found.length === 0) return { error: `wine_key_not_found: ${row.wineKey}` };
    return { wineKey: found[0].wineKey };
  }

  if (!row.producerName || !row.cuveeName) {
    return { error: "wine_key or (producer_name + cuvee_name) required" };
  }
  const producerNorm = expandProducerPrefix(normText(row.producerName));
  const cuveeNorm = normText(row.cuveeName);

  const conds = [
    eq(dimProducer.producerNorm, producerNorm),
    eq(dimWine.cuveeNorm, cuveeNorm),
  ];
  if (row.vintage !== undefined) {
    conds.push(eq(dimWine.vintage, row.vintage));
  }
  if (row.appellationName) {
    const appNorm = normText(row.appellationName);
    conds.push(eq(dimAppellation.appellationNorm, appNorm));
  }

  const matches = await db
    .select({ wineKey: dimWine.wineKey })
    .from(dimWine)
    .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .where(and(...conds))
    .limit(2);

  if (matches.length === 0) {
    return { error: `wine_not_found: ${row.producerName} / ${row.cuveeName}${row.vintage ? ` / ${row.vintage}` : ""}` };
  }
  if (matches.length > 1) {
    return { error: `ambiguous_match (${matches.length} candidates) — specify wine_key or appellation` };
  }
  return { wineKey: matches[0].wineKey };
}

export async function POST(req: NextRequest) {
  const contentType = req.headers.get("content-type") ?? "";
  let csvText = "";
  if (contentType.includes("text/csv") || contentType.includes("text/plain")) {
    csvText = await req.text();
  } else if (contentType.includes("multipart/form-data")) {
    const form = await req.formData();
    const file = form.get("file");
    if (file && typeof file !== "string") {
      csvText = await file.text();
    }
  } else {
    csvText = await req.text();
  }

  if (!csvText.trim()) {
    return NextResponse.json({ error: "empty_csv" }, { status: 400 });
  }
  if (csvText.length > 5 * 1024 * 1024) {
    return NextResponse.json({ error: "csv_too_large" }, { status: 413 });
  }

  const matrix = csvParse(csvText);
  if (matrix.length < 2) {
    return NextResponse.json({ error: "csv_has_no_data_rows" }, { status: 400 });
  }

  const header = matrix[0].map((h) => h.trim().toLowerCase());
  const idx = (name: string) => header.indexOf(name);
  const colWineKey = idx("wine_key");
  const colProducer = idx("producer_name");
  const colCuvee = idx("cuvee_name");
  const colVintage = idx("vintage");
  const colAppellation = idx("appellation_name");
  const colLocation = idx("location_id");
  const colQty = idx("qty");
  const colPrice = idx("purchase_price_eur");
  const colSource = idx("purchase_source");
  const colNotes = idx("notes");
  const colDate = idx("purchase_date");

  if (colLocation === -1 || colQty === -1) {
    return NextResponse.json(
      { error: "missing_required_columns: location_id, qty" },
      { status: 400 },
    );
  }

  // Load locations once for capacity check
  const locations = await db.select().from(cellarLocations);
  const locationById = new Map(locations.map((l) => [l.locationId, l]));

  // Current usage per location (running totals)
  const usageRows = await db
    .select({
      locationId: cellarInventory.locationId,
      qty: sql<number>`coalesce(sum(${cellarInventory.qty}), 0)`,
    })
    .from(cellarInventory)
    .groupBy(cellarInventory.locationId);
  const usageByLoc = new Map<number, number>();
  for (const u of usageRows) usageByLoc.set(u.locationId, Number(u.qty));

  const rejected: RejectedRow[] = [];
  let inserted = 0;
  let merged = 0;

  for (let i = 1; i < matrix.length; i++) {
    const cells = matrix[i];
    const rowNum = i + 1;
    const locationId = colLocation >= 0 ? parseInt10(cells[colLocation]) : undefined;
    const qty = colQty >= 0 ? parseInt10(cells[colQty]) : undefined;
    if (locationId === undefined || qty === undefined || qty <= 0) {
      rejected.push({ row: rowNum, reason: "invalid_location_or_qty" });
      continue;
    }
    const loc = locationById.get(locationId);
    if (!loc) {
      rejected.push({ row: rowNum, reason: `location_not_found: ${locationId}` });
      continue;
    }
    const used = usageByLoc.get(locationId) ?? 0;
    if (used + qty > loc.capacity) {
      rejected.push({
        row: rowNum,
        reason: `capacity_exceeded: ${used}+${qty} > ${loc.capacity} for location ${locationId}`,
      });
      continue;
    }

    const importRow: ImportRow = {
      rowNum,
      wineKey: colWineKey >= 0 ? cells[colWineKey]?.trim() || undefined : undefined,
      producerName: colProducer >= 0 ? cells[colProducer]?.trim() || undefined : undefined,
      cuveeName: colCuvee >= 0 ? cells[colCuvee]?.trim() || undefined : undefined,
      vintage: colVintage >= 0 ? parseInt10(cells[colVintage]) : undefined,
      appellationName: colAppellation >= 0 ? cells[colAppellation]?.trim() || undefined : undefined,
      locationId,
      qty,
      purchasePriceEur: colPrice >= 0 ? parseNum(cells[colPrice]) : undefined,
      purchaseSource: colSource >= 0 ? cells[colSource]?.trim() || undefined : undefined,
      notes: colNotes >= 0 ? cells[colNotes]?.trim() || undefined : undefined,
      purchaseDate: colDate >= 0 ? parseDate(cells[colDate]) : undefined,
    };

    const resolved = await resolveWineKey(importRow);
    if ("error" in resolved) {
      rejected.push({ row: rowNum, reason: resolved.error });
      continue;
    }
    const wineKey = resolved.wineKey;

    // Upsert by (wine_key, location_id)
    const existing = await db
      .select()
      .from(cellarInventory)
      .where(
        and(eq(cellarInventory.wineKey, wineKey), eq(cellarInventory.locationId, locationId)),
      )
      .limit(1);

    if (existing.length > 0) {
      await db
        .update(cellarInventory)
        .set({ qty: existing[0].qty + qty })
        .where(eq(cellarInventory.inventoryId, existing[0].inventoryId));
      merged++;
    } else {
      await db.insert(cellarInventory).values({
        wineKey,
        locationId,
        qty,
        purchasePriceEur: importRow.purchasePriceEur ?? null,
        purchaseDate: importRow.purchaseDate ?? null,
        purchaseSource: importRow.purchaseSource ?? null,
        notes: importRow.notes ?? null,
      });
      inserted++;
    }
    usageByLoc.set(locationId, used + qty);
  }

  return NextResponse.json({
    accepted: inserted + merged,
    inserted,
    merged,
    rejected: rejected.length,
    rejections: rejected.slice(0, 50),
    totalRows: matrix.length - 1,
  });
}
