import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import Link from "next/link";
import { PageShell } from "@/components/page-shell";
import { ConfidenceBadge, deriveConfidence } from "@/components/ConfidenceBadge";
import { CuveeEvolutionChart } from "@/components/DomaineCharts";
import { DomaineDetailTable } from "@/components/DomaineDetailTable";
import { SimilarWines } from "@/components/SimilarWines";
import { ArrowLeft, MapPin, Globe, Grape, Award } from "lucide-react";
import { getProducerDetail } from "@/lib/queries/producer-detail";
import { getSimilarWines } from "@/lib/queries/similar";

export const dynamic = "force-dynamic";

/* ─── Sub-components ─────────────────────────────────────────────────────── */

function ColorDot({ color }: { color: string }) {
  const map: Record<string, string> = {
    red: "#A53860",
    white: "#E5B25D",
    "rosé": "#E07898",
    sparkling: "#F5D08C",
    sweet: "#EDC072",
    fortified: "#6E1F3D",
    orange: "#C99440",
  };
  return (
    <span
      className="inline-block size-2 rounded-full shrink-0"
      style={{ background: map[color] ?? "#FAF7F5" }}
    />
  );
}

function CuveeLabel({ name, grandVinLabel }: { name: string; grandVinLabel: string }) {
  if (name) return <>{name}</>;
  return <em style={{ color: "rgba(250,247,245,0.45)", fontStyle: "italic" }}>{grandVinLabel}</em>;
}

function TierBadge({ tier, labels }: { tier: "flagship" | "normal" | "entry"; labels: { flagship: string; normal: string; entry: string } }) {
  const styles = {
    flagship: { background: "rgba(229,178,93,0.18)", color: "#E5B25D", border: "1px solid rgba(229,178,93,0.4)" },
    normal: { background: "rgba(250,247,245,0.08)", color: "rgba(250,247,245,0.7)", border: "1px solid rgba(255,255,255,0.15)" },
    entry: { background: "rgba(255,255,255,0.04)", color: "rgba(250,247,245,0.4)", border: "1px solid rgba(255,255,255,0.08)" },
  };
  return (
    <span
      className="inline-block text-[9px] font-semibold uppercase tracking-[0.08em] px-1.5 py-0.5 rounded-full"
      style={styles[tier]}
    >
      {labels[tier]}
    </span>
  );
}

/* ─── Page ───────────────────────────────────────────────────────────────── */

