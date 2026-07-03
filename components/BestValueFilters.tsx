"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useCallback, useEffect, useState, useTransition } from "react";
import { X } from "lucide-react";

export interface BestValueFilterLabels {
  country: string;
  region: string;
  vintage: string;
  color: string;
  colorRed: string;
  colorWhite: string;
  colorRose: string;
  colorSparkling: string;
  minPrice: string;
  maxPrice: string;
  minRating: string;
  maxRating: string;
  allCountries: string;
  allRegions: string;
  allVintages: string;
  clearFilters: string;
  intent: string;
  intentDrinkNow: string;
  intentCellar10: string;
  intentInvest: string;
}

const COLOR_OPTIONS = [
  { value: "red",      dot: "#A53860", label: (l: BestValueFilterLabels) => l.colorRed },
  { value: "white",    dot: "#E5B25D", label: (l: BestValueFilterLabels) => l.colorWhite },
  { value: "rosé",     dot: "#F4A7B9", label: (l: BestValueFilterLabels) => l.colorRose },
  { value: "sparkling",dot: "#B8D4E8", label: (l: BestValueFilterLabels) => l.colorSparkling },
] as const;

const INTENT_OPTIONS = [
  { value: "drink_now", icon: "🍷", label: (l: BestValueFilterLabels) => l.intentDrinkNow },
  { value: "cellar_10", icon: "⏳", label: (l: BestValueFilterLabels) => l.intentCellar10 },
  { value: "invest",    icon: "📈", label: (l: BestValueFilterLabels) => l.intentInvest },
] as const;

interface Props {
  countries: { code: string; name: string }[];
  regions: string[];
  vintages: number[];
  labels: BestValueFilterLabels;
}

const selectCls =
  "h-8 px-2 text-sm bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] rounded-md text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)] cursor-pointer";

const inputCls =
  "h-8 px-2 text-sm bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] rounded-md text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)] w-20 font-mono";

const labelCls =
  "block text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1";

