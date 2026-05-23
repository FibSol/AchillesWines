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

async function getBestValueWines(): Promise<{ wines: BestValueRow[]; ratingMode: boolean }> {
  try {
    // Get average price + source count per wine from confirmed fact_price
    const prices = await db
      .select({
        wineKey: factPrice.wineKey,
        avgPrice: sql<number>`avg(${factPrice.amountEur})`,
        minPrice: sql<number>`min(${factPrice.amountEur})`,
        maxPrice: sql<number>`max(${factPrice.amountEur})`,
        srcCount: sql<number>`count(distinct ${factPrice.sourceKey})`,
      })
      .from(factPrice)
      .where(and(isNotNull(factPrice.amountEur), gt(factPrice.amountEur, 1)))
      .groupBy(factPrice.wineKey);

    if (prices.length === 0) return { wines: [], ratingMode: false };

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

    const hasRatings = ratings.length > 0;
    const priceMap = new Map(prices.map((p) => [p.wineKey, p]));
    const ratingMap = new Map(ratings.map((r) => [r.wineKey, { avg: r.avgRating, count: r.sourceCount }]));

    // In rating mode: only wines with both price + rating; in price-confidence mode: all price wines
    const eligibleKeys = hasRatings
      ? [...priceMap.keys()].filter((k) => ratingMap.has(k))
      : [...priceMap.keys()];

    if (eligibleKeys.length === 0) return { wines: [], ratingMode: false };

    // Fetch wine + producer + appellation data for eligible keys (batched for SQLite)
    const BATCH = 200;
    const wineRows: Array<{
      wineKey: string; canonicalName: string; cuveeName: string;
      vintage: number | null; producerName: string; appellationName: string;
    }> = [];
    for (let i = 0; i < eligibleKeys.length; i += BATCH) {
      const batch = eligibleKeys.slice(i, i + BATCH);
      const rows = await db
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
        .where(sql`${dimWine.wineKey} IN (${sql.raw(batch.map(() => "?").join(","))})`)
        .execute();
      wineRows.push(...rows);
    }

    // Score and sort
    const scored: BestValueRow[] = wineRows
      .map((w) => {
        const pd = priceMap.get(w.wineKey);
        if (!pd) return null;
        const price = pd.avgPrice;
        if (price <= 1) return null;
        const logPrice = Math.log(price);
        if (logPrice <= 0) return null;

        let score: number;
        let ratingNorm100: number;
        let sourceCount: number;

        if (hasRatings) {
          const ratingInfo = ratingMap.get(w.wineKey);
          const rating = ratingInfo?.avg ?? 0;
          if (rating === 0) return null;
          ratingNorm100 = rating;
          sourceCount = Number(ratingInfo?.count ?? 0);
          score = (rating * rating) / logPrice;
        } else {
          // Price-confidence mode: score = sources × (1 - price_spread_pct)
          // Rewards wines confirmed by multiple retailers with tight price agreement
          const spread = pd.maxPrice > 0 ? (pd.maxPrice - pd.minPrice) / pd.maxPrice : 0;
          const priceSources = Number(pd.srcCount ?? 1);
          score = priceSources * (1 - spread) * 100;
          ratingNorm100 = 0;
          sourceCount = priceSources;
        }

        return {
          wineKey: w.wineKey,
          canonicalName: w.canonicalName,
          producerName: w.producerName,
          cuveeName: w.cuveeName,
          vintage: w.vintage,
          appellationName: w.appellationName,
          score,
          priceEur: price,
          ratingNorm100,
          confidence: deriveConfidence(sourceCount),
          sourceCount,
        } satisfies BestValueRow;
      })
      .filter((r): r is BestValueRow => r !== null)
      .sort((a, b) => b.score - a.score)
      .slice(0, 50);

    return { wines: scored, ratingMode: hasRatings };
  } catch {
    return { wines: [], ratingMode: false };
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

  const { wines, ratingMode } = await getBestValueWines();

  const scatterData: BestValuePoint[] = wines.map((w) => ({
    wineKey: w.wineKey,
    canonicalName: w.canonicalName,
    priceEur: w.priceEur,
    ratingNorm100: w.ratingNorm100,
    score: w.score,
  }));

  return (
    <PageShell title={t("title")} subtitle={ratingMode ? t("subtitle") : "Prix confirmés par ≥2 sources indépendantes · classement par confiance prix"} badge="Sprint 4 · P1">
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
