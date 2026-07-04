"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Moon, Sun } from "lucide-react";

const STORAGE_KEY = "achilles-theme";

/**
 * Dark ("Nuit") / light ("Jour") toggle. The pre-hydration script in the
 * layout sets <html data-theme> before paint; this button just flips it and
 * persists the choice.
 */
export function ThemeToggle() {
  const t = useTranslations("nav");
  // Avoid hydration mismatch: render neutral until mounted.
  const [theme, setTheme] = useState<"dark" | "light" | null>(null);

  useEffect(() => {
    const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    setTheme(current);
  }, []);

  function toggle() {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private browsing: theme just won't persist */
    }
    setTheme(next);
  }

  return (
    <button
      onClick={toggle}
      title={t("themeToggle")}
      aria-label={t("themeToggle")}
      className="inline-flex items-center justify-center rounded-lg p-2 text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg)] hover:bg-[color:var(--color-primary-tint)] transition-all"
    >
      {theme === "light" ? (
        <Moon className="size-4" strokeWidth={2} />
      ) : (
        <Sun className="size-4" strokeWidth={2} />
      )}
    </button>
  );
}