export function BestValueFilters({ countries, regions, vintages, labels }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isPending, startTransition] = useTransition();

  const [minPrice, setMinPrice] = useState(searchParams.get("minPrice") ?? "");
  const [maxPrice, setMaxPrice] = useState(searchParams.get("maxPrice") ?? "");
  const [minRating, setMinRating] = useState(searchParams.get("minRating") ?? "");
  const [maxRating, setMaxRating] = useState(searchParams.get("maxRating") ?? "");

  useEffect(() => {
    setMinPrice(searchParams.get("minPrice") ?? "");
    setMaxPrice(searchParams.get("maxPrice") ?? "");
    setMinRating(searchParams.get("minRating") ?? "");
    setMaxRating(searchParams.get("maxRating") ?? "");
  }, [searchParams]);

  const updateParam = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set(key, value);
      else params.delete(key);
      startTransition(() => {
        router.push(`${pathname}?${params.toString()}`, { scroll: false });
      });
    },
    [router, pathname, searchParams]
  );

  const commitInput = (key: string, value: string) => updateParam(key, value);

  const hasFilters = ["country", "region", "vintage", "color", "minPrice", "maxPrice", "minRating", "maxRating", "drinkingIntent"]
    .some((k) => searchParams.has(k));

  return (
    <div
      className={`glass-card px-4 py-3 transition-opacity duration-150 ${
        isPending ? "opacity-50 pointer-events-none" : ""
      }`}
    >
      <div className="flex flex-wrap gap-x-3 gap-y-3 items-end">

        {/* ── Country ── */}
        <div>
          <label className={labelCls}>{labels.country}</label>
          <select
            className={`${selectCls} min-w-[120px]`}
            value={searchParams.get("country") ?? ""}
            onChange={(e) => {
              const params = new URLSearchParams(searchParams.toString());
              if (e.target.value) params.set("country", e.target.value);
              else params.delete("country");
              params.delete("region"); // cascade: reset region when country changes
              startTransition(() => router.push(`${pathname}?${params.toString()}`, { scroll: false }));
            }}
          >
            <option value="">{labels.allCountries}</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>{c.name}</option>
            ))}
          </select>
        </div>

        {/* ── Region ── */}
        <div>
          <label className={labelCls}>{labels.region}</label>
          <select
            className={`${selectCls} min-w-[160px] max-w-[220px]`}
            value={searchParams.get("region") ?? ""}
            onChange={(e) => updateParam("region", e.target.value)}
          >
            <option value="">{labels.allRegions}</option>
            {regions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>

        {/* ── Vintage ── */}
        <div>
          <label className={labelCls}>{labels.vintage}</label>
          <select
            className={`${selectCls} w-24`}
            value={searchParams.get("vintage") ?? ""}
            onChange={(e) => updateParam("vintage", e.target.value)}
          >
            <option value="">{labels.allVintages}</option>
            {vintages.map((v) => (
              <option key={v} value={String(v)}>{v}</option>
            ))}
          </select>
        </div>

        {/* ── Color ── */}
        <div>
          <label className={labelCls}>{labels.color}</label>
          <div className="flex gap-1">
            {COLOR_OPTIONS.map((c) => {
              const active = searchParams.get("color") === c.value;
              return (
                <button
                  key={c.value}
                  type="button"
                  title={c.label(labels)}
                  onClick={() => updateParam("color", active ? "" : c.value)}
                  className={`h-8 px-2 flex items-center gap-1.5 rounded-md border text-xs transition-colors ${
                    active
                      ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-soft)] text-[color:var(--color-fg)]"
                      : "border-[color:var(--color-border)] bg-[color:var(--color-input-bg)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)]"
                  }`}
                >
                  <span className="size-2 rounded-full shrink-0" style={{ background: c.dot }} />
                  <span className="hidden sm:inline">{c.label(labels)}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* divider */}
        <div className="self-stretch w-px bg-[color:var(--color-border)] mx-1" />

        {/* ── Drinking intent ── */}
        <div>
          <label className={labelCls}>{labels.intent}</label>
          <div className="flex gap-1">
            {INTENT_OPTIONS.map((opt) => {
              const active = searchParams.get("drinkingIntent") === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  title={opt.label(labels)}
                  onClick={() => updateParam("drinkingIntent", active ? "" : opt.value)}
                  className={`h-8 px-2 flex items-center gap-1.5 rounded-md border text-xs transition-colors ${
                    active
                      ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-soft)] text-[color:var(--color-fg)]"
                      : "border-[color:var(--color-border)] bg-[color:var(--color-input-bg)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)]"
                  }`}
                >
                  <span className="text-sm leading-none">{opt.icon}</span>
                  <span className="hidden sm:inline">{opt.label(labels)}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* divider */}
        <div className="self-stretch w-px bg-[color:var(--color-border)] mx-1" />

        {/* ── Price range ── */}
        <div>
          <label className={labelCls}>{labels.minPrice}</label>
          <input
            type="number" min={0} placeholder="0"
            className={inputCls}
            value={minPrice}
            onChange={(e) => setMinPrice(e.target.value)}
            onBlur={(e) => commitInput("minPrice", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitInput("minPrice", (e.target as HTMLInputElement).value)}
          />
        </div>
        <div className="self-end pb-1.5 text-[color:var(--color-fg-subtle)] text-xs select-none">–</div>
        <div>
          <label className={labelCls}>{labels.maxPrice}</label>
          <input
            type="number" min={0} placeholder="∞"
            className={inputCls}
            value={maxPrice}
            onChange={(e) => setMaxPrice(e.target.value)}
            onBlur={(e) => commitInput("maxPrice", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitInput("maxPrice", (e.target as HTMLInputElement).value)}
          />
        </div>

        {/* divider */}
        <div className="self-stretch w-px bg-[color:var(--color-border)] mx-1" />

        {/* ── Rating range ── */}
        <div>
          <label className={labelCls}>{labels.minRating}</label>
          <input
            type="number" min={0} max={100} placeholder="0"
            className={inputCls}
            value={minRating}
            onChange={(e) => setMinRating(e.target.value)}
            onBlur={(e) => commitInput("minRating", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitInput("minRating", (e.target as HTMLInputElement).value)}
          />
        </div>
        <div className="self-end pb-1.5 text-[color:var(--color-fg-subtle)] text-xs select-none">–</div>
        <div>
          <label className={labelCls}>{labels.maxRating}</label>
          <input
            type="number" min={0} max={100} placeholder="100"
            className={inputCls}
            value={maxRating}
            onChange={(e) => setMaxRating(e.target.value)}
            onBlur={(e) => commitInput("maxRating", e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commitInput("maxRating", (e.target as HTMLInputElement).value)}
          />
        </div>

        {/* ── Clear ── */}
        {hasFilters && (
          <div className="self-end">
            <button
              type="button"
              className="btn btn-ghost text-xs px-3 h-8"
              onClick={() => startTransition(() => router.push(pathname, { scroll: false }))}
            >
              <X className="size-3.5" strokeWidth={2.5} />
              {labels.clearFilters}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
