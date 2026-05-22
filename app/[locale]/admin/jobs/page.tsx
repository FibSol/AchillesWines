import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { JobsTable } from "@/components/jobs-table";

export const dynamic = "force-dynamic";

export default async function AdminJobsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("adminJobs");
  return (
    <PageShell
      title={t("title")}
      subtitle={t("subtitle")}
      badge="ADR-006"
    >
      <JobsTable />
    </PageShell>
  );
}
