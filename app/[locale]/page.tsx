import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { db } from "@/db";
import {
  dimWine,
  dimProducer,
  cellarInventory,
  cellarConsumption,
  factRating,
  opsBatchLog,
  opsDeadLetter,
  factPrice,
} from "@/db/schema";
import { sql, desc, eq } from "drizzle-orm";
import {
  Wine,
  TrendingDown,
  CalendarRange,
  Map,
  Warehouse,
  UtensilsCrossed,
  Sparkles,
  AlertTriangle,
  Activity,
} from "lucide-react";

export const dynamic = "force-dynamic";

async function getStats() {
  try {
    const [bottlesRow] = await db
      .select({ total: sql<number>`coalesce(sum(${cellarInventory.qty}), 0)` })
      .from(cellarInventory);
    const [uniqueRow] = await db
      .select({ total: sql<number>`count(distinct ${dimWine.wineKey})` })
      .from(dimWine);
    const [producersRow] = await db
      .select({ total: sql<number>`count(*)` })
      .from(dimProducer)
      .where(eq(dimProducer.status, "active"));
    const [ratingsRow] = await db
      .select({ total: sql<number>`count(*)` })
      .from(factRating);
    // Use COALESCE(market_avg_price, purchase_price) so wines imported without
    // a purchase price still contribute their market value to the total.
    const marketAvg = db
      .select({
        wineKey: factPrice.wineKey,
        amountEur: sql<number>`avg(${factPrice.amountEur})`.as("amount_eur"),
      })
      .from(factPrice)
      .where(sql`${factPrice.priceKind} = 'market_avg'`)
      .groupBy(factPrice.wineKey)
      .as("market_avg");

    const [valueRow] = await db
      .select({
        total: sql<number>`coalesce(sum(${cellarInventory.qty} * coalesce(${marketAvg.amountEur}, ${cellarInventory.purchasePriceEur})), 0)`,
      })
      .from(cellarInventory)
      .leftJoin(marketAvg, eq(marketAvg.wineKey, cellarInventory.wineKey));
    const [lastBatch] = await db
      .select()
      .from(opsBatchLog)
      .orderBy(desc(opsBatchLog.startedAt))
      .limit(1);
    const [dlqRow] = await db
      .select({ total: sql<number>`count(*)` })
      .from(opsDeadLetter)
      .where(eq(opsDeadLetter.resolution, "pending"));

    return {
      bottles: Number(bottlesRow?.total ?? 0),
      uniqueWines: Number(uniqueRow?.total ?? 0),
      producers: Number(producersRow?.total ?? 0),
      ratings: Number(ratingsRow?.total ?? 0),
      cellarValue: Number(valueRow?.total ?? 0),
      lastIngest: lastBatch?.finishedAt ?? null,
      dlqOpen: Number(dlqRow?.total ?? 0),
    };
  } catch {
    return {
      bottles: 0,
      uniqueWines: 0,
      producers: 0,
      ratings: 0,
      cellarValue: 0,
      lastIngest: null,
      dlqOpen: 0,
    };
  }
}