export default async function DomainePage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("domaine");
  const tCommon = await getTranslations("common");
  const tConf = await getTranslations("confidence");
  const tColors = await getTranslations("colors");
  const tSim = await getTranslations("similarity");

  const producerKey = Number.parseInt(id, 10);
  if (!Number.isFinite(producerKey)) notFound();

  const data = await getProducerDetail(producerKey);
  if (!data) notFound();

  const { producer, varieties, cuveeSummaries, cuveeYearPoints, detailRows } = data;

  // Aggregate stats
  const totalVintages = new Set(detailRows.map((r) => r.vintage).filter(Boolean)).size;
  const allRatings = detailRows.flatMap((r) => (r.bestRating !== null ? [r.bestRating] : []));
  const globalBestRating = allRatings.length > 0 ? Math.max(...allRatings) : null;
  const allPrices = detailRows.flatMap((r) =>
    r.priceMin !== null ? [r.priceMin] : [],
  );
  const globalPriceMin = allPrices.length > 0 ? Math.min(...allPrices) : null;
  const allPricesMax = detailRows.flatMap((r) =>
    r.priceMax !== null ? [r.priceMax] : [],
  );
  const globalPriceMax = allPricesMax.length > 0 ? Math.max(...allPricesMax) : null;

  const cuveeNames = cuveeSummaries.map((c) => c.cuveeName);
  const hasVintageData = cuveeYearPoints.length > 0;

  // Load similar wines for the best-rated wine of this producer
  const bestWineKey =
    detailRows.find((r) => r.bestRating !== null)?.wineKey ??
    detailRows[0]?.wineKey ??
    null;
  const similarWines = bestWineKey ? await getSimilarWines(bestWineKey, 10) : [];

  const colorLabels: Record<string, string> = {
    red: tColors("red"),
    white: tColors("white"),
    "rosé": tColors("rosé"),
    sparkling: tColors("sparkling"),
    sweet: tColors("sweet"),
    fortified: tColors("fortified"),
    orange: tColors("orange"),
  };

  const tierLabels = {
    flagship: t("tierFlagship"),
    normal: t("tierNormal"),
    entry: t("tierEntry"),
  };

  const confidenceLabels = {
    verified: tConf.raw("verified") as string,
    reviewed: tConf("reviewed"),
    needs_review: tConf("needs_review"),
  };

  const coverageTierColor: Record<string, string> = {
    notable: "#E5B25D",
    mid: "#E5B25D",
    long_tail: "rgba(250,247,245,0.4)",
  };

  return (
    <PageShell
      title={producer.producerName}
      subtitle={[producer.region, producer.subregion, producer.countryCode].filter(Boolean).join(" · ")}
      badge={
        producer.coverageTier
          ? producer.coverageTier.charAt(0).toUpperCase() + producer.coverageTier.slice(1).replace("_", " ")
          : undefined
      }
    >
      {/* Back link */}
      <div className="flex items-center justify-between mb-6">
        <Link
          href={`/${locale}/domaines`}
          className="inline-flex items-center gap-1.5 text-xs transition-colors"
          style={{ color: "rgba(250,247,245,0.45)" }}
        >
          <ArrowLeft className="size-3.5" strokeWidth={2.5} />
          {t("backToList")}
        </Link>
        {producer.coverageTier && (
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded-full border"
            style={{
              color: coverageTierColor[producer.coverageTier] ?? "rgba(250,247,245,0.5)",
              borderColor: coverageTierColor[producer.coverageTier] ?? "rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.04)",
            }}
          >
            {producer.coverageTier}
          </span>
        )}
      </div>

      {/* ── 1. Info card ──────────────────────────────────────────────────── */}
      <section className="glass-card p-6 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Left: location + website + notes */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm" style={{ color: "rgba(250,247,245,0.65)" }}>
              <MapPin className="size-4 shrink-0" strokeWidth={2.5} />
              <span>
                {producer.region}
                {producer.subregion && ` · ${producer.subregion}`}
                {` · ${producer.countryCode}`}
              </span>
            </div>
            {producer.website && (
              <div className="flex items-center gap-2 text-sm">
                <Globe className="size-4 shrink-0" strokeWidth={2.5} style={{ color: "rgba(250,247,245,0.4)" }} />
                <a
                  href={producer.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="truncate transition-colors"
                  style={{ color: "var(--color-accent)" }}
                >
                  {producer.website.replace(/^https?:\/\//, "")}
                </a>
              </div>
            )}
            {producer.aliases && producer.aliases.length > 0 && (
              <p className="text-xs" style={{ color: "rgba(250,247,245,0.4)" }}>
                <span className="uppercase tracking-[0.06em] mr-2">{t("aliases")}:</span>
                {producer.aliases.join(" · ")}
              </p>
            )}
            {producer.notes && (
              <p className="text-xs leading-relaxed mt-1" style={{ color: "rgba(250,247,245,0.55)" }}>
                {producer.notes}
              </p>
            )}
          </div>

          {/* Center: grape varieties */}
          <div>
            <p
              className="text-[10px] uppercase tracking-[0.08em] mb-2 flex items-center gap-1.5"
              style={{ color: "rgba(250,247,245,0.4)" }}
            >
              <Grape className="size-3.5" strokeWidth={2.5} />
              {t("varieties")}
            </p>
            {varieties.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {varieties.map((v) => (
                  <span
                    key={v.varietyName}
                    className="text-[10px] px-2 py-0.5 rounded-full border"
                    style={{
                      borderColor: "rgba(255,255,255,0.15)",
                      color: "rgba(250,247,245,0.65)",
                      background: "rgba(255,255,255,0.04)",
                    }}
                  >
                    {v.varietyName}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs italic" style={{ color: "rgba(250,247,245,0.3)" }}>
                {tCommon("empty")}
              </p>
            )}
          </div>

          {/* Right: appellations */}
          <div>
            <p
              className="text-[10px] uppercase tracking-[0.08em] mb-2"
              style={{ color: "rgba(250,247,245,0.4)" }}
            >
              {t("allowedAppellations")}
            </p>
            {producer.allowedAppellations && producer.allowedAppellations.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {producer.allowedAppellations.map((app) => (
                  <span key={app} className="badge badge-verified text-[9px] py-0.5" title={app}>
                    {app}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs italic" style={{ color: "rgba(250,247,245,0.3)" }}>
                {tCommon("empty")}
              </p>
            )}
          </div>
        </div>
      </section>

      {/* ── 2. KPI strip ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        {[
          { label: t("cuvees"), value: cuveeSummaries.length },
          { label: t("vintageCount"), value: totalVintages > 0 ? totalVintages : "—" },
          {
            label: t("bestRating"),
            value: globalBestRating !== null ? `${globalBestRating.toFixed(1)}/100` : "—",
          },
          {
            label: t("priceRange"),
            value:
              globalPriceMin !== null && globalPriceMax !== null
                ? globalPriceMin === globalPriceMax
                  ? `€${globalPriceMin.toFixed(0)}`
                  : `€${globalPriceMin.toFixed(0)} – ${globalPriceMax.toFixed(0)}`
                : "—",
          },
        ].map((s) => (
          <div key={s.label} className="stat-card">
            <p className="stat-card-value">{s.value}</p>
            <p className="stat-card-label">{s.label}</p>
          </div>
        ))}
      </div>

      {/* ── 3. Cuvées summary table ───────────────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-xl font-display mb-4" style={{ color: "var(--color-fg)" }}>
          {t("cuvees")}
        </h2>
        {cuveeSummaries.length === 0 ? (
          <div
            className="glass-card p-8 text-center text-sm"
            style={{ color: "rgba(250,247,245,0.4)" }}
          >
            {t("noCuvees")}
          </div>
        ) : (
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                  <tr
                    className="text-left text-[10px] uppercase tracking-[0.06em]"
                    style={{ color: "rgba(250,247,245,0.4)" }}
                  >
                    <th className="px-4 py-3 font-semibold">{t("cuvee")}</th>
                    <th className="px-4 py-3 font-semibold">{tCommon("appellation")}</th>
                    <th className="px-4 py-3 font-semibold">{t("tier")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("vintageCount")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("bestRating")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("priceRange")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("sources")}</th>
                  </tr>
                </thead>
                <tbody>
                  {cuveeSummaries.map((c) => (
                    <tr
                      key={c.cuveeName}
                      className="transition-colors hover:bg-[rgba(165,56,96,0.05)]"
                      style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <ColorDot color={c.color} />
                          <span
                            className="font-semibold text-sm"
                            style={{ color: "var(--color-fg)" }}
                          >
                            <CuveeLabel name={c.cuveeName} grandVinLabel={t("grandVin")} />
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm" style={{ color: "rgba(250,247,245,0.6)" }}>
                        {c.appellationName}
                      </td>
                      <td className="px-4 py-3">
                        <TierBadge tier={c.tier} labels={tierLabels} />
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-sm" style={{ color: "rgba(250,247,245,0.6)" }}>
                        {c.vintageCount > 0 ? c.vintageCount : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {c.bestRating !== null ? (
                          <span
                            className="font-semibold"
                            style={{ color: "var(--color-accent)" }}
                          >
                            {c.bestRating.toFixed(1)}/100
                          </span>
                        ) : (
                          <span style={{ color: "rgba(250,247,245,0.25)" }}>—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-sm" style={{ color: "var(--color-fg)" }}>
                        {c.priceMin !== null && c.priceMax !== null ? (
                          c.priceMin === c.priceMax ? (
                            `€${c.priceMin.toFixed(0)}`
                          ) : (
                            `€${c.priceMin.toFixed(0)} – ${c.priceMax.toFixed(0)}`
                          )
                        ) : (
                          <span style={{ color: "rgba(250,247,245,0.25)" }}>—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <ConfidenceBadge
                          confidence={deriveConfidence(c.sourceCount)}
                          sourceCount={c.sourceCount}
                          labels={confidenceLabels}
                          size="sm"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* ── 4. Evolution chart ────────────────────────────────────────────── */}
      {hasVintageData && (
        <section className="mb-10">
          <h2 className="text-xl font-display mb-4" style={{ color: "var(--color-fg)" }}>
            {t("evolution")}
          </h2>
          <CuveeEvolutionChart
            data={cuveeYearPoints}
            cuveeNames={cuveeNames}
            labels={{
              metricPrice: t("metricPrice"),
              metricRating: t("metricRating"),
              allCuvees: t("allCuvees"),
              noData: t("noPriceData"),
              priceAxis: t("priceAxis"),
              ratingAxis: t("ratingAxis"),
              evolution: t("evolution"),
            }}
          />
        </section>
      )}

      {/* ── 5. Detailed wine table ────────────────────────────────────────── */}
      <section className="mb-6">
        <h2 className="text-xl font-display mb-4" style={{ color: "var(--color-fg)" }}>
          {t("detailedWines")}
        </h2>
        <DomaineDetailTable
          rows={detailRows}
          cuveeNames={cuveeNames}
          labels={{
            canonicalName: t("canonicalName"),
            cuvee: t("cuvee"),
            vintage: tCommon("vintage"),
            appellation: tCommon("appellation"),
            color: tCommon("color"),
            classification: t("classification"),
            alcohol: t("alcohol"),
            bottleSize: t("bottleSize"),
            bestRating: t("bestRating"),
            priceRange: t("priceRange"),
            inCellar: t("inCellar"),
            sources: t("sources"),
            allCuvees: t("allCuvees"),
            allColors: t("allColors"),
            filterVintageFrom: t("filterVintageFrom"),
            filterVintageTo: t("filterVintageTo"),
            noWinesFilter: t("noWinesFilter"),
            grandVin: t("grandVin"),
          }}
          colorLabels={colorLabels}
          confidenceLabels={confidenceLabels}
        />
      </section>

      {/* ── 6. Similar wines ─────────────────────────────────────────────── */}
      <section className="mb-8">
        <SimilarWines
          wines={similarWines}
          labels={{
            title: tSim("title"),
            subtitle: tSim("subtitle"),
            match: tSim("similarityScore"),
            noResults: tSim("noResults"),
          }}
        />
      </section>
    </PageShell>
  );
}
