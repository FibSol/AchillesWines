import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { opsDeadLetter, dimSource } from "@/db/schema";
import { eq, desc } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { AlertTriangle, Check, Ban, EyeOff } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function QuarantinePage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("quarantine");

  const rows = await db
    .select({
      dlq: opsDeadLetter,
      source: dimSource,
    })
    .from(opsDeadLetter)
    .leftJoin(dimSource, eq(opsDeadLetter.sourceKey, dimSource.sourceKey))
    .where(eq(opsDeadLetter.resolution, "pending"))
    .orderBy(desc(opsDeadLetter.createdAt))
    .limit(200);

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge={`${rows.length} en attente`}>
      {rows.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <ShieldCheckBadge />
          <p className="mt-4 text-[color:var(--color-fg-muted)]">Aucun record en quarantaine.</p>
          <p className="text-xs text-[color:var(--color-fg-subtle)] mt-1">Cassandra dort tranquille.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map(({ dlq, source }) => (
            <div key={dlq.dlqId} className="glass-card p-4">
              <div className="flex items-start gap-4">
                <AlertTriangle className="size-5 text-[color:var(--color-coral-400)] mt-0.5 shrink-0" strokeWidth={2} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="badge badge-needs-review text-[10px]">{dlq.errorClass}</span>
                    <span className="text-xs text-[color:var(--color-fg-subtle)]">
                      {source?.sourceName ?? "—"} · {dlq.createdAt ? new Date(dlq.createdAt).toLocaleString(locale) : "—"}
                    </span>
                  </div>
                  <p className="text-sm text-[color:var(--color-fg)] mb-2">{dlq.errorMessage}</p>
                  {dlq.rawRecord != null && (
                    <details className="mt-2">
                      <summary className="text-xs text-[color:var(--color-fg-muted)] cursor-pointer hover:text-[color:var(--color-primary)]">
                        Raw record
                      </summary>
                      <pre className="mt-2 text-[10px] bg-[color:var(--color-aubergine-950)] p-3 rounded-md overflow-x-auto font-mono">
                        {JSON.stringify(dlq.rawRecord, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
                <div className="flex flex-col gap-1.5 shrink-0">
                  <button className="btn btn-primary text-xs">
                    <Check className="size-3.5" strokeWidth={3} />
                    {t("approve")}
                  </button>
                  <button className="btn btn-ghost text-xs">
                    <Ban className="size-3.5" strokeWidth={2.5} />
                    {t("blacklist")}
                  </button>
                  <button className="btn btn-ghost text-xs">
                    <EyeOff className="size-3.5" strokeWidth={2.5} />
                    {t("ignore")}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}

function ShieldCheckBadge() {
  return (
    <div className="size-16 rounded-full bg-[rgba(111,255,233,0.1)] mx-auto flex items-center justify-center">
      <Check className="size-7 text-[color:var(--color-accent)]" strokeWidth={2.5} />
    </div>
  );
}
