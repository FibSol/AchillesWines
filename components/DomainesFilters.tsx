"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Search, X, Filter } from "lucide-react";

export interface DomainesFiltersLabels {
  searchPlaceholder: string;
  tier: string;
  allTiers: string;
  clear: string;
  showing: string;
  matchingOf: string;
  noMatches: string;
}

interface Props {
  tiers: number[];
  labels: DomainesFiltersLabels;
  totalShown: number;
  totalMatching: number;
}

export function DomainesFilters({ tiers, labels, totalShown, totalMatching }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const [search, setSearch] = useState(sp.get("q") ?? "");
  const activeTier = sp.get("tier") ?? "";
  const hasAnyFilter = Boolean(sp.get("q") || activeTier);

  // Debounce search text → URL.
  useEffect(() => {
    if ((sp.get("q") ?? "") === search) return;
    const timer = setTimeout(() => pushParam("q", search), 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function pushParam(key: string, value: string) {
    const next = new URLSearchParams(sp.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  function clearAll() {
    setSearch("");
    // Keep country/region from URL, only clear search + tier
    const next = new URLSearchParams(sp.toString());
    next.delete("q");
    next.delete("tier");
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[color:var(--color-fg-subtle)] pointer-events-none"
            strokeWidth={2.5}
          />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={labels.searchPlaceholder}
            className="w-full pl-9 pr-9 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-magenta-400)]"
              aria-label="clear"
            >
              <X className="size-3.5" strokeWidth={2.5} />
            </button>
          )}
        </div>

        {hasAnyFilter && (
          <button
            type="button"
            onClick={clearAll}
            className="btn btn-ghost text-xs px-3"
            title={labels.clear}
          >
            <X className="size-3.5" strokeWidth={2.5} />
            <span className="hidden sm:inline">{labels.clear}</span>
          </button>
        )}
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
              ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-soft)] text-[color:var(--color-magenta-400)]"
              : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] hover:border-[color:var(--color-magenta-400)]"
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
                ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-soft)] text-[color:var(--color-magenta-400)]"
                : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] hover:border-[color:var(--color-magenta-400)]"
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
