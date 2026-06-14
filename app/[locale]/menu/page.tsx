import { getTranslations, setRequestLocale } from "next-intl/server";
import { PageShell } from "@/components/page-shell";
import { MenuComposer, type MenuLabels } from "@/components/MenuComposer";

export const dynamic = "force-dynamic";

export default async function MenuPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("menu");
  const tConf = await getTranslations("confidence");

  const labels: MenuLabels = {
    courseTypes: {
      aperitif: t("courseTypes.aperitif"),
      entree: t("courseTypes.entree"),
      plat: t("courseTypes.plat"),
      fromage: t("courseTypes.fromage"),
      dessert: t("courseTypes.dessert"),
      other: t("courseTypes.other"),
    },
    courses: t("courses"),
    budget: t("budget"),
    guests: t("guests"),
    addCourse: t("addCourse"),
    propose: t("propose"),
    proposing: t("proposing"),
    dishPlaceholder: t("dishPlaceholder"),
    remove: t("remove"),
    noPicks: t("noPicks"),
    noPoolBottlesYet: t("noPoolBottlesYet"),
    scoreLabel: t("scoreLabel"),
    poolSize: t("poolSize"),
    budgetPerGuest: t("budgetPerGuest"),
    fromCellar: t("fromCellar"),
    fromRegistry: t("fromRegistry"),
    consumeBtn: t("consumeBtn"),
    consumeQty: t("consumeQty"),
    consumeConfirm: t("consumeConfirm"),
    consumeCancel: t("consumeCancel"),
    consumeSuccess: t("consumeSuccess"),
    confidence: {
      verified: tConf.raw("verified") as string,
      reviewed: tConf("reviewed"),
      needs_review: tConf("needs_review"),
    },
  };

  return (
    <PageShell title={t("title")} subtitle={t("subtitle")} badge="Sprint 6 · P2">
      <MenuComposer labels={labels} />
    </PageShell>
  );
}
