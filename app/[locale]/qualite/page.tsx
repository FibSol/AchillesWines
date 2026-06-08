import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import {
  dimWine,
  opsDeadLetter,
  factPrice,
  factRating,
  opsBatchLog,
  stagingPriceCandidates,
} from "@/db/schema";
import { sql, eq, desc } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { ShieldCheck, AlertTriangle, Activity, Settings2, ArrowRight, Database, TrendingUp } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { PromoteButton } from "@/components/promote-button";

export const dynamic = "force-dynamic";

export default async function QualityPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("quality");

  // Stat card queries
  const [totalWines] = await db.select({ n: sql<number>`count(*)` }).from(dimWine);
  const [pendingDlq] = await db
    .select({ n: sql<number>`count(*)` })
    .from(opsDeadLetter)
    .where(eq(opsDeadLetter.resolution, "pending"));
  const [pricesTotal] = await db.select({ n: sql<number>`count(*)` }).from(factPrice);
  const [ratingsTotal] = await db.select({ n: sql<number>`count(*)` }).from(factRating);

  // Staging pending (needs_review=1)
  const [stagingPending] = await db
    .select({ n: sql<number>`count(*)` })
    .from(stagingPriceCandidates)
    .where(eq(stagingPriceCandidates.needsReview, true));

  // Truly promotable: ≥2 distinct sources AND price spread within ±15% tolerance
  // MAX/MIN ≤ 1.35 approximates "both prices within ±15% of the median"
  const promotableRows = await db
    .select({ wineKey: stagingPriceCandidates.wineKey })
    .from(stagingPriceCandidates)
    .where(eq(stagingPriceCandidates.needsReview, true))
    .groupBy(stagingPriceCandidates.wineKey)
    .having(
      sql`count(distinct ${stagingPriceCandidates.sourceKey}) >= 2
        AND min(${stagingPriceCandidates.amountEur}) > 0
        AND max(${stagingPriceCandidates.amountEur}) / min(${stagingPriceCandidates.amountEur}) <= 1.35`
    );
  const promotableCount = promotableRows.length;

  // Recent batches (20 rows)
  const recentBatches = await db
    .select()
    .from(opsBatchLog)
    .orderBy(desc(opsBatchLog.startedAt))
    .limit(20);

  const stagingPendingNum = Number(stagingPending?.n ?? 0);
  const pricesNum = Number(pricesTotal?.n ?? 0);

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="Cassandra's dashboard">
      {/* Quick actions */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Link
          href="/admin/jobs"
          className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--color-primary)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
        >
          <Settings2 className="size-4" />
          {t("launchScraper")}
        </Link>
        <Link
          href="/quarantaine"
          className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-border)] bg-[rgba(255,255,255,0.04)] px-4 py-2 text-sm font-semibold text-[color:var(--color-fg)] transition-colors hover:bg-[rgba(255,255,255,0.08)]"
        >
          <AlertTriangle className="size-4 text-[color:var(--color-warning)]" strokeWidth={2} />
          {t("viewQuarantine")}
        </Link>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <div className="stat-card">
          <ShieldCheck className="size-4 text-[color:var(--color-mint-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(totalWines?.n ?? 0).toLocaleString()}</div>
          <div className="stat-card-label">{t("verifiedCount")}</div>
        </div>
        <div className="stat-card">
          <Activity className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{pricesNum.toLocaleString()}</div>
          <div className="stat-card-label">{t("pricesCount")}</div>
        </div>
        <div className="stat-card">
          <Activity className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(ratingsTotal?.n ?? 0).toLocaleString()}</div>
          <div className="stat-card-label">{t("ratingsCount")}</div>
        </div>
        <div className="stat-card">
          <AlertTriangle className="size-4 text-[color:var(--color-warning)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(pendingDlq?.n ?? 0).toLocaleString()}</div>
          <div className="stat-card-label">{t("needsReviewCount")}</div>
        </div>
        <div className="stat-card">
          <Database className="size-4 text-[color:var(--color-fg-muted)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{stagingPendingNum.toLocaleString()}</div>
          <div className="stat-card-label">{t("stagingPending")}</div>
        </div>
        <div className="stat-card">
          <TrendingUp className="size-4 text-emerald-400" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{promotableCount.toLocaleString()}</div>
          <div className="stat-card-label">{t("promotable")}</div>
        </div>
      </div>

      {/* Pipeline funnel */}
      <section className="mt-10 space-y-3">
        <h2 className="text-xl font-semibold">{t("promotePipeline")}</h2>
        <div className="glass-card p-6">
          <div className="flex flex-wrap items-center gap-2 mb-6">
            <div className="flex flex-col items-center gap-1 px-4 py-3 rounded-lg bg-[rgba(255,255,255,0.05)]">
              <span className="text-2xl font-bold text-[color:var(--color-fg)]">
                {stagingPendingNum.toLocaleString()}
              </span>
              <span className="text-xs text-[color:var(--color-fg-muted)]">{t("stagingPending")}</span>
            </div>
            <ArrowRight className="size-5 text-[color:var(--color-fg-subtle)] shrink-0" strokeWidth={1.5} />
            <div className="flex flex-col items-center gap-1 px-4 py-3 rounded-lg bg-[rgba(255,255,255,0.05)]">
              <span className="text-2xl font-bold text-emerald-400">
                {promotableCount.toLocaleString()}
              </span>
              <span className="text-xs text-[color:var(--color-fg-muted)]">{t("promotable")}</span>
            </div>
            <ArrowRight className="size-5 text-[color:var(--color-fg-subtle)] shrink-0" strokeWidth={1.5} />
            <div className="flex flex-col items-center gap-1 px-4 py-3 rounded-lg bg-[rgba(255,255,255,0.05)]">
              <span className="text-2xl font-bold text-[color:var(--color-accent)]">
                {pricesNum.toLocaleString()}
              </span>
              <span className="text-xs text-[color:var(--color-fg-muted)]">{t("pricesCount")}</span>
            </div>
          </div>
          <PromoteButton />
        </div>
      </section>

      {/* Recent batches */}
      <section className="mt-10 space-y-3">
        <h2 className="text-xl font-semibold">{t("recentBatches")}</h2>
        <div className="glass-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-[color:var(--color-fg-subtle)]">
              <tr>
                <th className="text-left p-3">batch_id</th>
                <th className="text-left p-3">started</th>
                <th className="text-right p-3">fetched</th>
                <th className="text-right p-3">inserted</th>
                <th className="text-right p-3">dlq</th>
                <th className="text-left p-3">status</th>
              </tr>
            </thead>
            <tbody>
              {recentBatches.length === 0 ? (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-[color:var(--color-fg-muted)]">
                    {t("noBatches")}
                  </td>
                </tr>
              ) : (
                recentBatches.map((b) => (
                  <tr key={b.batchId} className="border-t border-[color:var(--color-border)]">
                    <td className="p-3 font-mono text-xs">{b.batchId}</td>
                    <td className="p-3 text-xs">
                      {b.startedAt ? new Date(b.startedAt).toLocaleString(locale) : "—"}
                    </td>
                    <td className="p-3 text-right">{b.rowsFetched}</td>
                    <td className="p-3 text-right text-[color:var(--color-accent)]">{b.rowsInserted}</td>
                    <td className="p-3 text-right text-[color:var(--color-warning)]">{b.rowsDlq}</td>
                    <td className="p-3">
                      <span
                        className={
                          b.status === "success"
                            ? "badge badge-verified"
                            : b.status === "failed"
                              ? "badge badge-needs-review"
                              : "badge badge-reviewed"
                        }
                      >
                        {b.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </PageShell>
  );
}
