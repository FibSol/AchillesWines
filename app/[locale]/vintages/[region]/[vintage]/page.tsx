import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import Link from "next/link";
import { PageShell } from "@/components/page-shell";
import { ConfidenceBadge, deriveConfidence } from "@/components/ConfidenceBadge";
import { ArrowLeft } from "lucide-react";
import { getVintageWines } from "@/lib/queries/vintages";

export const dynamic = "force-dynamic";

function scoreToTier(score: number): 1 | 2 | 3 | 4 | 5 {
  if (score >= 95) return 5;
  if (score >= 90) return 4;
  if (score >= 82) return 3;
  if (score >= 70) return 2;
  return 1;
}

type TierStyle = { bg: string; text: string };

function tierStyle(tier: 1 | 2 | 3 | 4 | 5): TierStyle {
  switch (tier) {
    case 5: return { bg: "rgba(229,178,93,0.97)",  text: "#0F0E17" };
    case 4: return { bg: "rgba(165,56,96,0.95)",  text: "#0F0E17" };
    case 3: return { bg: "rgba(155,100,210,0.82)", text: "#FAF7F5" };
    case 2: return { bg: "rgba(165,56,96,0.60)",   text: "rgba(250,247,245,0.9)" };
    case 1: return { bg: "rgba(50,20,38,0.85)",    text: "rgba(250,247,245,0.6)" };
  }
}

function ColorDot({ color }: { color: string }) {
  const map: Record<string, string> = {
    red: "#A53860", white: "#E5B25D", "rosé": "#E07898",
    sparkling: "#F5D08C", sweet: "#EDC072", fortified: "#6E1F3D", orange: "#C99440",
  };
  return (
    <span
      className="inline-block size-2 rounded-full shrink-0"
      style={{ background: map[color] ?? "#FAF7F5" }}
      aria-label={color}
    />
  );
}

export default async function VintageWinesPage({
  params,
}: {
  params: Promise<{ locale: string; region: string; vintage: string }>;
}) {
  const { locale, region: regionParam, vintage: vintageParam } = await params;
  setRequestLocale(locale);

  const region = decodeURIComponent(regionParam);
  const vintage = parseInt(vintageParam, 10);
  if (isNaN(vintage)) notFound();

  const t = await getTranslations("vintages");
  const tCommon = await getTranslations("common");
  const tConf = await getTranslations("confidence");
  const tDomaine = await getTranslations("domaine");

  const { wines, avgScore } = await getVintageWines(region, vintage);

  const tier = avgScore !== null ? scoreToTier(avgScore) : null;
  const tierLabels = [t("tiers.t1"), t("tiers.t2"), t("tiers.t3"), t("tiers.t4"), t("tiers.t5")];
  const tierLabel = tier !== null ? tierLabels[tier - 1] : null;
  const ts = tier !== null ? tierStyle(tier) : null;

  const confidenceLabels = {
    verified: tConf.raw("verified") as string,
    reviewed: tConf("reviewed"),
    needs_review: tConf("needs_review"),
  };

  return (
    <PageShell
      title={`${region} · ${vintage}`}
      subtitle={tier !== null && tierLabel ? `${t("scoreLabel")} ${tier}/5 — ${tierLabel}` : region}
      badge={wines.length > 0 ? `${wines.length} ${tCommon("producer").toLowerCase()}s` : undefined}
    >
      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/${locale}/vintages`}
          className="inline-flex items-center gap-1.5 text-xs text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)] transition-colors"
        >
          <ArrowLeft className="size-3.5" strokeWidth={2.5} />
          {t("backToVintages")}
        </Link>
      </div>

      {/* Tier badge */}
      {tier !== null && ts !== null && tierLabel !== null && (
        <div className="mb-6 flex items-center gap-3">
          <span
            className="text-sm px-3 py-1 rounded font-semibold"
            style={{ background: ts.bg, color: ts.text }}
          >
            {tier}/5 — {tierLabel}
          </span>
          <span className="text-sm text-[color:var(--color-fg-muted)] font-mono">
            {avgScore!.toFixed(0)}/100
          </span>
        </div>
      )}

      {/* Wine table */}
      {wines.length === 0 ? (
        <div className="glass-card p-12 text-center text-[rgba(250,247,245,0.5)] text-sm">
          {t("noWines")}
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-[color:var(--color-border)]">
                <tr className="text-left text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                  <th className="px-4 py-3 font-semibold">{tCommon("producer")}</th>
                  <th className="px-4 py-3 font-semibold">{tDomaine("cuvee")}</th>
                  <th className="px-4 py-3 font-semibold">{tCommon("appellation")}</th>
                  <th className="px-4 py-3 font-semibold text-right">{tDomaine("sources")}</th>
                </tr>
              </thead>
              <tbody>
                {wines.map(w => (
                  <tr
                    key={w.wineKey}
                    className="border-b border-[color:var(--color-border)] last:border-b-0 hover:bg-[rgba(165,56,96,0.04)] transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/${locale}/domaines/${w.producerKey}`}
                        className="font-semibold text-[color:var(--color-fg)] hover:text-[color:var(--color-magenta-400)] transition-colors"
                      >
                        {w.producerName}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <ColorDot color={w.color} />
                        <span className="text-[color:var(--color-fg-muted)]">{w.cuveeName}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-[color:var(--color-fg-muted)]">
                      {w.appellationName}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <ConfidenceBadge
                        confidence={deriveConfidence(w.sourceCount)}
                        sourceCount={w.sourceCount}
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
    </PageShell>
  );
}
