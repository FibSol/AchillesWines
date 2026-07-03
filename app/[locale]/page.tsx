import { getTranslations, setRequestLocale } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { getDashboardStats } from "@/lib/queries/stats";
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

  const stats = await getDashboardStats();
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
          <p className="micro-label">Athena · v1.3.0</p>
          <h1 className="display-xl">Achilles&apos;s Wines</h1>
          <p className="text-base text-[color:var(--color-fg-muted)] max-w-2xl leading-relaxed">
            {tMeta("tagline")} — {t("subtitle")}
          </p>
        </div>
        <div className="mt-10 h-px w-full bg-[color:var(--color-border)]" />
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
