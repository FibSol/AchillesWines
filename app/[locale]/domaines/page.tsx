import { getTranslations, setRequestLocale } from "next-intl/server";
import Link from "next/link";
import { db } from "@/db";
import { dimProducer } from "@/db/schema";
import { eq, desc } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { MapPin, Globe } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function DomainesPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("domaines");
  const tCommon = await getTranslations("common");

  const producers = await db
    .select()
    .from(dimProducer)
    .where(eq(dimProducer.status, "active"))
    .orderBy(desc(dimProducer.tier), dimProducer.producerName)
    .limit(100);

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge={`${producers.length} ${tCommon("producer").toLowerCase()}s`}>
      <div className="flex items-center gap-3 mb-6">
        <button className="btn btn-ghost text-xs">{t("exportCsv")}</button>
        <button className="btn btn-ghost text-xs">{t("importCsv")}</button>
        <button className="btn btn-ghost text-xs">{t("downloadTemplate")}</button>
      </div>

      {producers.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <p className="text-[color:var(--color-fg-muted)]">
            {tCommon("empty")} — import du registry burgundy-manager à venir.
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
