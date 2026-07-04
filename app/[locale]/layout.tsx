import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { setRequestLocale, getMessages } from "next-intl/server";
import { routing } from "@/i18n/routing";
import { SiteNav } from "@/components/site-nav";
import { Fraunces, Inter } from "next/font/google";

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  style: ["normal", "italic"],
});

const inter = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-inter",
  display: "swap",
});

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
      <head>
        {/* Apply the persisted theme before first paint to avoid a flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("achilles-theme");if(t==="dark")document.documentElement.dataset.theme="dark";}catch(e){}`,
          }}
        />
      </head>
      <body className={`${fraunces.variable} ${inter.variable}`} suppressHydrationWarning>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <SiteNav />
          <main className="mx-auto max-w-screen-2xl px-4 sm:px-8 py-8">
            {children}
          </main>
          <footer className="border-t border-[color:var(--color-border)] mt-16 py-6">
            <div className="mx-auto max-w-screen-2xl px-4 sm:px-8 flex items-center justify-between text-xs text-[color:var(--color-fg-subtle)]">
              <span>© 2026 Achilles&apos;s Wines · Personal use</span>
              <span className="text-display text-sm text-[color:var(--color-primary)]">A.</span>
            </div>
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
