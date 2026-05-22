import { getTranslations, setRequestLocale } from "next-intl/server";
import Link from "next/link";
import { db } from "@/db";
import { dimProducer } from "@/db/schema";
import { eq, desc, like, or, and, sql, asc, isNotNull, type SQL } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { CsvActions, type CsvLabels } from "@/components/CsvActions";
import { DomainesFilters, type CountryRegion, type DomainesFiltersLabels } from "@/components/DomainesFilters";
import { MapPin, Globe } from "lucide-react";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 100;

interface SearchParams {
  q?: string;
  country?: string;
  region?: string;
  tier?: string;
}

export default async function DomainesPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const { locale } = await params;
  const sp = await searchParams;
  setRequestLocale(locale);
  const t = await getTranslations("domaines");
  const tCommon = await getTranslations("common");

  // Always restrict to active producers (Cassandra's region gate already
  // moves bad rows to pending_review).
  const conditions: SQL[] = [eq(dimProducer.status, "active")];

  if (sp.q && sp.q.trim()) {
    const needle = `%${sp.q.trim().toLowerCase()}%`;
    const orClause = or(
      like(sql<string>`lower(${dimProducer.producerName})`, needle),
      like(sql<string>`lower(${dimProducer.producerNorm})`, needle),
    );
    if (orClause) conditions.push(orClause);
  }
  if (sp.country) {
    conditions.push(eq(dimProducer.countryCode, sp.country));
  }
  if (sp.region) {
    conditions.push(eq(dimProducer.region, sp.region));
  }
  const tierNum = sp.tier ? Number.parseInt(sp.tier, 10) : NaN;
  if (Number.isFinite(tierNum)) {
    conditions.push(eq(dimProducer.tier, tierNum));
  }

  const whereExpr = conditions.length === 1 ? conditions[0] : and(...conditions);

  const [producers, [countRow], countryRegionRows, tierRows] = await Promise.all([
    db
      .select()
      .from(dimProducer)
      .where(whereExpr)
      .orderBy(desc(dimProducer.tier), dimProducer.producerName)
      .limit(PAGE_SIZE),
    db
      .select({ total: sql<number>`count(*)` })
      .from(dimProducer)
      .where(whereExpr),
    db
      .selectDistinct({
        country: dimProducer.countryCode,
        region: dimProducer.region,
      })
      .from(dimProducer)
      .where(eq(dimProducer.status, "active"))
      .orderBy(asc(dimProducer.countryCode), asc(dimProducer.region)),
    db
      .selectDistinct({ tier: dimProducer.tier })
      .from(dimProducer)
      .where(and(eq(dimProducer.status, "active"), isNotNull(dimProducer.tier)))
      .orderBy(asc(dimProducer.tier)),
  ]);

  const totalMatching = Number(countRow?.total ?? 0);
  const countryRegions: CountryRegion[] = countryRegionRows.map((r) => ({
    country: r.country,
    region: r.region,
  }));
  const tiers = tierRows
    .map((r) => r.tier)
    .filter((t): t is number => t !== null);

  const csvLabels: CsvLabels = {
    importBtn: t("importCsv"),
    exportBtn: t("exportCsv"),
    templateBtn: t("downloadTemplate"),
    importTitle: t("csv.importTitle"),
    importing: t("csv.importing"),
    close: t("csv.close"),
    resultAccepted: t("csv.accepted"),
    resultInserted: t("csv.inserted"),
    resultMerged: t("csv.updated"),
    resultRejected: t("csv.rejected"),
    resultDetails: t("csv.details"),
    resultDone: t("csv.done"),
    uploadError: t("csv.uploadError"),
  };

  const filterLabels: DomainesFiltersLabels = {
    searchPlaceholder: t("filters.searchPlaceholder"),
    allCountries: t("filters.allCountries"),
    allRegions: t("filters.allRegions"),
    tier: t("filters.tier"),
    allTiers: t("filters.allTiers"),
    clear: t("filters.clear"),
    showing: t("filters.showing"),
    matchingOf: t("filters.matchingOf"),
    noMatches: t("filters.noMatches"),
  };

  return (
    <PageShell
      title={t("title")}
      subtitle={t("subtitle")}
      badge={`${totalMatching} ${tCommon("producer").toLowerCase()}s`}
    >
      <div className="space-y-6 mb-6">
        <CsvActions
          endpoints={{
            export: "/api/producers/export",
            template: "/api/producers/template",
            import: "/api/producers/import",
          }}
          labels={csvLabels}
        />
        <DomainesFilters
          countryRegions={countryRegions}
          tiers={tiers}
          labels={filterLabels}
          totalShown={producers.length}
          totalMatching={totalMatching}
        />
      </div>

      {producers.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <p className="text-[color:var(--color-fg-muted)]">
            {totalMatching === 0 ? t("filters.noMatches") : tCommon("empty")}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {producers.map((p) => (
            <Link
              key={p.producerKey}
              href={`/${locale}/domaines/${p.producerKey}`}
              className="glass-card p-5 block"
            >
              <div className="flex items-start justify-between gap-3 mb-3">
                <h3 className="font-semibold text-base text-[color:var(--color-fg)] leading-tight">{p.producerName}</h3>
                {p.tier && (
                  <span className="badge badge-verified shrink-0 text-[10px] py-0.5">T{p.tier}</span>
                )}
              </div>
              <div className="space-y-1.5 text-xs text-[color:var(--color-fg-muted)]">
                <div className="flex items-center gap-1.5">
                  <MapPin className="size-3" strokeWidth={2.5} />
                  <span>
                    {p.region}
                    {p.subregion && ` · ${p.subregion}`}
                    {` · ${p.countryCode}`}
                  </span>
                </div>
                {p.website && (
                  <div className="flex items-center gap-1.5">
                    <Globe className="size-3" strokeWidth={2.5} />
                    <span className="text-[color:var(--color-coral-400)] truncate">
                      {p.website.replace(/^https?:\/\//, "")}
                    </span>
                  </div>
                )}
                {p.allowedAppellations && p.allowedAppellations.length > 0 && (
                  <p className="text-[10px] text-[color:var(--color-fg-subtle)] mt-2 line-clamp-2 font-mono">
                    {p.allowedAppellations.slice(0, 3).join(" · ")}
                    {p.allowedAppellations.length > 3 && ` +${p.allowedAppellations.length - 3}`}
                  </p>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </PageShell>
  );
}
