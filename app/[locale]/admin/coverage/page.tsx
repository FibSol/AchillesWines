import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { Target } from "lucide-react";
import { getCoverageData } from "@/lib/queries/ops";

export const dynamic = "force-dynamic";

function GaugeBar({ pct }: { pct: number }) {
  const color =
    pct >= 60
      ? "bg-[color:var(--color-success)]"
      : pct >= 40
        ? "bg-[color:var(--color-warning)]"
        : "bg-[color:var(--color-danger)]";
  return (
    <div className="relative h-6 w-full rounded-full bg-[color:var(--color-surface-muted)] overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${color}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
      <span className="absolute inset-0 flex items-center justify-center text-sm font-bold text-[color:var(--color-fg)]">
        {pct}%
      </span>
    </div>
  );
}

export default async function AdminCoveragePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("adminCoverage");

  const {
    total,
    withCuvee,
    withMultiPrice,
    withMultiRating,
    coverageScorePct,
    tierMap,
    regionBreakdown,
  } = await getCoverageData();

  const notable = tierMap["notable"] ?? 0;
  const mid = tierMap["mid"] ?? 0;
  const longTail = tierMap["long_tail"] ?? 0;

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="ADR-013">
      <div className="space-y-10">
        {/* Coverage score gauge */}
        <div className="glass-card p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-[color:var(--color-fg)]">
              {t("scoreLabel")}
            </h2>
            <span className="text-sm text-[color:var(--color-fg-muted)]">
              {t("targetLabel")}
            </span>
          </div>
          <GaugeBar pct={coverageScorePct} />
          <p className="text-xs text-[color:var(--color-fg-subtle)]">
            ({withCuvee} + {withMultiPrice} + {withMultiRating}) ÷ (3 × {total}) = {coverageScorePct}%
          </p>
        </div>

        {/* KPI stat cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="stat-card">
            <div className="stat-card-value">{total.toLocaleString()}</div>
            <div className="stat-card-label">{t("totalProducers")}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-value">{withCuvee.toLocaleString()}</div>
            <div className="stat-card-label">{t("withCuvees")}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-value">{withMultiPrice.toLocaleString()}</div>
            <div className="stat-card-label">{t("multiPrice")}</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-value">{withMultiRating.toLocaleString()}</div>
            <div className="stat-card-label">{t("multiRating")}</div>
          </div>
        </div>

        {/* Coverage tier breakdown */}
        <div className="glass-card p-6 space-y-4">
          <h2 className="text-lg font-semibold text-[color:var(--color-fg)] flex items-center gap-2">
            <Target className="w-5 h-5 text-[color:var(--color-primary)]" />
            {t("tierBreakdownTitle")}
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <div className="rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] p-4 text-center">
              <div className="text-2xl font-bold text-[color:var(--color-accent)]">
                {notable.toLocaleString()}
              </div>
              <div className="text-xs text-[color:var(--color-fg-muted)] mt-1">{t("tierNotable")}</div>
            </div>
            <div className="rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] p-4 text-center">
              <div className="text-2xl font-bold text-[color:var(--color-fg)]">
                {mid.toLocaleString()}
              </div>
              <div className="text-xs text-[color:var(--color-fg-muted)] mt-1">{t("tierMid")}</div>
            </div>
            <div className="rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-bg-elevated)] p-4 text-center">
              <div className="text-2xl font-bold text-[color:var(--color-fg-subtle)]">
                {longTail.toLocaleString()}
              </div>
              <div className="text-xs text-[color:var(--color-fg-muted)] mt-1">{t("tierLongTail")}</div>
            </div>
          </div>
        </div>

        {/* Per-region breakdown table */}
        <div className="glass-card p-6 space-y-4">
          <h2 className="text-lg font-semibold text-[color:var(--color-fg)]">
            {t("regionBreakdown")}
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[color:var(--color-border)] text-left text-[color:var(--color-fg-muted)]">
                  <th className="pb-2 pr-4 font-medium">{t("region")}</th>
                  <th className="pb-2 pr-4 font-medium text-right">{t("colTotal")}</th>
                  <th className="pb-2 pr-4 font-medium text-right">{t("colCuvees")}</th>
                  <th className="pb-2 pr-4 font-medium text-right">{t("colPrices")}</th>
                  <th className="pb-2 font-medium text-right">{t("colRatings")}</th>
                </tr>
              </thead>
              <tbody>
                {regionBreakdown.map((row, i) => (
                  <tr
                    key={i}
                    className="border-b border-[color:var(--color-border)] hover:bg-[color:var(--color-surface-muted)] transition-colors"
                  >
                    <td className="py-2 pr-4 text-[color:var(--color-fg)]">
                      {row.region ?? "—"}
                    </td>
                    <td className="py-2 pr-4 text-right text-[color:var(--color-fg-muted)]">
                      {row.total}
                    </td>
                    <td className="py-2 pr-4 text-right text-[color:var(--color-fg-muted)]">
                      {row.withCuvee}
                    </td>
                    <td className="py-2 pr-4 text-right text-[color:var(--color-accent)]">
                      {row.withPrice}
                    </td>
                    <td className="py-2 text-right text-[color:var(--color-primary)]">
                      {row.withRating}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
