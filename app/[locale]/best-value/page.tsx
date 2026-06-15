import { Suspense } from "react";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { BestValueScatter, type BestValuePoint } from "@/components/BestValueScatter";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { BestValueFilters, type BestValueFilterLabels } from "@/components/BestValueFilters";
import { ShopButton } from "@/components/ShopButton";
import { TrendingDown } from "lucide-react";
import {
  getBestValueWines,
  getBestValueFilterOptions,
  type BestValueRow,
  type FilterParams,
  type DrinkingIntent,
} from "@/lib/queries/best-value";

export const dynamic = "force-dynamic";

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

function RankBadge({ rank }: { rank: number }) {
  const isTop3 = rank <= 3;
  return (
    <div
      className={`flex-shrink-0 size-9 rounded-full flex items-center justify-center text-sm font-bold font-mono ${
        isTop3
          ? "bg-[rgba(165,56,96,0.2)] text-[color:var(--color-champagne-400)] border border-[rgba(165,56,96,0.4)]"
          : "bg-[rgba(165,56,96,0.07)] text-[color:var(--color-fg-muted)] border border-[color:var(--color-border)]"
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
  searchParams: Promise<{ country?: string; region?: string; vintage?: string; color?: string; minPrice?: string; maxPrice?: string; minRating?: string; maxRating?: string; drinkingIntent?: string }>;
}) {
  const { locale } = await params;
  const sp = await searchParams;
  setRequestLocale(locale);
  const t = await getTranslations("bestValue");
  const tc = await getTranslations("common");

  const drinkingIntent = (["drink_now", "cellar_10", "invest"].includes(sp.drinkingIntent ?? "") ? sp.drinkingIntent : undefined) as DrinkingIntent | undefined;

  const filters: FilterParams = {
    country: sp.country || undefined,
    region: sp.region || undefined,
    vintage: sp.vintage ? parseInt(sp.vintage, 10) : undefined,
    color: sp.color || undefined,
    minPrice: sp.minPrice ? parseFloat(sp.minPrice) : undefined,
    maxPrice: sp.maxPrice ? parseFloat(sp.maxPrice) : undefined,
    minRating: sp.minRating ? parseFloat(sp.minRating) : undefined,
    maxRating: sp.maxRating ? parseFloat(sp.maxRating) : undefined,
    drinkingIntent,
  };
  const hasActiveFilters = !!(sp.country || sp.region || sp.vintage || sp.color || sp.minPrice || sp.maxPrice || sp.minRating || sp.maxRating || drinkingIntent);

  const [{ wines, ratingMode }, { countries, regions, vintages }] = await Promise.all([
    getBestValueWines(filters),
    getBestValueFilterOptions(locale, filters.country),
  ]);

  const filterLabels: BestValueFilterLabels = {
    country: t("filters.country"),
    region: tc("region"),
    vintage: tc("vintage"),
    color: t("filters.color"),
    colorRed: t("filters.colorRed"),
    colorWhite: t("filters.colorWhite"),
    colorRose: t("filters.colorRose"),
    colorSparkling: t("filters.colorSparkling"),
    minPrice: t("filters.minPrice"),
    maxPrice: t("filters.maxPrice"),
    minRating: t("filters.minRating"),
    maxRating: t("filters.maxRating"),
    allCountries: t("filters.allCountries"),
    allRegions: t("filters.allRegions"),
    allVintages: t("filters.allVintages"),
    clearFilters: t("filters.clearFilters"),
    intent: t("filters.intent"),
    intentDrinkNow: t("filters.intentDrinkNow"),
    intentCellar10: t("filters.intentCellar10"),
    intentInvest: t("filters.intentInvest"),
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
                        className="hover:text-[color:var(--color-magenta-400)] transition-colors"
                      >
                        {wine.producerName}
                      </Link>
                      {" · "}
                      <span className="text-[color:var(--color-champagne-400)]">{wine.cuveeName}</span>
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
                    <p className="font-mono text-sm font-bold text-[color:var(--color-champagne-400)]">
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
