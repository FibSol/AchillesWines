import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimProducer, dimAppellation } from "@/db/schema";
import { isNotNull, isNull, inArray, or, and } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { WineMapLoader } from "@/components/WineMapLoader";
import { TierFilter } from "@/components/TierFilter";
import { DEFAULT_TIERS } from "@/lib/map-tiers";
import type { ProducerPin, AppellationOverlay } from "@/components/WineMap";
import { Suspense } from "react";

export const dynamic = "force-dynamic";

function parseTiers(raw: string | string[] | undefined): {
  numeric: number[];
  includeNull: boolean;
} {
  const str = Array.isArray(raw) ? raw[0] : (raw ?? DEFAULT_TIERS.join(","));
  const parts = str.split(",").map((s) => s.trim()).filter(Boolean);
  const numeric = parts
    .filter((p) => p !== "null")
    .map(Number)
    .filter((n) => !isNaN(n) && n >= 1 && n <= 5);
  const includeNull = parts.includes("null");
  return { numeric, includeNull };
}

export default async function MapPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;
  const sp = await searchParams;
  setRequestLocale(locale);
  const t = await getTranslations("map");

  const { numeric, includeNull } = parseTiers(sp.tiers);
  const selectedKeys = [
    ...numeric.map(String),
    ...(includeNull ? ["null"] : []),
  ];

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

  const badge =
    producers.length > 0
      ? `${producers.length} ${t("legendProducers").toLowerCase()} · ${appellations.length} ${t("legendAppellations").toLowerCase()}`
      : "Sprint 3 · P1";

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge={badge}>
      <Suspense>
        <TierFilter selected={selectedKeys} />
      </Suspense>
      <WineMapLoader
        producers={producers}
        appellations={appellations}
        locale={locale}
        labels={{
          noData: t("noData"),
          legendProducers: t("legendProducers"),
          legendAppellations: t("legendAppellations"),
          legendRegions: t("legendRegions"),
        }}
      />
    </PageShell>
  );
}
