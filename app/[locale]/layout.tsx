import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { setRequestLocale, getMessages } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { SiteNav } from "@/components/site-nav";

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export const metadata: Metadata = {
  title: {
    template: "%s · Achilles's Wines",
    default: "Achilles's Wines",
  },
  description: "Vinothèque familiale, multi-source, multi-langue.",
  applicationName: "Achilles's Wines",
};

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }
  setRequestLocale(locale);
  const messages = await getMessages();

  return (
    <html lang={locale} suppressHydrationWarning>
      <body className="grain" suppressHydrationWarning>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <SiteNav />
          <main className="mx-auto max-w-screen-2xl px-4 sm:px-8 py-8">
            {children}
          </main>
          <footer className="border-t border-[color:var(--color-border)] mt-16 py-6">
            <div className="mx-auto max-w-screen-2xl px-4 sm:px-8 flex items-center justify-between text-xs text-[color:var(--color-fg-subtle)]">
              <span>© 2026 Achilles&apos;s Wines · Personal use</span>
              <span className="text-display italic text-sm text-gradient">A.</span>
            </div>
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
