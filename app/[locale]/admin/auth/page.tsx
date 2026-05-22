import { getTranslations, setRequestLocale } from "next-intl/server";
import { db } from "@/db";
import { dimSource } from "@/db/schema";
import { eq, asc } from "drizzle-orm";
import { PageShell } from "@/components/page-shell";
import { AuthSourceList, type AuthSourceRow } from "@/components/AuthSourceList";

export const dynamic = "force-dynamic";

function envKey(sourceCode: string): string {
  return sourceCode.toUpperCase().replace(/-/g, "_");
}

function hasCredentials(sourceCode: string): boolean {
  const k = envKey(sourceCode);
  const u = process.env[`ACHILLES_AUTH_${k}_USERNAME`]?.trim() ?? "";
  const p = process.env[`ACHILLES_AUTH_${k}_PASSWORD`] ?? "";
  return u.length > 0 && p.length > 0;
}

export default async function AdminAuthPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("adminAuth");

  const sources = await db
    .select({
      sourceKey: dimSource.sourceKey,
      sourceCode: dimSource.sourceCode,
      sourceName: dimSource.sourceName,
      sourceTier: dimSource.sourceTier,
      baseUrl: dimSource.baseUrl,
      requiresAuth: dimSource.requiresAuth,
      enabled: dimSource.enabled,
    })
    .from(dimSource)
    .where(eq(dimSource.requiresAuth, true))
    .orderBy(asc(dimSource.sourceCode));

  const rows: AuthSourceRow[] = sources.map((s) => ({
    sourceKey: s.sourceKey,
    sourceCode: s.sourceCode,
    sourceName: s.sourceName,
    sourceTier: s.sourceTier,
    baseUrl: s.baseUrl,
    enabled: s.enabled,
    hasCredentials: hasCredentials(s.sourceCode),
    envUserVar: `ACHILLES_AUTH_${envKey(s.sourceCode)}_USERNAME`,
    envPassVar: `ACHILLES_AUTH_${envKey(s.sourceCode)}_PASSWORD`,
  }));

  return (
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
  );
}
