import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import Link from "next/link";
import { db } from "@/db";
import {
  dimProducer,
  dimWine,
  dimAppellation,
  dimSource,
  factPrice,
  factRating,
} from "@/db/schema";
import { eq, inArray, asc } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import {
  PriceHistoryChart,
  RatingsByCriticChart,
  DrinkingWindowBand,
  type PricePoint,
  type RatingPoint,
} from "@/components/ProducerCharts";
import { ConfidenceBadge, deriveConfidence } from "@/components/ConfidenceBadge";
import { ArrowLeft, MapPin, Globe } from "lucide-react";

export const dynamic = "force-dynamic";

interface CuveeRow {
  wineKey: string;
  cuveeName: string;
  canonicalName: string;
  vintage: number | null;
  appellationName: string;
  color: string;
  bestRating: number | null;
  priceMin: number | null;
  priceMax: number | null;
  sourceCount: number;
}

interface LoadedData {
  producer: typeof dimProducer.$inferSelect;
  cuvees: CuveeRow[];
  pricePoints: PricePoint[];
  priceSources: string[];
  ratingPoints: RatingPoint[];
  drinkingWindow: { drinkFrom: number; drinkTo: number } | null;
}

async function loadProducerDetail(producerKey: number): Promise<LoadedData | null> {
  const producerRows = await db
    .select()
    .from(dimProducer)
    .where(eq(dimProducer.producerKey, producerKey))
    .limit(1);

  const producer = producerRows[0];
  if (!producer) return null;

  // All wines for this producer with their appellation
  const wines = await db
    .select({
      wineKey: dimWine.wineKey,
      cuveeName: dimWine.cuveeName,
      canonicalName: dimWine.canonicalName,
      vintage: dimWine.vintage,
      color: dimWine.color,
      appellationName: dimAppellation.appellationName,
    })
    .from(dimWine)
    .innerJoin(dimAppellation, eq(dimWine.appellationKey, dimAppellation.appellationKey))
    .where(eq(dimWine.producerKey, producerKey));

  const wineKeys = wines.map((w) => w.wineKey);

  let prices: (typeof factPrice.$inferSelect)[] = [];
  let ratings: (typeof factRating.$inferSelect)[] = [];
  let sources: (typeof dimSource.$inferSelect)[] = [];

  if (wineKeys.length > 0) {
    [prices, ratings] = await Promise.all([
      db
        .select()
        .from(factPrice)
        .where(inArray(factPrice.wineKey, wineKeys))
        .orderBy(asc(factPrice.recordedAt)),
      db
        .select()
        .from(factRating)
        .where(inArray(factRating.wineKey, wineKeys)),
    ]);

    const sourceKeys = Array.from(
      new Set<number>([...prices.map((p) => p.sourceKey), ...ratings.map((r) => r.sourceKey)]),
    );
    if (sourceKeys.length > 0) {
      sources = await db.select().from(dimSource).where(inArray(dimSource.sourceKey, sourceKeys));
    }
  }

  const sourceCodeByKey = new Map(sources.map((s) => [s.sourceKey, s.sourceCode]));

  // Build cuvée aggregates
  const ratingsByWine = new Map<string, typeof ratings>();
  for (const r of ratings) {
    const arr = ratingsByWine.get(r.wineKey) ?? [];
    arr.push(r);
    ratingsByWine.set(r.wineKey, arr);
  }

  const pricesByWine = new Map<string, typeof prices>();
  for (const p of prices) {
    const arr = pricesByWine.get(p.wineKey) ?? [];
    arr.push(p);
    pricesByWine.set(p.wineKey, arr);
  }

  const cuvees: CuveeRow[] = wines
    .map((w) => {
      const wineRatings = ratingsByWine.get(w.wineKey) ?? [];
      const winePrices = pricesByWine.get(w.wineKey) ?? [];
      const ratingScores = wineRatings.map((r) => r.scoreNormalized100);
      const priceValues = winePrices
        .map((p) => p.amountEur)
        .filter((v): v is number => typeof v === "number" && v > 0);
      const sourceCount = new Set([
        ...winePrices.map((p) => p.sourceKey),
        ...wineRatings.map((r) => r.sourceKey),
      ]).size;
      return {
        wineKey: w.wineKey,
        cuveeName: w.cuveeName,
        canonicalName: w.canonicalName,
        vintage: w.vintage,
        appellationName: w.appellationName,
        color: w.color,
        bestRating: ratingScores.length > 0 ? Math.max(...ratingScores) : null,
        priceMin: priceValues.length > 0 ? Math.min(...priceValues) : null,
        priceMax: priceValues.length > 0 ? Math.max(...priceValues) : null,
        sourceCount,
      } satisfies CuveeRow;
    })
    .sort((a, b) => {
      const ar = a.bestRating ?? -1;
      const br = b.bestRating ?? -1;
      if (br !== ar) return br - ar;
      return a.cuveeName.localeCompare(b.cuveeName);
    });

  // Price history: latest per (source, recordedAt bucket). Group by source as separate series.
  const seenSources = new Set<string>();
  const pointMap = new Map<number, PricePoint>();
  for (const p of prices) {
    if (typeof p.amountEur !== "number" || p.amountEur <= 0) continue;
    const src = sourceCodeByKey.get(p.sourceKey);
    if (!src) continue;
    seenSources.add(src);
    const ts = p.recordedAt instanceof Date ? Math.floor(p.recordedAt.getTime() / 1000) : 0;
    const existing = pointMap.get(ts) ?? { recordedAt: ts };
    existing[src] = p.amountEur;
    pointMap.set(ts, existing);
  }
  const pricePoints = Array.from(pointMap.values()).sort((a, b) => a.recordedAt - b.recordedAt);
  const priceSources = Array.from(seenSources).sort();

  // Ratings by critic: average score per critic_code
  const ratingsByCritic = new Map<string, number[]>();
  for (const r of ratings) {
    const arr = ratingsByCritic.get(r.criticCode) ?? [];
    arr.push(r.scoreNormalized100);
    ratingsByCritic.set(r.criticCode, arr);
  }
  const ratingPoints: RatingPoint[] = Array.from(ratingsByCritic.entries())
    .map(([criticCode, scores]) => ({
      criticCode,
      score: scores.reduce((a, b) => a + b, 0) / scores.length,
    }))
    .sort((a, b) => b.score - a.score);

  // Drinking window — fact_rating may carry optional drink_from/drink_to in future. Try to read
  // them via JSON column not present in current schema; for now we look for any non-null pair
  // attached to the row through an unstructured probe. Returns null if data isn't available.
  let drinkingWindow: { drinkFrom: number; drinkTo: number } | null = null;
  const drinkFroms: number[] = [];
  const drinkTos: number[] = [];
  for (const r of ratings) {
    const raw = r as Record<string, unknown>;
    const from = raw.drinkFrom ?? raw.drink_from;
    const to = raw.drinkTo ?? raw.drink_to;
    if (typeof from === "number" && typeof to === "number" && to >= from) {
      drinkFroms.push(from);
      drinkTos.push(to);
    }
  }
  if (drinkFroms.length > 0 && drinkTos.length > 0) {
    drinkingWindow = {
      drinkFrom: Math.min(...drinkFroms),
      drinkTo: Math.max(...drinkTos),
    };
  }

  return {
    producer,
    cuvees,
    pricePoints,
    priceSources,
    ratingPoints,
    drinkingWindow,
  };
}

