import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { VintageHeatmap, type HeatmapLabels } from "@/components/VintageHeatmap";
import { VintageDivergenceHeatmap, type DivergenceLabels } from "@/components/VintageDivergenceHeatmap";
import { getVintageHeatmap, getVintageDivergence } from "@/lib/queries/vintages";

export const dynamic = "force-dynamic";

export default async function VintagesPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("vintages");

  const [{ cells, regions, years }, divergenceCells] = await Promise.all([
    getVintageHeatmap(),
    getVintageDivergence(),
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
