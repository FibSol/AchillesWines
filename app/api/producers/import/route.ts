import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { dimProducer } from "@/db/schema";
import { eq, and } from "drizzle-orm";
import { csvParse } from "@/lib/csv";
import { normText, expandProducerPrefix } from "@/lib/identity";

interface Rejected {
  row: number;
  reason: string;
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

function splitList(v: string | undefined): string[] {
  if (!v) return [];
  return v
    .split(/[;|]/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

const STATUS_VALUES = new Set(["active", "pending_review", "deprecated"]);

export async function POST(req: NextRequest) {
  const contentType = req.headers.get("content-type") ?? "";
  let csvText = "";
  if (contentType.includes("multipart/form-data")) {
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
  const cName = idx("producer_name");
  const cCountry = idx("country_code");
  const cRegion = idx("region");
  const cSubregion = idx("subregion");
  const cTier = idx("tier");
  const cStatus = idx("status");
  const cWebsite = idx("website");
  const cLat = idx("latitude");
  const cLon = idx("longitude");
  const cAllowed = idx("allowed_appellations");
  const cAliases = idx("aliases");
  const cNotes = idx("notes");

  if (cName === -1 || cCountry === -1) {
    return NextResponse.json(
      { error: "missing_required_columns: producer_name, country_code" },
      { status: 400 },
    );
  }

  const rejected: Rejected[] = [];
  let inserted = 0;
  let updated = 0;

  for (let i = 1; i < matrix.length; i++) {
    const cells = matrix[i];
    const rowNum = i + 1;
    const producerName = cells[cName]?.trim();
    const countryCode = cells[cCountry]?.trim().toUpperCase();

    if (!producerName) {
      rejected.push({ row: rowNum, reason: "producer_name required" });
      continue;
    }
    if (!countryCode) {
      rejected.push({ row: rowNum, reason: "country_code required" });
      continue;
    }

    const producerNorm = expandProducerPrefix(normText(producerName));
    if (!producerNorm) {
      rejected.push({ row: rowNum, reason: "producer_norm empty after normalization" });
      continue;
    }

    const statusRaw = cStatus >= 0 ? cells[cStatus]?.trim() : "";
    const status = statusRaw && STATUS_VALUES.has(statusRaw)
      ? (statusRaw as "active" | "pending_review" | "deprecated")
      : "active";
    if (statusRaw && !STATUS_VALUES.has(statusRaw)) {
      rejected.push({
        row: rowNum,
        reason: `invalid status "${statusRaw}" (expected: ${[...STATUS_VALUES].join("|")})`,
      });
      continue;
    }

    const allowedAppellations = cAllowed >= 0
      ? splitList(cells[cAllowed]).map((a) => normText(a))
      : [];
    const aliases = cAliases >= 0 ? splitList(cells[cAliases]) : [];

    const tierVal = cTier >= 0 ? parseInt10(cells[cTier]) : undefined;
    const latVal = cLat >= 0 ? parseNum(cells[cLat]) : undefined;
    const lonVal = cLon >= 0 ? parseNum(cells[cLon]) : undefined;

    const row = {
      producerName,
      producerNorm,
      countryCode,
      region: cRegion >= 0 ? cells[cRegion]?.trim() || null : null,
      subregion: cSubregion >= 0 ? cells[cSubregion]?.trim() || null : null,
      tier: tierVal ?? null,
      status,
      website: cWebsite >= 0 ? cells[cWebsite]?.trim() || null : null,
      latitude: latVal ?? null,
      longitude: lonVal ?? null,
      allowedAppellations,
      aliases,
      notes: cNotes >= 0 ? cells[cNotes]?.trim() || null : null,
    };

    try {
      const existing = await db
        .select({ producerKey: dimProducer.producerKey })
        .from(dimProducer)
        .where(
          and(
            eq(dimProducer.producerNorm, producerNorm),
            eq(dimProducer.countryCode, countryCode),
          ),
        )
        .limit(1);

      if (existing.length > 0) {
        await db
          .update(dimProducer)
          .set({
            producerName: row.producerName,
            region: row.region,
            subregion: row.subregion,
            tier: row.tier,
            status: row.status,
            website: row.website,
            latitude: row.latitude,
            longitude: row.longitude,
            allowedAppellations: row.allowedAppellations,
            aliases: row.aliases,
            notes: row.notes,
          })
          .where(eq(dimProducer.producerKey, existing[0].producerKey));
        updated++;
      } else {
        await db.insert(dimProducer).values(row);
        inserted++;
      }
    } catch (e) {
      rejected.push({ row: rowNum, reason: `db_error: ${(e as Error).message}` });
    }
  }

  return NextResponse.json({
    accepted: inserted + updated,
    inserted,
    merged: updated,
    rejected: rejected.length,
    rejections: rejected.slice(0, 50),
    totalRows: matrix.length - 1,
  });
}
