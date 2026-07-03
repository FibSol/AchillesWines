"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useRouter, useParams } from "next/navigation";
import { ChevronRight } from "lucide-react";

export interface VintageCell {
  region: string;
  countryCode: string;
  vintage: number;
  wineCount: number;
  avgScore: number | null;
}

export interface TierLabels {
  t1: string;
  t2: string;
  t3: string;
  t4: string;
  t5: string;
}

export interface HeatmapLabels {
  noData: string;
  scoreLabel: string;
  clickToExplore: string;
  tiers: TierLabels;
  densityLabel: string;
}

interface Props {
  cells: VintageCell[];
  regions: string[];
  years: number[];
  labels: HeatmapLabels;
}

function scoreToTier(score: number): 1 | 2 | 3 | 4 | 5 {
  if (score >= 95) return 5;
  if (score >= 90) return 4;
  if (score >= 82) return 3;
  if (score >= 70) return 2;
  return 1;
}

type TierStyle = { bg: string; text: string; border: string };

function tierStyle(tier: 1 | 2 | 3 | 4 | 5): TierStyle {
  switch (tier) {
    case 5: return { bg: "rgba(229,178,93,0.97)",  text: "#0F0E17", border: "rgba(229,178,93,0.6)"  };
    case 4: return { bg: "rgba(165,56,96,0.95)",  text: "#0F0E17", border: "rgba(165,56,96,0.6)"  };
    case 3: return { bg: "rgba(155,100,210,0.82)", text: "#FAF7F5", border: "rgba(155,100,210,0.5)" };
    case 2: return { bg: "rgba(165,56,96,0.60)",   text: "rgba(250,247,245,0.85)", border: "rgba(165,56,96,0.4)"  };
    case 1: return { bg: "rgba(50,20,38,0.85)",    text: "rgba(250,247,245,0.38)", border: "rgba(165,56,96,0.15)" };
  }
}

function tierLabel(tier: 1 | 2 | 3 | 4 | 5, labels: TierLabels): string {
  return [labels.t1, labels.t2, labels.t3, labels.t4, labels.t5][tier - 1];
}

const CELL_W = 72;
const CELL_H = 26;
const LABEL_W = 148;

