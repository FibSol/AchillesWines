import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { WineMapLoader } from "@/components/WineMapLoader";
import { TierFilter } from "@/components/TierFilter";
import { parseTiers, getMapData } from "@/lib/queries/map";
import { Suspense } from "react";

export const dynamic = "force-dynamic";

export default async function MapPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;
  const sp = await searchParams;
  setRequestLocale(locale);
  const t = await getTranslations("map");

  const { numeric, includeNull } = parseTiers(sp.tiers);
  const selectedKeys = [
    ...numeric.map(String),
    ...(includeNull ? ["null"] : []),
  ];

  const { producers, appellations } = await getMapData({ numeric, includeNull });

  const badge =
    producers.length > 0
      ? `${producers.length} ${t("legendProducers").toLowerCase()} · ${appellations.length} ${t("legendAppellations").toLowerCase()}`
      : "Sprint 3 · P1";

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge={badge}>
      <Suspense>
        <TierFilter selected={selectedKeys} />
      </Suspense>
      <WineMapLoader
        producers={producers}
        appellations={appellations}
        locale={locale}
        labels={{
          noData: t("noData"),
          legendProducers: t("legendProducers"),
          legendAppellations: t("legendAppellations"),
          legendRegions: t("legendRegions"),
        }}
      />
    </PageShell>
  );
}
