"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { LanguageSwitcher } from "./language-switcher";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Wine,
  TrendingDown,
  CalendarRange,
  Map,
  Warehouse,
  UtensilsCrossed,
  ShieldCheck,
  AlertTriangle,
  Settings2,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", key: "dashboard", icon: LayoutDashboard },
  { href: "/domaines", key: "domaines", icon: Wine },
  { href: "/best-value", key: "bestValue", icon: TrendingDown },
  { href: "/vintages", key: "vintages", icon: CalendarRange },
  { href: "/map", key: "map", icon: Map },
  { href: "/cellar", key: "cellar", icon: Warehouse },
  { href: "/menu", key: "menu", icon: UtensilsCrossed },
] as const;

const ADMIN_ITEMS = [
  { href: "/qualite", key: "quality", icon: ShieldCheck },
  { href: "/quarantaine", key: "quarantine", icon: AlertTriangle },
  { href: "/admin/jobs", key: "adminJobs", icon: Settings2 },
] as const;

export function SiteNav() {
  const t = useTranslations("nav");
  const tMeta = useTranslations("meta");
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <header className="sticky top-0 z-40 border-b border-[color:var(--color-border)] bg-[rgba(13,6,26,0.85)] backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-screen-2xl items-center gap-6 px-4 sm:px-8">
        <Link href="/" className="flex items-center gap-2 group">
          <span className="text-display text-2xl text-gradient">A.</span>
          <span className="hidden sm:inline font-semibold tracking-tight text-[color:var(--color-fg)]">
            {tMeta("appName")}
          </span>
        </Link>

        <nav className="hidden md:flex items-center gap-1 ml-4">
          {NAV_ITEMS.map(({ href, key, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-all",
                isActive(href)
                  ? "bg-[rgba(255,92,138,0.12)] text-[color:var(--color-primary)]"
                  : "text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] hover:bg-[rgba(255,92,138,0.06)]"
              )}
            >
              <Icon className="size-3.5" strokeWidth={2.5} />
              {t(key)}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          {ADMIN_ITEMS.map(({ href, key, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              title={t(key)}
              className={cn(
                "inline-flex items-center justify-center rounded-lg p-2 transition-all",
                isActive(href)
                  ? "bg-[rgba(255,92,138,0.12)] text-[color:var(--color-primary)]"
                  : "text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg)] hover:bg-[rgba(255,92,138,0.06)]"
              )}
            >
              <Icon className="size-4" strokeWidth={2} />
            </Link>
          ))}
          <LanguageSwitcher />
        </div>
      </div>

      {/* Mobile nav */}
      <nav className="md:hidden flex items-center gap-1 overflow-x-auto px-4 pb-2 -mx-px scrollbar-thin">
        {NAV_ITEMS.map(({ href, key, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all",
              isActive(href)
                ? "bg-[rgba(255,92,138,0.12)] text-[color:var(--color-primary)]"
                : "text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]"
            )}
          >
            <Icon className="size-3.5" strokeWidth={2.5} />
            {t(key)}
          </Link>
        ))}
      </nav>
    </header>
  );
}
