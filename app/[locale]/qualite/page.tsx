import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimWine, opsDeadLetter, factPrice, factRating, opsBatchLog } from "@/db/schema";
import { sql, eq, desc } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { ShieldCheck, AlertTriangle, Activity, Settings2 } from "lucide-react";
import { Link } from "@/i18n/navigation";

export const dynamic = "force-dynamic";

export default async function QualityPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("quality");

  const [totalWines] = await db.select({ n: sql<number>`count(*)` }).from(dimWine);
  const [pendingDlq] = await db
    .select({ n: sql<number>`count(*)` })
    .from(opsDeadLetter)
    .where(eq(opsDeadLetter.resolution, "pending"));
  const [pricesTotal] = await db.select({ n: sql<number>`count(*)` }).from(factPrice);
  const [ratingsTotal] = await db.select({ n: sql<number>`count(*)` }).from(factRating);
  const recentBatches = await db
    .select()
    .from(opsBatchLog)
    .orderBy(desc(opsBatchLog.startedAt))
    .limit(5);

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="Cassandra's dashboard">
      <div className="mb-6">
        <Link
          href="/admin/jobs"
          className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--color-primary)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90"
        >
          <Settings2 className="size-4" />
          🚀 Lancer un scraper
        </Link>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="stat-card">
          <ShieldCheck className="size-4 text-[color:var(--color-mint-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(totalWines?.n ?? 0)}</div>
          <div className="stat-card-label">{t("verifiedCount")}</div>
        </div>
        <div className="stat-card">
          <Activity className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(pricesTotal?.n ?? 0)}</div>
          <div className="stat-card-label">fact_price rows</div>
        </div>
        <div className="stat-card">
          <Activity className="size-4 text-[color:var(--color-coral-400)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(ratingsTotal?.n ?? 0)}</div>
          <div className="stat-card-label">fact_rating rows</div>
        </div>
        <div className="stat-card">
          <AlertTriangle className="size-4 text-[color:var(--color-warning)]" strokeWidth={2} />
          <div className="mt-3 stat-card-value">{Number(pendingDlq?.n ?? 0)}</div>
          <div className="stat-card-label">{t("needsReviewCount")}</div>
        </div>
      </div>

      <section className="mt-12 space-y-3">
        <h2 className="text-2xl">Dernières ingestions</h2>
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
                    Aucune ingestion. Lance le scraper depuis le sidecar Python.
                  </td>
                </tr>
              ) : (
                recentBatches.map((b) => (
                  <tr key={b.batchId} className="border-t border-[color:var(--color-border)]">
                    <td className="p-3 font-mono text-xs">{b.batchId}</td>
                    <td className="p-3 text-xs">{b.startedAt ? new Date(b.startedAt).toLocaleString(locale) : "—"}</td>
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
