"use client";

import { useLocale } from "next-intl";
import { useRouter, usePathname } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";
import { useTransition } from "react";
import { Globe } from "lucide-react";

const LOCALE_LABELS: Record<string, string> = {
  fr: "FR",
  en: "EN",
  nl: "NL",
  de: "DE",
  es: "ES",
  it: "IT",
};

export function LanguageSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  return (
    <div className="relative">
      <select
        aria-label="Change language"
        defaultValue={locale}
        disabled={isPending}
        onChange={(e) => {
          const next = e.target.value as (typeof routing.locales)[number];
          startTransition(() => {
            router.replace(pathname, { locale: next });
          });
        }}
        className="appearance-none cursor-pointer rounded-lg border border-[color:var(--color-border)] bg-transparent pl-8 pr-3 py-1.5 text-xs font-semibold text-[color:var(--color-fg)] hover:border-[color:var(--color-border-strong)] focus:outline-none focus:ring-2 focus:ring-[color:var(--color-primary)] transition-all"
      >
        {routing.locales.map((loc) => (
          <option key={loc} value={loc} className="bg-[color:var(--color-bg)] text-[color:var(--color-fg)]">
            {LOCALE_LABELS[loc]}
          </option>
        ))}
      </select>
      <Globe className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-[color:var(--color-fg-subtle)] pointer-events-none" strokeWidth={2.5} />
    </div>
  );
}
