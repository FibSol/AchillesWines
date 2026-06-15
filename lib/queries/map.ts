import { db } from "@/db";
import { dimProducer, dimAppellation } from "@/db/schema";
import { isNotNull, isNull, inArray, or, and } from "drizzle-orm";
import { DEFAULT_TIERS } from "@/lib/map-tiers";
import type { ProducerPin, AppellationOverlay } from "@/components/WineMap";

export interface ParsedTiers {
  numeric: number[];
  includeNull: boolean;
}

export interface MapData {
  producers: ProducerPin[];
  appellations: AppellationOverlay[];
}

export function parseTiers(raw: string | string[] | undefined): ParsedTiers {
  const str = Array.isArray(raw) ? raw[0] : (raw ?? DEFAULT_TIERS.join(","));
  const parts = str.split(",").map((s) => s.trim()).filter(Boolean);
  const numeric = parts
    .filter((p) => p !== "null")
    .map(Number)
    .filter((n) => !isNaN(n) && n >= 1 && n <= 5);
  const includeNull = parts.includes("null");
  return { numeric, includeNull };
}

/**
 * Geo data for the wine map: producer pins (filtered by tier) and appellation
 * overlays (polygons/points). Shared by the map page (SSR) and GET /api/map.
 */
export async function getMapData({ numeric, includeNull }: ParsedTiers): Promise<MapData> {
  // Build tier WHERE clause
  const tierClauses = [];
  if (numeric.length > 0) tierClauses.push(inArray(dimProducer.tier, numeric));
  if (includeNull) tierClauses.push(isNull(dimProducer.tier));
  const tierWhere =
    tierClauses.length === 0
      ? isNull(dimProducer.producerKey) // nothing selected → empty
      : tierClauses.length === 1
      ? tierClauses[0]
      : or(...tierClauses);

  const [rawProducers, rawAppellations] = await Promise.all([
    db
      .select({
        producerKey: dimProducer.producerKey,
        producerName: dimProducer.producerName,
        region: dimProducer.region,
        subregion: dimProducer.subregion,
        latitude: dimProducer.latitude,
        longitude: dimProducer.longitude,
        tier: dimProducer.tier,
      })
      .from(dimProducer)
      .where(and(isNotNull(dimProducer.latitude), tierWhere)),
    db
      .select({
        appellationKey: dimAppellation.appellationKey,
        appellationName: dimAppellation.appellationName,
        region: dimAppellation.region,
        level: dimAppellation.level,
        geoPolygon: dimAppellation.geoPolygon,
        latitude: dimAppellation.latitude,
        longitude: dimAppellation.longitude,
      })
      .from(dimAppellation)
      .where(
        or(
          isNotNull(dimAppellation.geoPolygon),
          isNotNull(dimAppellation.latitude)
        )
      ),
  ]);

  const producers = rawProducers.filter(
    (p): p is ProducerPin => p.latitude != null && p.longitude != null
  );
  const appellations = rawAppellations as AppellationOverlay[];

  return { producers, appellations };
}