export function VintageHeatmap({ cells, regions, years, labels }: Props) {
  const [selected, setSelected] = useState<{ region: string; vintage: number } | null>(null);
  const [countryFilter, setCountryFilter] = useState("FR");
  const router = useRouter();
  const params = useParams();
  const locale = (params.locale as string) || "fr";
  const [collapsedCountries, setCollapsedCountries] = useState<Set<string>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  // Build lookup structures
  const { cellMap, regionCountry, globalMaxCount } = useMemo(() => {
    const cellMap = new Map<string, VintageCell>();
    const regionCountry = new Map<string, string>();
    let globalMaxCount = 1;
    for (const c of cells) {
      cellMap.set(`${c.region}|${c.vintage}`, c);
      regionCountry.set(c.region, c.countryCode);
      if (c.wineCount > globalMaxCount) globalMaxCount = c.wineCount;
    }
    return { cellMap, regionCountry, globalMaxCount };
  }, [cells]);

  // Available countries
  const availableCountries = useMemo(() => {
    const s = new Set<string>();
    for (const c of cells) s.add(c.countryCode);
    return Array.from(s).sort();
  }, [cells]);

  // Regions filtered by country and with at least one vintage rating score
  const visibleRegions = useMemo(() => {
    return regions.filter(r => {
      if (countryFilter !== "ALL" && regionCountry.get(r) !== countryFilter) return false;
      return years.some(y => {
        const cell = cellMap.get(`${r}|${y}`);
        return cell && cell.avgScore !== null;
      });
    });
  }, [regions, countryFilter, regionCountry, years, cellMap]);

  // Years that have at least one data point among visible regions
  const visibleYears = useMemo(() => {
    return years.filter(y =>
      visibleRegions.some(r => {
        const cell = cellMap.get(`${r}|${y}`);
        return cell && (cell.wineCount > 0 || cell.avgScore !== null);
      })
    );
  }, [years, visibleRegions, cellMap]);

  // Group visible regions by country (preserving order)
  const regionsByCountry = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const r of visibleRegions) {
      const cc = regionCountry.get(r) ?? "??";
      if (!map.has(cc)) map.set(cc, []);
      map.get(cc)!.push(r);
    }
    return map;
  }, [visibleRegions, regionCountry]);

  const toggleCountry = useCallback((cc: string) => {
    setCollapsedCountries(prev => {
      const next = new Set(prev);
      if (next.has(cc)) next.delete(cc);
      else next.add(cc);
      return next;
    });
  }, []);

  // Scroll to the rightmost (most recent) years on mount and when visible years change
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [visibleYears]);

  const handleCellClick = useCallback((region: string, vintage: number) => {
    const cell = cellMap.get(`${region}|${vintage}`);
    if (!cell || (cell.wineCount === 0 && cell.avgScore === null)) return;
    setSelected({ region, vintage });
    router.push(`/${locale}/vintages/${encodeURIComponent(region)}/${vintage}`);
  }, [cellMap, locale, router]);

  if (cells.length === 0) {
    return (
      <div className="glass-card p-12 flex items-center justify-center text-[color:var(--color-fg-muted)] text-sm">
        {labels.noData}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Country filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => setCountryFilter("ALL")}
          className={`text-xs px-3 py-1 rounded-full border transition ${
            countryFilter === "ALL"
              ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-soft)] text-[color:var(--color-magenta-400)]"
              : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)]"
          }`}
        >
          All
        </button>
        {availableCountries.map(cc => (
          <button
            key={cc}
            type="button"
            onClick={() => setCountryFilter(cc)}
            className={`text-xs px-3 py-1 rounded-full border transition font-mono ${
              countryFilter === cc
                ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-soft)] text-[color:var(--color-magenta-400)]"
                : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)]"
            }`}
          >
            {cc}
          </button>
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] text-[color:var(--color-fg-muted)] px-1">
        {([5, 4, 3, 2, 1] as const).map(t => {
          const s = tierStyle(t);
          return (
            <div key={t} className="flex items-center gap-1.5">
              <div className="rounded-[3px] flex-shrink-0" style={{ width: 14, height: 14, background: s.bg, border: `1px solid ${s.border}` }} />
              <span className="font-medium" style={{ color: "rgba(250,247,245,0.75)" }}>{t}</span>
              <span>— {tierLabel(t, labels.tiers)}</span>
            </div>
          );
        })}
        <div className="flex items-center gap-1.5">
          <div className="rounded-[3px] flex-shrink-0" style={{ width: 14, height: 14, background: "rgba(165,56,96,0.22)", border: "1px solid rgba(165,56,96,0.18)" }} />
          <span>{labels.densityLabel}</span>
        </div>
      </div>

      {/* Heatmap grid */}
      <div ref={scrollRef} className="glass-card p-4 overflow-x-auto" style={{ background: "rgba(9,8,15,0.7)" }}>
        <div style={{ minWidth: `${LABEL_W + visibleYears.length * (CELL_W + 2)}px` }}>
          {/* Year header */}
          <div className="flex">
            {/* Sticky corner spacer */}
            <div style={{ width: `${LABEL_W}px`, flexShrink: 0, position: "sticky", left: 0, zIndex: 2, background: "rgba(9,8,15,0.95)" }} />
            {visibleYears.map(y => (
              <div key={y} style={{ width: `${CELL_W}px`, flexShrink: 0, fontSize: "9px", marginRight: "2px" }} className="text-center text-[color:var(--color-fg-subtle)] select-none">
                {String(y).slice(2)}
              </div>
            ))}
          </div>

          {/* Country groups */}
          <div className="mt-1 space-y-px">
            {Array.from(regionsByCountry.entries()).map(([country, countryRegions]) => {
              const isCollapsed = collapsedCountries.has(country);
              return (
                <div key={country}>
                  {/* Country header row */}
                  <div
                    className="flex items-center cursor-pointer group"
                    onClick={() => toggleCountry(country)}
                  >
                    <div
                      className="flex items-center gap-1.5 flex-shrink-0 pr-2"
                      style={{ width: `${LABEL_W}px`, position: "sticky", left: 0, zIndex: 1, background: "rgba(9,8,15,0.95)" }}
                    >
                      <ChevronRight
                        className={`size-3 text-[color:var(--color-fg-subtle)] group-hover:text-[color:var(--color-magenta-400)] transition-transform ${isCollapsed ? "" : "rotate-90"}`}
                        strokeWidth={2.5}
                      />
                      <span className="text-[11px] font-mono font-semibold text-[color:var(--color-fg-muted)] group-hover:text-[color:var(--color-magenta-400)] transition-colors uppercase tracking-wider">
                        {country}
                      </span>
                      <span className="text-[9px] text-[color:var(--color-fg-faint)] ml-1">
                        {countryRegions.length}
                      </span>
                    </div>
                    {/* Thin spacer line across years */}
                    <div className="flex-1 h-px bg-[color:var(--color-fill-subtle)]" />
                  </div>

                  {/* Region rows */}
                  {!isCollapsed && (
                    <div className="space-y-[2px] mt-[2px]">
                      {countryRegions.map(region => (
                        <div key={region} className="flex items-center">
                          {/* Region label */}
                          <div
                            className="flex items-center flex-shrink-0 pr-2 overflow-hidden pl-5"
                            style={{ width: `${LABEL_W}px`, position: "sticky", left: 0, zIndex: 1, background: "rgba(9,8,15,0.95)" }}
                            title={region}
                          >
                            <span className="text-[color:var(--color-fg-muted)] text-[11px] font-medium truncate">
                              {region}
                            </span>
                          </div>

                          {/* Cells */}
                          {visibleYears.map(y => {
                            const cell = cellMap.get(`${region}|${y}`);
                            const wineCount = cell?.wineCount ?? 0;
                            const avgScore = cell?.avgScore ?? null;
                            const isSelected = selected?.region === region && selected?.vintage === y;
                            const hasData = wineCount > 0 || avgScore !== null;

                            let bg: string, textColor: string, borderColor: string, label = "";

                            if (avgScore !== null) {
                              const tier = scoreToTier(avgScore);
                              const s = tierStyle(tier);
                              bg = s.bg; textColor = s.text;
                              borderColor = isSelected ? "rgba(165,56,96,0.9)" : s.border;
                              label = tierLabel(tier, labels.tiers);
                            } else if (wineCount > 0) {
                              const t = Math.min(1, wineCount / Math.max(1, globalMaxCount));
                              bg = `rgba(165,56,96,${(0.08 + t * 0.28).toFixed(2)})`;
                              textColor = "rgba(250,247,245,0.5)";
                              borderColor = isSelected ? "rgba(165,56,96,0.9)" : "rgba(165,56,96,0.18)";
                            } else {
                              bg = "rgba(255,255,255,0.03)";
                              textColor = "transparent";
                              borderColor = isSelected ? "rgba(165,56,96,0.9)" : "rgba(255,255,255,0.04)";
                            }

                            return (
                              <button
                                key={y}
                                onClick={() => handleCellClick(region, y)}
                                title={hasData ? `${region} ${y}${avgScore !== null ? ` · ${tierLabel(scoreToTier(avgScore), labels.tiers)} (${avgScore.toFixed(0)}/100)` : ""} · ${wineCount} wines` : `${region} ${y}: no data`}
                                aria-label={`${region} ${y}${hasData ? ` — ${wineCount} wines` : ""}`}
                                style={{
                                  width: `${CELL_W}px`, height: `${CELL_H}px`, flexShrink: 0,
                                  background: bg, border: `${isSelected ? "1.5px" : "1px"} solid ${borderColor}`,
                                  borderRadius: "3px", marginRight: "2px",
                                  cursor: hasData ? "pointer" : "default",
                                  outline: "none", transition: "opacity 0.1s",
                                  display: "flex", alignItems: "center", justifyContent: "center",
                                  fontSize: "9px", fontWeight: 600, letterSpacing: "0.02em",
                                  color: textColor, overflow: "hidden", whiteSpace: "nowrap",
                                }}
                              >
                                {label}
                              </button>
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <p className="text-xs text-[color:var(--color-fg-subtle)] text-center py-1">{labels.clickToExplore}</p>
    </div>
  );
}
