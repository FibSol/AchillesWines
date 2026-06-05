import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { TastingStudio } from "@/components/TastingStudio";

export const dynamic = "force-dynamic";

export default async function TastingPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("tasting");

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")}>
      <TastingStudio />
    </PageShell>
  );
}
