import { getTranslations, setRequestLocale } from "next-intl/server";
import Link from "next/link";
import { PageShell } from "@/components/page-shell";
import { CsvActions, type CsvLabels } from "@/components/CsvActions";
import { DomainesFilters, type DomainesFiltersLabels } from "@/components/DomainesFilters";
import { DomaineSidebar } from "@/components/DomaineSidebar";
import { MapPin, Globe } from "lucide-react";
import { getProducers } from "@/lib/queries/producers";

export const dynamic = "force-dynamic";

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

  const { producers, totalMatching, totalAll, facets } = await getProducers({
    q: sp.q,
    country: sp.country,
    region: sp.region,
    tier: sp.tier ? Number.parseInt(sp.tier, 10) : undefined,
  });
  const sidebarCountries = facets.countries;
  const tiers = facets.tiers;

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
      <div className="mb-4">
        <CsvActions
          endpoints={{
            export: "/api/producers/export",
            template: "/api/producers/template",
            import: "/api/producers/import",
          }}
          labels={csvLabels}
        />
      </div>

      <div className="flex gap-6 items-start">
        {/* Left sidebar */}
        <DomaineSidebar
          countries={sidebarCountries}
          allLabel={t("filters.allCountries")}
          allCount={totalAll}
        />

        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-5">
          <DomainesFilters
            tiers={tiers}
            labels={filterLabels}
            totalShown={producers.length}
            totalMatching={totalMatching}
          />

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
                        <span className="text-[color:var(--color-champagne-400)] truncate">
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
        </div>
      </div>
    </PageShell>
  );
}
