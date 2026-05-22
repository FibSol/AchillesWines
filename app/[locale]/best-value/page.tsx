import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimWine, dimProducer, dimAppellation, factPrice, factRating } from "@/db/schema";
import { sql, desc, eq, and, gt, isNotNull } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { BestValueScatter, type BestValuePoint } from "@/components/BestValueScatter";
import { ConfidenceBadge, deriveConfidence, type Confidence } from "@/components/ConfidenceBadge";
import { TrendingDown } from "lucide-react";

export const dynamic = "force-dynamic";

interface BestValueRow {
  wineKey: string;
  canonicalName: string;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  appellationName: string;
  score: number;
  priceEur: number;
  ratingNorm100: number;
  confidence: Confidence;
  sourceCount: number;
}

async function getBestValueWines(): Promise<BestValueRow[]> {
  try {
    // Get average price per wine
    const prices = await db
      .select({
        wineKey: factPrice.wineKey,
        avgPrice: sql<number>`avg(${factPrice.amountEur})`,
      })
      .from(factPrice)
      .where(and(isNotNull(factPrice.amountEur), gt(factPrice.amountEur, 1)))
      .groupBy(factPrice.wineKey);

    // Get average normalized rating + distinct source count per wine
    const ratings = await db
      .select({
        wineKey: factRating.wineKey,
        avgRating: sql<number>`avg(${factRating.scoreNormalized100})`,
        sourceCount: sql<number>`count(distinct ${factRating.sourceKey})`,
      })
      .from(factRating)
      .where(isNotNull(factRating.scoreNormalized100))
      .groupBy(factRating.wineKey);

    if (prices.length === 0 || ratings.length === 0) {
      return [];
    }

    // Build lookup maps
    const priceMap = new Map(prices.map((p) => [p.wineKey, p.avgPrice]));
    const ratingMap = new Map(ratings.map((r) => [r.wineKey, { avg: r.avgRating, count: r.sourceCount }]));

    // Find wine_keys that have both price and rating
    const eligibleKeys = [...priceMap.keys()].filter((k) => ratingMap.has(k));
    if (eligibleKeys.length === 0) return [];

    // Fetch wine + producer + appellation data for eligible keys
    const wines = await db
      .select({
        wineKey: dimWine.wineKey,
        canonicalName: dimWine.canonicalName,
        cuveeName: dimWine.cuveeName,
        vintage: dimWine.vintage,
        producerName: dimProducer.producerName,
        appellationName: dimAppellation.appellationName,
      })
      .from(dimWine)
      .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
      .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .where(sql`${dimWine.wineKey} IN (${sql.raw(eligibleKeys.map(() => "?").join(","))})`)
      .execute();

    // Score and sort
    const scored: BestValueRow[] = wines
      .map((w) => {
        const price = priceMap.get(w.wineKey) ?? 0;
        const ratingInfo = ratingMap.get(w.wineKey);
        const rating = ratingInfo?.avg ?? 0;
        const sourceCount = Number(ratingInfo?.count ?? 0);

        if (price <= 1 || rating === 0) return null;

        const logPrice = Math.log(price);
        if (logPrice <= 0) return null;

        const score = (rating * rating) / logPrice;

        return {
          wineKey: w.wineKey,
          canonicalName: w.canonicalName,
          producerName: w.producerName,
          cuveeName: w.cuveeName,
          vintage: w.vintage,
          appellationName: w.appellationName,
          score,
          priceEur: price,
          ratingNorm100: rating,
          confidence: deriveConfidence(sourceCount),
          sourceCount,
        } satisfies BestValueRow;
      })
      .filter((r): r is BestValueRow => r !== null)
      .sort((a, b) => b.score - a.score)
      .slice(0, 50);

    return scored;
  } catch {
    return [];
  }
}

function RankBadge({ rank }: { rank: number }) {
  const isTop3 = rank <= 3;
  return (
    <div
      className={`flex-shrink-0 size-9 rounded-full flex items-center justify-center text-sm font-bold font-mono ${
        isTop3
          ? "bg-[rgba(255,92,138,0.2)] text-[color:var(--color-coral-400)] border border-[rgba(255,92,138,0.4)]"
          : "bg-[rgba(255,92,138,0.07)] text-[color:var(--color-fg-muted)] border border-[color:var(--color-border)]"
      }`}
    >
      {rank}
    </div>
  );
}

export default async function BestValuePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("bestValue");

  const wines = await getBestValueWines();

  const scatterData: BestValuePoint[] = wines.map((w) => ({
    wineKey: w.wineKey,
    canonicalName: w.canonicalName,
    priceEur: w.priceEur,
    ratingNorm100: w.ratingNorm100,
    score: w.score,
  }));

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="Sprint 4 · P1">
      {wines.length === 0 ? (
        <div className="glass-card p-12 flex flex-col items-center justify-center text-center gap-4">
          <TrendingDown className="size-10 text-[color:var(--color-fg-subtle)]" strokeWidth={1.5} />
          <p className="text-[color:var(--color-fg-muted)]">{t("noData")}</p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Scatter plot */}
          <section>
            <BestValueScatter data={scatterData} />
          </section>

          {/* Ranked list */}
          <section className="space-y-2">
            {wines.map((wine, idx) => (
              <div
                key={wine.wineKey}
                className="glass-card p-4 flex items-center gap-4"
              >
                {/* Rank */}
                <RankBadge rank={idx + 1} />

                {/* Wine info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-2 flex-wrap">
                    <p className="font-semibold text-[color:var(--color-fg)] leading-snug">
                      {wine.producerName}
                      {" · "}
                      <span className="text-[color:var(--color-coral-400)]">{wine.cuveeName}</span>
                      {wine.vintage && (
                        <span className="ml-1 text-[color:var(--color-fg-muted)]">{wine.vintage}</span>
                      )}
                    </p>
                    <ConfidenceBadge
                      confidence={wine.confidence}
                      sourceCount={wine.sourceCount}
                      labels={{
                        verified: t.raw("confidence.verified") as string,
                        reviewed: t("confidence.reviewed"),
                        needs_review: t("confidence.needs_review"),
                      }}
                    />
                  </div>
                  <p className="text-xs text-[color:var(--color-fg-subtle)] mt-0.5">
                    {wine.appellationName}
                  </p>
                </div>

                {/* Metrics */}
                <div className="hidden sm:flex items-center gap-6 shrink-0 text-right">
                  <div>
                    <p className="text-xs text-[color:var(--color-fg-subtle)]">{t("price")}</p>
                    <p className="font-mono text-sm font-semibold text-[color:var(--color-fg)]">
                      €{wine.priceEur.toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-[color:var(--color-fg-subtle)]">{t("rating")}</p>
                    <p className="font-mono text-sm font-semibold text-[color:var(--color-accent)]">
                      {wine.ratingNorm100.toFixed(1)}/100
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-[color:var(--color-fg-subtle)]">{t("score")}</p>
                    <p className="font-mono text-sm font-bold text-[color:var(--color-coral-400)]">
                      {wine.score.toFixed(2)}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </section>
        </div>
      )}
    </PageShell>
  );
}
