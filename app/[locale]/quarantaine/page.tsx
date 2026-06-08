import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { opsDeadLetter, dimSource } from "@/db/schema";
import { eq, desc, and } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { Check } from "lucide-react";
import { DlqCard } from "@/components/dlq-card";
import { Link } from "@/i18n/navigation";

export const dynamic = "force-dynamic";

// All valid error classes for the filter pills
const ERROR_CLASSES = [
  "network_error",
  "parse_error",
  "schema_drift",
  "auth_error",
  "validation_error",
  "region_gate",
  "critic_enum",
  "multi_source_rule",
  "reconcile_error",
  "fx_missing",
  "unresolved_dim",
  "unmatched_wine",
  "scraper_not_applicable",
  "source_dead",
] as const;

type ErrorClass = (typeof ERROR_CLASSES)[number];

function isErrorClass(v: string): v is ErrorClass {
  return (ERROR_CLASSES as readonly string[]).includes(v);
}

export default async function QuarantinePage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ class?: string }>;
}) {
  const { locale } = await params;
  const sp = await searchParams;
  setRequestLocale(locale);
  const t = await getTranslations("quarantine");

  const filterClass = sp.class && isErrorClass(sp.class) ? sp.class : null;

  const whereClause = filterClass
    ? and(
        eq(opsDeadLetter.resolution, "pending"),
        eq(opsDeadLetter.errorClass, filterClass)
      )
    : eq(opsDeadLetter.resolution, "pending");

  const rows = await db
    .select({
      dlq: opsDeadLetter,
      source: dimSource,
    })
    .from(opsDeadLetter)
    .leftJoin(dimSource, eq(opsDeadLetter.sourceKey, dimSource.sourceKey))
    .where(whereClause)
    .orderBy(desc(opsDeadLetter.createdAt))
    .limit(200);

  const labels = {
    approve: t("approve"),
    blacklist: t("blacklist"),
    ignore: t("ignore"),
  };

  return (
    <PageShell
      title={t("title")}
      subtitle={t("subtitle")}
      badge={`${rows.length}${filterClass ? ` · ${filterClass}` : ""} en attente`}
    >
      {/* Filter bar */}
      <div className="mb-6 flex flex-wrap gap-2 items-center">
        <Link
          href="/quarantaine"
          className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
            !filterClass
              ? "bg-[color:var(--color-primary)] border-[color:var(--color-primary)] text-white"
              : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-primary)] hover:text-[color:var(--color-fg)]"
          }`}
        >
          {t("allClasses")}
        </Link>
        {ERROR_CLASSES.map((cls) => (
          <Link
            key={cls}
            href={`/quarantaine?class=${cls}`}
            className={`rounded-full px-3 py-1 text-xs font-medium border transition-colors ${
              filterClass === cls
                ? "bg-[color:var(--color-primary)] border-[color:var(--color-primary)] text-white"
                : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-primary)] hover:text-[color:var(--color-fg)]"
            }`}
          >
            {cls}
          </Link>
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <ShieldCheckBadge />
          <p className="mt-4 text-[color:var(--color-fg-muted)]">Aucun record en quarantaine.</p>
          <p className="text-xs text-[color:var(--color-fg-subtle)] mt-1">Cassandra dort tranquille.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map(({ dlq, source }) => (
            <DlqCard
              key={dlq.dlqId}
              dlq={{
                dlqId: dlq.dlqId,
                errorClass: dlq.errorClass,
                errorMessage: dlq.errorMessage,
                rawRecord: dlq.rawRecord,
                createdAt: dlq.createdAt,
                sourceKey: dlq.sourceKey,
              }}
              sourceName={source?.sourceName ?? null}
              locale={locale}
              labels={labels}
            />
          ))}
        </div>
      )}
    </PageShell>
  );
}

function ShieldCheckBadge() {
  return (
    <div className="size-16 rounded-full bg-[rgba(229,178,93,0.1)] mx-auto flex items-center justify-center">
      <Check className="size-7 text-[color:var(--color-accent)]" strokeWidth={2.5} />
    </div>
  );
}
