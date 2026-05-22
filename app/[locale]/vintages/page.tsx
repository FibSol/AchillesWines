import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimWine, dimAppellation, factVintageRating } from "@/db/schema";
import { eq, isNotNull, gte, and, sql } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { VintageHeatmap, type VintageCell, type HeatmapLabels } from "@/components/VintageHeatmap";

export const dynamic = "force-dynamic";

async function getHeatmapData(): Promise<{
  cells: VintageCell[];
  regions: string[];
  years: number[];
}> {
  try {
    // Wine counts per (region, vintage) from the producer registry
    const wineCounts = await db
      .select({
        region: dimAppellation.region,
        vintage: dimWine.vintage,
        wineCount: sql<number>`cast(count(*) as integer)`,
      })
      .from(dimWine)
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .where(and(isNotNull(dimWine.vintage), gte(dimWine.vintage, 1980)))
      .groupBy(dimAppellation.region, dimWine.vintage);

    // Vintage scores from fact_vintage_rating (may be empty until scrapers run)
    const vintageScores = await db
      .select({
        region: factVintageRating.region,
        vintage: factVintageRating.vintage,
        avgScore: sql<number>`avg(${factVintageRating.scoreNormalized100})`,
      })
      .from(factVintageRating)
      .where(gte(factVintageRating.vintage, 1980))
      .groupBy(factVintageRating.region, factVintageRating.vintage);

    const scoreMap = new Map<string, number>();
    for (const s of vintageScores) {
      scoreMap.set(`${s.region}|${s.vintage}`, Number(s.avgScore));
    }

    const cellMap = new Map<string, VintageCell>();

    // Cells from wine counts
    for (const r of wineCounts) {
      if (r.vintage === null || !r.region) continue;
      const key = `${r.region}|${r.vintage}`;
      cellMap.set(key, {
        region: r.region,
        vintage: r.vintage,
        wineCount: Number(r.wineCount),
        avgScore: scoreMap.get(key) ?? null,
      });
    }

    // Additional cells from vintage scores with no wines
    for (const s of vintageScores) {
      const key = `${s.region}|${s.vintage}`;
      if (!cellMap.has(key)) {
        cellMap.set(key, {
          region: s.region,
          vintage: s.vintage,
          wineCount: 0,
          avgScore: Number(s.avgScore),
        });
      }
    }

    const cells = Array.from(cellMap.values());
    if (cells.length === 0) return { cells: [], regions: [], years: [] };

    const yearsSet = new Set(cells.map((c) => c.vintage));
    const years = Array.from(yearsSet).sort((a, b) => a - b);

    const regionTotals = new Map<string, number>();
    for (const c of cells) {
      regionTotals.set(c.region, (regionTotals.get(c.region) ?? 0) + c.wineCount);
    }
    const regions = Array.from(regionTotals.keys()).sort(
      (a, b) => (regionTotals.get(b) ?? 0) - (regionTotals.get(a) ?? 0)
    );

    return { cells, regions, years };
  } catch {
    return { cells: [], regions: [], years: [] };
  }
}

export default async function VintagesPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("vintages");
  const tConf = await getTranslations("confidence");

  const { cells, regions, years } = await getHeatmapData();

  const labels: HeatmapLabels = {
    noData: t("noData"),
    scoreLabel: t("scoreLabel"),
    clickToExplore: t("clickToExplore"),
    loadingWines: t("loadingWines"),
    noWines: t("noWines"),
    chartTitle: t("chartTitle"),
    confidence: {
      verified: tConf.raw("verified") as string,
      reviewed: tConf("reviewed"),
      needs_review: tConf("needs_review"),
    },
  };

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="Sprint 4 · P1">
      <VintageHeatmap cells={cells} regions={regions} years={years} labels={labels} />
    </PageShell>
  );
}
