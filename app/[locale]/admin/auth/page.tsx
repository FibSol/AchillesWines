import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { AuthSourceList } from "@/components/AuthSourceList";
import { SchedulePanel } from "@/components/SchedulePanel";
import { getAuthSources } from "@/lib/queries/ops";

export const dynamic = "force-dynamic";

export default async function AdminAuthPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("adminAuth");
  const ts = await getTranslations("adminSchedule");

  const rows = await getAuthSources();

  const scheduleLabels = {
    title: ts("title"),
    subtitle: ts("subtitle"),
    source: ts("source"),
    cronExpr: ts("cronExpr"),
    description: ts("description"),
    save: ts("save"),
    clear: ts("clear"),
    saved: ts("saved"),
    invalid: ts("invalid"),
    placeholder: ts("placeholder"),
    manualOnly: ts("manualOnly"),
    groupRetail: ts("groupRetail"),
    groupEmail: ts("groupEmail"),
    groupCritic: ts("groupCritic"),
    groupVintage: ts("groupVintage"),
    restartHint: ts("restartHint"),
  };

  return (
    <div className="space-y-12">
      <PageShell
        title={t("title")}
        subtitle={t("subtitle")}
        badge={`${rows.length} ${t("sources").toLowerCase()}`}
      >
        <AuthSourceList
          rows={rows}
          labels={{
            source: t("source"),
            status: t("status"),
            envVars: t("envVars"),
            credsPresent: t("credsPresent"),
            credsMissing: t("credsMissing"),
            testLogin: t("testLogin"),
            testing: t("testing"),
            empty: t("empty"),
            jobQueued: t("jobQueued"),
            viewJob: t("viewJob"),
            docsHint: t("docsHint"),
            docsLink: t("docsLink"),
          }}
          locale={locale}
        />
      </PageShell>

      <PageShell
        title={ts("title")}
        subtitle={ts("subtitle")}
      >
        <SchedulePanel labels={scheduleLabels} />
      </PageShell>
    </div>
  );
}
