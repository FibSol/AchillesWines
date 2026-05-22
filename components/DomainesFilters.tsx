"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Search, X, Filter } from "lucide-react";

export interface CountryRegion {
  country: string;
  region: string | null;
}

export interface DomainesFiltersLabels {
  searchPlaceholder: string;
  allCountries: string;
  allRegions: string;
  tier: string;
  allTiers: string;
  clear: string;
  showing: string;
  matchingOf: string;
  noMatches: string;
}

interface Props {
  countryRegions: CountryRegion[];
  tiers: number[];
  labels: DomainesFiltersLabels;
  totalShown: number;
  totalMatching: number;
}

export function DomainesFilters({
  countryRegions,
  tiers,
  labels,
  totalShown,
  totalMatching,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  // Local controlled state for the text input (debounced into the URL).
  const [search, setSearch] = useState(sp.get("q") ?? "");
  const activeCountry = sp.get("country") ?? "";
  const activeRegion = sp.get("region") ?? "";
  const activeTier = sp.get("tier") ?? "";
  const hasAnyFilter = Boolean(sp.get("q") || activeCountry || activeRegion || activeTier);

  const countries = useMemo(() => {
    const seen = new Set<string>();
    for (const cr of countryRegions) seen.add(cr.country);
    return Array.from(seen).sort();
  }, [countryRegions]);

  const regions = useMemo(() => {
    const seen = new Set<string>();
    for (const cr of countryRegions) {
      if (!cr.region) continue;
      if (activeCountry && cr.country !== activeCountry) continue;
      seen.add(cr.region);
    }
    return Array.from(seen).sort();
  }, [countryRegions, activeCountry]);

  // Debounce the search text → URL.
  useEffect(() => {
    if ((sp.get("q") ?? "") === search) return;
    const timer = setTimeout(() => {
      pushParam("q", search);
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function pushParam(key: string, value: string) {
    const next = new URLSearchParams(sp.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    // When country changes, drop the region filter — it may not exist in the new country.
    if (key === "country") next.delete("region");
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  function clearAll() {
    setSearch("");
    router.push(pathname);
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-12 gap-3">
        <div className="md:col-span-5 relative">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[color:var(--color-fg-subtle)] pointer-events-none"
            strokeWidth={2.5}
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={labels.searchPlaceholder}
            className="w-full pl-9 pr-9 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-coral-400)]"
              aria-label="clear"
            >
              <X className="size-3.5" strokeWidth={2.5} />
            </button>
          )}
        </div>

        <select
          value={activeCountry}
          onChange={(e) => pushParam("country", e.target.value)}
          className="md:col-span-3 px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
        >
          <option value="">{labels.allCountries}</option>
          {countries.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>

        <select
          value={activeRegion}
          onChange={(e) => pushParam("region", e.target.value)}
          className="md:col-span-3 px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)] disabled:opacity-40"
          disabled={regions.length === 0}
        >
          <option value="">{labels.allRegions}</option>
          {regions.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>

        <button
          type="button"
          onClick={clearAll}
          disabled={!hasAnyFilter}
          className="md:col-span-1 btn btn-ghost text-xs disabled:opacity-30 disabled:cursor-not-allowed"
          title={labels.clear}
        >
          <X className="size-3.5" strokeWidth={2.5} />
          <span className="hidden md:inline">{labels.clear}</span>
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mr-2">
          <Filter className="inline size-3 mr-1" strokeWidth={2.5} />
          {labels.tier}
        </span>
        <button
          type="button"
          onClick={() => pushParam("tier", "")}
          className={`text-xs px-3 py-1 rounded-full border transition ${
            activeTier === ""
              ? "border-[color:var(--color-coral-400)] bg-[rgba(255,92,138,0.18)] text-[color:var(--color-coral-400)]"
              : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] hover:border-[color:var(--color-coral-400)]"
          }`}
        >
          {labels.allTiers}
        </button>
        {tiers.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => pushParam("tier", String(t))}
            className={`text-xs px-3 py-1 rounded-full border transition font-mono ${
              activeTier === String(t)
                ? "border-[color:var(--color-coral-400)] bg-[rgba(255,92,138,0.18)] text-[color:var(--color-coral-400)]"
                : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] hover:border-[color:var(--color-coral-400)]"
            }`}
          >
            T{t}
          </button>
        ))}
        <span className="ml-auto text-xs font-mono text-[color:var(--color-fg-subtle)]">
          {totalMatching === 0
            ? labels.noMatches
            : `${labels.showing} ${totalShown} ${labels.matchingOf} ${totalMatching}`}
        </span>
      </div>
    </div>
  );
}
