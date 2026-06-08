"use client";

import { useState } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { ChevronRight, Globe2 } from "lucide-react";

export interface SidebarRegion {
  name: string;
  count: number;
}

export interface SidebarCountry {
  code: string;
  count: number;
  regions: SidebarRegion[];
}

interface Props {
  countries: SidebarCountry[];
  allLabel: string;
  allCount: number;
}

export function DomaineSidebar({ countries, allLabel, allCount }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const activeCountry = sp.get("country") ?? "";
  const activeRegion = sp.get("region") ?? "";

  // Countries that are open (expanded). Default: open the active one.
  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    activeCountry ? { [activeCountry]: true } : {},
  );

  function navigate(country: string, region?: string) {
    const next = new URLSearchParams(sp.toString());
    // Strip page / region on every nav
    next.delete("page");
    next.delete("region");
    if (country) next.set("country", country);
    else next.delete("country");
    if (region) next.set("region", region);
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  function toggleOpen(code: string) {
    setOpen((prev) => ({ ...prev, [code]: !prev[code] }));
  }

  const isAllActive = !activeCountry;

  return (
    <nav className="w-56 shrink-0 space-y-0.5">
      {/* All */}
      <button
        type="button"
        onClick={() => navigate("")}
        className={`w-full flex items-center justify-between gap-2 px-3 py-2 rounded-md text-sm transition ${
          isAllActive
            ? "bg-[rgba(165,56,96,0.22)] text-[color:var(--color-magenta-400)] font-semibold"
            : "text-[color:var(--color-fg-muted)] hover:bg-[rgba(255,255,255,0.06)] hover:text-[color:var(--color-fg)]"
        }`}
      >
        <span className="flex items-center gap-2">
          <Globe2 className="size-3.5 shrink-0" strokeWidth={2} />
          {allLabel}
        </span>
        <span className="text-[10px] font-mono text-[color:var(--color-fg-subtle)]">{allCount}</span>
      </button>

      {/* Countries */}
      {countries.map((c) => {
        const isCountryActive = activeCountry === c.code && !activeRegion;
        const isExpanded = !!open[c.code];

        return (
          <div key={c.code}>
            <div
              className={`w-full flex items-center gap-1 px-3 py-2 rounded-md text-sm transition ${
                isCountryActive
                  ? "bg-[rgba(165,56,96,0.22)] text-[color:var(--color-magenta-400)] font-semibold"
                  : "text-[color:var(--color-fg-muted)] hover:bg-[rgba(255,255,255,0.06)] hover:text-[color:var(--color-fg)]"
              }`}
            >
              {/* Chevron toggle */}
              <button
                type="button"
                onClick={() => toggleOpen(c.code)}
                className="shrink-0 p-0.5 -ml-1 rounded hover:text-[color:var(--color-magenta-400)]"
                aria-label={isExpanded ? "Collapse" : "Expand"}
              >
                <ChevronRight
                  className={`size-3.5 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  strokeWidth={2.5}
                />
              </button>

              {/* Country link */}
              <button
                type="button"
                onClick={() => navigate(c.code)}
                className="flex-1 flex items-center justify-between gap-2 text-left"
              >
                <span className="font-medium">{c.code}</span>
                <span className="text-[10px] font-mono text-[color:var(--color-fg-subtle)]">{c.count}</span>
              </button>
            </div>

            {/* Regions (shown when expanded) */}
            {isExpanded && c.regions.length > 0 && (
              <div className="ml-5 mt-0.5 space-y-0.5 border-l border-[color:var(--color-border)] pl-2">
                {c.regions.map((r) => {
                  const isRegionActive = activeCountry === c.code && activeRegion === r.name;
                  return (
                    <button
                      key={r.name}
                      type="button"
                      onClick={() => navigate(c.code, r.name)}
                      className={`w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-md text-xs transition ${
                        isRegionActive
                          ? "bg-[rgba(165,56,96,0.22)] text-[color:var(--color-magenta-400)] font-semibold"
                          : "text-[color:var(--color-fg-subtle)] hover:bg-[rgba(255,255,255,0.06)] hover:text-[color:var(--color-fg)]"
                      }`}
                    >
                      <span className="truncate text-left">{r.name}</span>
                      <span className="text-[10px] font-mono shrink-0 text-[color:var(--color-fg-subtle)]">{r.count}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}
