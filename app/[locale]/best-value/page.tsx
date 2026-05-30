import { Suspense } from "react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimWine, dimProducer, dimAppellation, factPrice, factRating, stagingPriceCandidates } from "@/db/schema";
import { sql, desc, eq, and, gt, isNotNull, inArray } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { BestValueScatter, type BestValuePoint } from "@/components/BestValueScatter";
import { ConfidenceBadge, deriveConfidence, type Confidence } from "@/components/ConfidenceBadge";
import { BestValueFilters, type BestValueFilterLabels } from "@/components/BestValueFilters";
import { ShopButton } from "@/components/ShopButton";
import { TrendingDown } from "lucide-react";

export const dynamic = "force-dynamic";

interface FilterParams {
  country?: string;
  region?: string;
  vintage?: number;
  minPrice?: number;
  maxPrice?: number;
  minRating?: number;
  maxRating?: number;
}

async function getFilterOptions(locale: string, country?: string) {
  const countryNames = new Intl.DisplayNames([locale], { type: "region" });

  const [countriesResult, regionsResult, vintagesResult] = await Promise.all([
    db
      .selectDistinct({ countryCode: dimAppellation.countryCode })
      .from(dimAppellation)
      .innerJoin(dimWine, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .innerJoin(factPrice, eq(factPrice.wineKey, dimWine.wineKey))
      .orderBy(dimAppellation.countryCode),
    db
      .selectDistinct({ region: dimAppellation.region })
      .from(dimAppellation)
      .innerJoin(dimWine, eq(dimWine.appellationKey, dimAppellation.appellationKey))
      .innerJoin(factPrice, eq(factPrice.wineKey, dimWine.wineKey))
      .where(country ? eq(dimAppellation.countryCode, country) : undefined)
      .orderBy(dimAppellation.region),
    db
      .selectDistinct({ vintage: dimWine.vintage })
      .from(dimWine)
      .innerJoin(factPrice, eq(factPrice.wineKey, dimWine.wineKey))
      .where(isNotNull(dimWine.vintage))
      .orderBy(desc(dimWine.vintage)),
  ]);

  const countries = countriesResult
    .map((r) => r.countryCode)
    .filter(Boolean)
    .map((code) => ({ code: code as string, name: countryNames.of(code as string) ?? (code as string) }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return {
    countries,
    regions: regionsResult.map((r) => r.region).filter(Boolean) as string[],
    vintages: vintagesResult.map((v) => v.vintage).filter(Boolean) as number[],
  };
}

interface BestValueRow {
  wineKey: string;
  canonicalName: string;
  producerKey: number;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  appellationName: string;
  score: number;
  priceEur: number;
  minPriceEur: number;
  maxPriceEur: number;
  ratingNorm100: number;
  confidence: Confidence;
  sourceCount: number;
}

function generateShopPrompt(wine: BestValueRow): string {
  const priceRange =
    wine.minPriceEur === wine.maxPriceEur
      ? `€${wine.priceEur.toFixed(2)}`
      : `€${wine.minPriceEur.toFixed(2)} – €${wine.maxPriceEur.toFixed(2)} (moy. €${wine.priceEur.toFixed(2)})`;

  const ratingLine =
    wine.ratingNorm100 > 0
      ? `\n**Note critique :** ${wine.ratingNorm100.toFixed(1)}/100 (${wine.sourceCount} source${wine.sourceCount > 1 ? "s" : ""})`
      : "";

  const millesimeAdvice = wine.vintage
    ? `Pour le millésime ${wine.vintage}, est-ce le bon moment pour acheter et/ou boire ce vin ?`
    : `Ce vin est sans millésime précis. Quel millésime recommandes-tu actuellement ?`;

  return `Je recherche ce vin précis pour l'acquérir au meilleur prix :

**Vin :** ${wine.producerName} — ${wine.cuveeName}${wine.vintage ? ` · Millésime ${wine.vintage}` : ""}
**Appellation :** ${wine.appellationName}${ratingLine}
**Prix de référence :** ${priceRange}
**Sources :** ${wine.sourceCount} revendeur${wine.sourceCount > 1 ? "s" : ""} référencé${wine.sourceCount > 1 ? "s" : ""} dans ma base

En tant que caviste expérimenté, aide-moi à :

1. **Trouver ce vin** — identifie les meilleurs sites en ligne et cavistes physiques (France, Belgique, Europe) où le commander aujourd'hui. Prix indicatif si possible.
2. **Valider le prix** — le prix observé est-il cohérent avec le marché actuel ? Y a-t-il des opportunités (déstockage, enchères, négoce) ?
3. **Conseil millésime** — ${millesimeAdvice}
4. **Plan B** — si ce vin est épuisé ou hors budget, quelles alternatives (même appellation, style proche, rapport Q/P similaire) recommandes-tu ?
5. **Contexte cave** — je suis un amateur éclairé avec une cave privée. Donne-moi ce qu'un bon caviste partagerait avec un client régulier.

**Livraison souhaitée à : Templeuve, Belgique (7520)**

Sois précis, pratique et direct — pas de généralités.`;
}

async function getBestValueWines(filters: FilterParams = {}): Promise<{ wines: BestValueRow[]; ratingMode: boolean }> {
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

    // Also include staging prices for wines not yet promoted to fact_price (single-source candidates)
    const factPriceKeys = new Set(prices.map((p) => p.wineKey));
    const stagingRows = await db
      .select({
        wineKey: stagingPriceCandidates.wineKey,
        avgPrice: sql<number>`avg(${stagingPriceCandidates.amountEur})`,
        minPrice: sql<number>`min(${stagingPriceCandidates.amountEur})`,
        maxPrice: sql<number>`max(${stagingPriceCandidates.amountEur})`,
        srcCount: sql<number>`count(distinct ${stagingPriceCandidates.sourceKey})`,
      })
      .from(stagingPriceCandidates)
      .where(and(isNotNull(stagingPriceCandidates.amountEur), gt(stagingPriceCandidates.amountEur, 1)))
      .groupBy(stagingPriceCandidates.wineKey);

    // Merge: fact_price wins on overlap; staging fills in the rest
    let allPrices = [
      ...prices,
      ...stagingRows.filter((s) => !factPriceKeys.has(s.wineKey)),
    ];

    // Apply price filters
    if (filters.minPrice !== undefined) {
      allPrices = allPrices.filter((p) => p.avgPrice >= filters.minPrice!);
    }
    if (filters.maxPrice !== undefined) {
      allPrices = allPrices.filter((p) => p.avgPrice <= filters.maxPrice!);
    }

    if (allPrices.length === 0) return { wines: [], ratingMode: false };

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
    const priceMap = new Map(allPrices.map((p) => [p.wineKey, p]));
    const ratingMap = new Map(ratings.map((r) => [r.wineKey, { avg: r.avgRating, count: r.sourceCount }]));

    // In rating mode: only wines with both price + rating; in price-confidence mode: all price wines
    const eligibleKeys = hasRatings
      ? [...priceMap.keys()].filter((k) => {
          if (!ratingMap.has(k)) return false;
          const rating = ratingMap.get(k)!.avg;
          if (filters.minRating !== undefined && rating < filters.minRating) return false;
          if (filters.maxRating !== undefined && rating > filters.maxRating) return false;
          return true;
        })
      : [...priceMap.keys()];

    if (eligibleKeys.length === 0) return { wines: [], ratingMode: false };

    // Fetch wine + producer + appellation data for eligible keys (batched for SQLite)
    const BATCH = 200;
    const wineRows: Array<{
      wineKey: string; canonicalName: string; cuveeName: string;
      vintage: number | null; producerKey: number; producerName: string; appellationName: string;
    }> = [];
    for (let i = 0; i < eligibleKeys.length; i += BATCH) {
      const batch = eligibleKeys.slice(i, i + BATCH);
      const rows = await db
        .select({
          wineKey: dimWine.wineKey,
          canonicalName: dimWine.canonicalName,
          cuveeName: dimWine.cuveeName,
          vintage: dimWine.vintage,
          producerKey: dimProducer.producerKey,
          producerName: dimProducer.producerName,
          appellationName: dimAppellation.appellationName,
        })
        .from(dimWine)
        .innerJoin(dimProducer, eq(dimWine.producerKey, dimProducer.producerKey))
        .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
        .where(
          and(
            inArray(dimWine.wineKey, batch),
            filters.country ? eq(dimAppellation.countryCode, filters.country) : undefined,
            filters.vintage !== undefined ? eq(dimWine.vintage, filters.vintage) : undefined,
            filters.region ? eq(dimAppellation.region, filters.region) : undefined,
          )
        )
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
          producerKey: w.producerKey,
          producerName: w.producerName,
          cuveeName: w.cuveeName,
          vintage: w.vintage,
          appellationName: w.appellationName,
          score,
          priceEur: price,
          minPriceEur: pd.minPrice,
          maxPriceEur: pd.maxPrice,
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
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ country?: string; region?: string; vintage?: string; minPrice?: string; maxPrice?: string; minRating?: string; maxRating?: string }>;
}) {
  const { locale } = await params;
  const sp = await searchParams;
  setRequestLocale(locale);
  const t = await getTranslations("bestValue");
  const tc = await getTranslations("common");

  const filters: FilterParams = {
    country: sp.country || undefined,
    region: sp.region || undefined,
    vintage: sp.vintage ? parseInt(sp.vintage, 10) : undefined,
    minPrice: sp.minPrice ? parseFloat(sp.minPrice) : undefined,
    maxPrice: sp.maxPrice ? parseFloat(sp.maxPrice) : undefined,
    minRating: sp.minRating ? parseFloat(sp.minRating) : undefined,
    maxRating: sp.maxRating ? parseFloat(sp.maxRating) : undefined,
  };
  const hasActiveFilters = !!(sp.country || sp.region || sp.vintage || sp.minPrice || sp.maxPrice || sp.minRating || sp.maxRating);

  const [{ wines, ratingMode }, { countries, regions, vintages }] = await Promise.all([
    getBestValueWines(filters),
    getFilterOptions(locale, filters.country),
  ]);

  const filterLabels: BestValueFilterLabels = {
    country: t("filters.country"),
    region: tc("region"),
    vintage: tc("vintage"),
    minPrice: t("filters.minPrice"),
    maxPrice: t("filters.maxPrice"),
    minRating: t("filters.minRating"),
    maxRating: t("filters.maxRating"),
    allCountries: t("filters.allCountries"),
    allRegions: t("filters.allRegions"),
    allVintages: t("filters.allVintages"),
    clearFilters: t("filters.clearFilters"),
  };

  const scatterData: BestValuePoint[] = wines.map((w) => ({
    wineKey: w.wineKey,
    canonicalName: w.canonicalName,
    priceEur: w.priceEur,
    ratingNorm100: w.ratingNorm100,
    score: w.score,
  }));

  return (
    <PageShell title={t("title")} subtitle={ratingMode ? t("subtitle") : "Prix confirmés par ≥2 sources indépendantes · classement par confiance prix"} badge="Sprint 4 · P1">
      <Suspense fallback={<div className="glass-card p-4 h-16 animate-pulse rounded-xl" />}>
        <BestValueFilters countries={countries} regions={regions} vintages={vintages} labels={filterLabels} />
      </Suspense>

      {wines.length === 0 ? (
        <div className="glass-card p-12 flex flex-col items-center justify-center text-center gap-4">
          <TrendingDown className="size-10 text-[color:var(--color-fg-subtle)]" strokeWidth={1.5} />
          <p className="text-[color:var(--color-fg-muted)]">
            {hasActiveFilters ? t("filters.noResults") : t("noData")}
          </p>
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
                      <Link
                        href={`/${locale}/domaines/${wine.producerKey}`}
                        className="hover:text-[color:var(--color-coral-400)] transition-colors"
                      >
                        {wine.producerName}
                      </Link>
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
                  <ShopButton prompt={generateShopPrompt(wine)} />
                </div>
              </div>
            ))}
          </section>
        </div>
      )}
    </PageShell>
  );
}