export default async function DashboardPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("dashboard");
  const tMeta = await getTranslations("meta");
  const tNav = await getTranslations("nav");

  const stats = await getStats();
  const fmt = new Intl.NumberFormat(locale === "fr" ? "fr-FR" : locale);
  const fmtEur = new Intl.NumberFormat(locale === "fr" ? "fr-FR" : locale, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  });

  return (
    <div className="space-y-12">
      {/* Hero */}
      <section className="relative pt-8 pb-10">
        <div className="space-y-5">
          <p className="badge badge-verified w-fit">
            <span className="relative flex size-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full rounded-full bg-[color:var(--color-champagne-400)] opacity-60 motion-safe:animate-ping" />
              <span className="relative inline-flex size-2 rounded-full bg-[color:var(--color-champagne-400)]" />
            </span>
            <span>Athena · v1.3.0</span>
          </p>
          <h1 className="display-xl">
            <span className="text-gradient">Achilles&apos;s</span> Wines.
          </h1>
          <p className="text-lg text-[color:var(--color-fg-muted)] max-w-2xl leading-relaxed">
            {tMeta("tagline")} — {t("subtitle")}
          </p>
        </div>
        {/* Editorial hairline — magenta→champagne, fades to nothing */}
        <div className="mt-10 h-px w-full bg-[linear-gradient(90deg,rgba(165,56,96,0.55),rgba(229,178,93,0.18)_45%,transparent)]" />
      </section>

      {/* Stats grid */}
      <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard label={t("stats.bottles")} value={fmt.format(stats.bottles)} icon={Warehouse} href="/cellar" />
        <StatCard label={t("stats.uniqueWines")} value={fmt.format(stats.uniqueWines)} icon={Wine} href="/domaines" />
        <StatCard label={t("stats.value")} value={fmtEur.format(stats.cellarValue)} icon={TrendingDown} href="/cellar" />
        <StatCard label={t("stats.domaines")} value={fmt.format(stats.producers)} icon={Map} href="/domaines" />
        <StatCard label={t("stats.ratings")} value={fmt.format(stats.ratings)} icon={Sparkles} href="/best-value" />
      </section>

      {/* Quick access */}
      <section className="space-y-4">
        <div className="flex items-end justify-between">
          <h2>{t("quick.title")}</h2>
          <div className="h-px flex-1 ml-6 bg-[color:var(--color-border)]" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <QuickCard href="/best-value" icon={TrendingDown} title={t("quick.bestValueShort")} desc={t("quick.bestValueDesc")} />
          <QuickCard href="/cellar" icon={Warehouse} title={t("quick.drinkNow")} desc={t("quick.drinkNowDesc")} />
          <QuickCard href="/vintages" icon={CalendarRange} title={tNav("vintages")} desc={t("quick.vintagesDesc")} />
          <QuickCard href="/menu" icon={UtensilsCrossed} title={tNav("menu")} desc={t("quick.menuDesc")} />
        </div>
      </section>

      {/* Status row */}
      <section className="glass-card p-6">
        <div className="flex items-start gap-4">
          <div className="size-10 rounded-full bg-[rgba(229,178,93,0.1)] flex items-center justify-center shrink-0">
            <Activity className="size-5 text-[color:var(--color-accent)]" strokeWidth={2.5} />
          </div>
          <div className="flex-1 space-y-1">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-base font-semibold">{t("status.title")}</h3>
              <Link
                href="/qualite"
                className={stats.dlqOpen > 0 ? "badge badge-needs-review" : "badge badge-verified"}
              >
                {stats.dlqOpen > 0 ? (
                  <>
                    <AlertTriangle className="size-3" strokeWidth={2.5} />
                    {t("status.dlqOpen", { count: stats.dlqOpen })}
                  </>
                ) : (
                  t("status.allClear")
                )}
              </Link>
            </div>
            <p className="text-sm text-[color:var(--color-fg-muted)]">
              {stats.lastIngest
                ? t("status.lastIngest", { date: new Intl.DateTimeFormat(locale).format(stats.lastIngest) })
                : t("status.noIngest")}
            </p>
            <p className="text-xs text-[color:var(--color-fg-subtle)] font-mono">
              schema · drizzle · ✓ &nbsp;·&nbsp; i18n · 6 langues · ✓ &nbsp;·&nbsp; design · Athena · ✓
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  tone = "default",
  href,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  tone?: "default" | "warning";
  href?: string;
}) {
  const inner = (
    <>
      <div className="flex items-start justify-between">
        <Icon
          className={
            tone === "warning"
              ? "size-4 text-[color:var(--color-warning)]"
              : "size-4 text-[color:var(--color-champagne-400)]"
          }
          strokeWidth={2}
        />
        {href && (
          <span className="text-xs text-[color:var(--color-fg-subtle)] opacity-0 group-hover:opacity-100 transition-opacity">→</span>
        )}
      </div>
      <div className="mt-3 stat-card-value">{value}</div>
      <div className="stat-card-label">{label}</div>
    </>
  );

  if (href) {
    return (
      <Link href={href as "/cellar"} className="stat-card group block hover:border-[color:var(--color-primary)] transition-colors">
        {inner}
      </Link>
    );
  }
  return <div className="stat-card">{inner}</div>;
}

function QuickCard({
  href,
  icon: Icon,
  title,
  desc,
}: {
  href: string;
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  title: string;
  desc: string;
}) {
  return (
    <Link
      href={href as "/best-value"}
      className="glass-card p-5 group block"
    >
      <div className="flex items-start justify-between mb-4">
        <Icon className="size-5 text-[color:var(--color-magenta-400)] transition-transform group-hover:scale-110" strokeWidth={2} />
        <span className="text-xs text-[color:var(--color-fg-subtle)] group-hover:text-[color:var(--color-primary)] transition-colors">
          →
        </span>
      </div>
      <h3 className="text-base font-semibold text-[color:var(--color-fg)]">{title}</h3>
      <p className="text-xs text-[color:var(--color-fg-muted)] mt-1">{desc}</p>
    </Link>
  );
}