function ColorDot({ color }: { color: string }) {
  const map: Record<string, string> = {
    red: "#b71f55",
    white: "#FFD166",
    "rosé": "#FF89A6",
    sparkling: "#8EFEED",
    sweet: "#FFB3C8",
    fortified: "#553987",
    orange: "#FF5C8A",
  };
  return (
    <span
      className="inline-block size-2 rounded-full shrink-0"
      style={{ background: map[color] ?? "#FAF7F5" }}
      aria-label={color}
    />
  );
}

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

  const producerKey = Number.parseInt(id, 10);
  if (!Number.isFinite(producerKey)) notFound();

  const data = await loadProducerDetail(producerKey);
  if (!data) notFound();

  const { producer, cuvees, pricePoints, priceSources, ratingPoints, drinkingWindow } = data;

  return (
    <PageShell
      title={producer.producerName}
      subtitle={[producer.region, producer.subregion, producer.countryCode]
        .filter(Boolean)
        .join(" · ")}
      badge={producer.tier ? `T${producer.tier} · ${cuvees.length} ${t("cuvees").toLowerCase()}` : `${cuvees.length} ${t("cuvees").toLowerCase()}`}
    >
      {/* Header / back link */}
      <div className="flex items-center justify-between mb-6">
        <Link
          href={`/${locale}/domaines`}
          className="inline-flex items-center gap-1.5 text-xs text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)] transition-colors"
        >
          <ArrowLeft className="size-3.5" strokeWidth={2.5} />
          {t("backToList")}
        </Link>
      </div>

      {/* Producer meta */}
      <section className="glass-card p-6 mb-8">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-[color:var(--color-fg-muted)]">
              <MapPin className="size-4" strokeWidth={2.5} />
              <span>
                {producer.region}
                {producer.subregion && ` · ${producer.subregion}`}
                {` · ${producer.countryCode}`}
              </span>
            </div>
            {producer.website && (
              <div className="flex items-center gap-2 text-sm">
                <Globe className="size-4 text-[color:var(--color-fg-muted)]" strokeWidth={2.5} />
                <a
                  href={producer.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[color:var(--color-coral-400)] hover:text-[color:var(--color-accent)] truncate"
                >
                  {producer.website.replace(/^https?:\/\//, "")}
                </a>
              </div>
            )}
            {producer.aliases && producer.aliases.length > 0 && (
              <p className="text-xs text-[color:var(--color-fg-subtle)] mt-2">
                <span className="uppercase tracking-[0.06em] mr-2">{t("aliases")}:</span>
                <span className="font-mono">{producer.aliases.join(" · ")}</span>
              </p>
            )}
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-2">
              {t("allowedAppellations")}
            </p>
            {producer.allowedAppellations && producer.allowedAppellations.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {producer.allowedAppellations.map((app) => (
                  <span
                    key={app}
                    className="badge badge-verified text-[10px] py-0.5"
                    title={app}
                  >
                    {app}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[color:var(--color-fg-subtle)] italic">{tCommon("empty")}</p>
            )}
          </div>
        </div>
      </section>

      {/* Drinking window band — only if data present */}
      {drinkingWindow && (
        <section className="mb-8">
          <DrinkingWindowBand
            drinkFrom={drinkingWindow.drinkFrom}
            drinkTo={drinkingWindow.drinkTo}
            label={t("drinkingWindow")}
          />
        </section>
      )}

      {/* Cuvées table */}
      <section className="mb-10">
        <h2 className="text-xl font-display mb-4 text-[color:var(--color-fg)]">{t("cuvees")}</h2>
        {cuvees.length === 0 ? (
          <div className="glass-card p-8 text-center text-[color:var(--color-fg-subtle)] text-sm">
            {t("noCuvees")}
          </div>
        ) : (
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-[color:var(--color-border)]">
                  <tr className="text-left text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                    <th className="px-4 py-3 font-semibold">{t("cuvee")}</th>
                    <th className="px-4 py-3 font-semibold">{tCommon("appellation")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("bestRating")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("priceRange")}</th>
                    <th className="px-4 py-3 font-semibold text-right">{t("sources")}</th>
                  </tr>
                </thead>
                <tbody>
                  {cuvees.map((c) => (
                    <tr
                      key={c.wineKey}
                      className="border-b border-[color:var(--color-border)] last:border-b-0 hover:bg-[rgba(255,92,138,0.04)] transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <ColorDot color={c.color} />
                          <div className="min-w-0">
                            <p className="font-semibold text-[color:var(--color-fg)] leading-tight">
                              {c.cuveeName}
                              {c.vintage && (
                                <span className="ml-2 text-[color:var(--color-fg-muted)] font-mono text-xs">
                                  {c.vintage}
                                </span>
                              )}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[color:var(--color-fg-muted)]">
                        {c.appellationName}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {c.bestRating !== null ? (
                          <span className="text-[color:var(--color-accent)] font-semibold">
                            {c.bestRating.toFixed(1)}/100
                          </span>
                        ) : (
                          <span className="text-[color:var(--color-fg-subtle)]">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right font-mono">
                        {c.priceMin !== null && c.priceMax !== null ? (
                          c.priceMin === c.priceMax ? (
                            <span className="text-[color:var(--color-fg)]">€{c.priceMin.toFixed(2)}</span>
                          ) : (
                            <span className="text-[color:var(--color-fg)]">
                              €{c.priceMin.toFixed(2)} – €{c.priceMax.toFixed(2)}
                            </span>
                          )
                        ) : (
                          <span className="text-[color:var(--color-fg-subtle)]">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <ConfidenceBadge
                          confidence={deriveConfidence(c.sourceCount)}
                          sourceCount={c.sourceCount}
                          labels={{
                            verified: tConf.raw("verified") as string,
                            reviewed: tConf("reviewed"),
                            needs_review: tConf("needs_review"),
                          }}
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

      {/* Charts */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h2 className="text-xl font-display mb-4 text-[color:var(--color-fg)]">
            {t("priceOverTime")}
          </h2>
          <PriceHistoryChart
            data={pricePoints}
            sources={priceSources}
            labels={{
              noData: t("noPriceData"),
              priceAxis: t("priceAxis"),
            }}
          />
        </div>
        <div>
          <h2 className="text-xl font-display mb-4 text-[color:var(--color-fg)]">
            {t("ratingsByCritic")}
          </h2>
          <RatingsByCriticChart
            data={ratingPoints}
            labels={{
              noData: t("noRatingData"),
              scoreAxis: t("ratingAxis"),
            }}
          />
        </div>
      </section>
    </PageShell>
  );
}
