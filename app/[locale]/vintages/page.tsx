import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimWine, dimAppellation, factVintageRating, factRating } from "@/db/schema";
import { eq, isNotNull, gte, lte, and, sql } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { VintageHeatmap, type VintageCell, type HeatmapLabels } from "@/components/VintageHeatmap";
import { VintageDivergenceHeatmap, type DivergenceCell, type DivergenceLabels } from "@/components/VintageDivergenceHeatmap";

export const dynamic = "force-dynamic";

async function getDivergenceData(): Promise<DivergenceCell[]> {
  try {
    const rows = await db
      .select({
        year: dimWine.vintage,
        critic: factRating.criticCode,
        avg: sql<number>`round(avg(${factRating.scoreNormalized100}), 1)`,
        count: sql<number>`cast(count(*) as integer)`,
        divergence: sql<number>`round(
          sqrt(
            max(0,
              avg(${factRating.scoreNormalized100} * ${factRating.scoreNormalized100})
              - avg(${factRating.scoreNormalized100}) * avg(${factRating.scoreNormalized100})
            )
          ),
          1
        )`,
      })
      .from(factRating)
      .innerJoin(dimWine, eq(factRating.wineKey, dimWine.wineKey))
      .where(
        and(
          isNotNull(dimWine.vintage),
          gte(dimWine.vintage, 1990),
          lte(dimWine.vintage, 2024),
        )
      )
      .groupBy(dimWine.vintage, factRating.criticCode)
      .having(sql`count(*) >= 3`);

    return rows
      .filter((r) => r.year !== null)
      .map((r) => ({
        year: r.year as number,
        critic: r.critic,
        avg: Number(r.avg),
        count: Number(r.count),
        divergence: Number(r.divergence),
      }));
  } catch {
    return [];
  }
}

async function getHeatmapData(): Promise<{
  cells: VintageCell[];
  regions: string[];
  years: number[];
}> {
  try {
    // Wine counts per (region, vintage) from the producer registry
    const wineCounts = await db
      .select({
        countryCode: dimAppellation.countryCode,
        region: dimAppellation.region,
        vintage: dimWine.vintage,
        wineCount: sql<number>`cast(count(*) as integer)`,
      })
      .from(dimWine)
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .where(and(isNotNull(dimWine.vintage), gte(dimWine.vintage, 1980)))
      .groupBy(dimAppellation.countryCode, dimAppellation.region, dimWine.vintage);

    // Vintage scores from fact_vintage_rating
    const vintageScores = await db
      .select({
        countryCode: factVintageRating.countryCode,
        region: factVintageRating.region,
        vintage: factVintageRating.vintage,
        avgScore: sql<number>`avg(${factVintageRating.scoreNormalized100})`,
      })
      .from(factVintageRating)
      .where(gte(factVintageRating.vintage, 1980))
      .groupBy(factVintageRating.countryCode, factVintageRating.region, factVintageRating.vintage);

    const scoreMap = new Map<string, { score: number; countryCode: string }>();
    for (const s of vintageScores) {
      scoreMap.set(`${s.region}|${s.vintage}`, {
        score: Number(s.avgScore),
        countryCode: s.countryCode,
      });
    }

    const cellMap = new Map<string, VintageCell>();

    // Cells from wine counts
    for (const r of wineCounts) {
      if (r.vintage === null || !r.region) continue;
      const key = `${r.region}|${r.vintage}`;
      const sc = scoreMap.get(key);
      cellMap.set(key, {
        region: r.region,
        countryCode: r.countryCode ?? sc?.countryCode ?? "??",
        vintage: r.vintage,
        wineCount: Number(r.wineCount),
        avgScore: sc?.score ?? null,
      });
    }

    // Additional cells from vintage scores with no wines
    for (const s of vintageScores) {
      const key = `${s.region}|${s.vintage}`;
      if (!cellMap.has(key)) {
        cellMap.set(key, {
          region: s.region,
          countryCode: s.countryCode,
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

  const [{ cells, regions, years }, divergenceCells] = await Promise.all([
    getHeatmapData(),
    getDivergenceData(),
  ]);

  const labels: HeatmapLabels = {
    noData: t("noData"),
    scoreLabel: t("scoreLabel"),
    clickToExplore: t("clickToExplore"),
    densityLabel: t("densityLabel"),
    tiers: {
      t1: t("tiers.t1"),
      t2: t("tiers.t2"),
      t3: t("tiers.t3"),
      t4: t("tiers.t4"),
      t5: t("tiers.t5"),
    },
  };

  const divergenceLabels: DivergenceLabels = {
    title: t("divergenceTitle"),
    subtitle: t("divergenceSubtitle"),
    legend: t("divergenceLegend"),
    tooltipYear: t("divergenceTooltipYear"),
    tooltipCritic: t("divergenceTooltipCritic"),
    tooltipAvg: t("divergenceTooltipAvg"),
    tooltipCount: t("divergenceTooltipCount"),
    tooltipDivergence: t("divergenceTooltipDivergence"),
    noData: t("noData"),
  };

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="Sprint 4 · P1">
      <VintageHeatmap cells={cells} regions={regions} years={years} labels={labels} />

      {/* Divergence heatmap — score by critic × vintage */}
      <section className="mt-10 space-y-3">
        <div>
          <h2 className="text-lg font-semibold text-[rgba(250,247,245,0.92)] tracking-tight">
            {t("divergenceTitle")}
          </h2>
        </div>
        <VintageDivergenceHeatmap cells={divergenceCells} labels={divergenceLabels} />
      </section>
    </PageShell>
  );
}
