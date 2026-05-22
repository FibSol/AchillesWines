import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(amount: number | null | undefined, currency = "EUR", locale = "fr-FR") {
  if (amount === null || amount === undefined) return "—";
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: amount >= 100 ? 0 : 2,
  }).format(amount);
}

export function formatNumber(n: number | null | undefined, locale = "fr-FR") {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat(locale).format(n);
}

export function formatDate(d: Date | number | null | undefined, locale = "fr-FR") {
  if (d === null || d === undefined) return "—";
  const date = typeof d === "number" ? new Date(d * 1000) : d;
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}
