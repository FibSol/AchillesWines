"use client";

import { useState, useMemo } from "react";
import { ConfidenceBadge, deriveConfidence } from "@/components/ConfidenceBadge";

export interface DetailRow {
  wineKey: string;
  canonicalName: string;
  cuveeName: string;
  vintage: number | null;
  isNonVintage: boolean;
  appellationName: string;
  color: string;
  classification: string | null;
  alcoholPct: number | null;
  bottleMl: number;
  bestRating: number | null;
  criticBreakdown: { criticCode: string; score: number }[];
  priceMin: number | null;
  priceMax: number | null;
  inCellar: number;
  sourceCount: number;
}

interface DomaineDetailTableProps {
  rows: DetailRow[];
  cuveeNames: string[];
  labels: {
    canonicalName: string;
    cuvee: string;
    vintage: string;
    appellation: string;
    color: string;
    classification: string;
    alcohol: string;
    bottleSize: string;
    bestRating: string;
    priceRange: string;
    inCellar: string;
    sources: string;
    allCuvees: string;
    allColors: string;
    filterVintageFrom: string;
    filterVintageTo: string;
    noWinesFilter: string;
    grandVin: string;
  };
  colorLabels: Record<string, string>;
  confidenceLabels: {
    verified: string;
    reviewed: string;
    needs_review: string;
  };
}

const COLOR_DOT: Record<string, string> = {
  red: "#b71f55",
  white: "#FFD166",
  "rosé": "#FF89A6",
  sparkling: "#8EFEED",
  sweet: "#FFB3C8",
  fortified: "#553987",
  orange: "#FF5C8A",
};

function CuveeName({ name, grandVinLabel }: { name: string; grandVinLabel: string }) {
  if (name) return <>{name}</>;
  return <em style={{ color: "rgba(250,247,245,0.4)", fontStyle: "italic" }}>{grandVinLabel}</em>;
}

export function DomaineDetailTable({
  rows,
  cuveeNames,
  labels,
  colorLabels,
  confidenceLabels,
}: DomaineDetailTableProps) {
  const [cuveeFilter, setCuveeFilter] = useState("__all__");
  const [colorFilter, setColorFilter] = useState("__all__");
  const [vintageFrom, setVintageFrom] = useState("");
  const [vintageTo, setVintageTo] = useState("");

  const uniqueColors = useMemo(() => Array.from(new Set(rows.map((r) => r.color))).sort(), [rows]);

  const filtered = useMemo(() => {
    return rows.filter((row) => {
      if (cuveeFilter !== "__all__" && row.cuveeName !== cuveeFilter) return false;
      if (colorFilter !== "__all__" && row.color !== colorFilter) return false;
      if (vintageFrom && row.vintage !== null && row.vintage < Number(vintageFrom)) return false;
      if (vintageTo && row.vintage !== null && row.vintage > Number(vintageTo)) return false;
      return true;
    });
  }, [rows, cuveeFilter, colorFilter, vintageFrom, vintageTo]);

  const selectCls =
    "text-xs rounded-lg px-3 py-1.5 focus:outline-none cursor-pointer transition-colors " +
    "bg-transparent border text-[color:var(--color-fg)] focus:border-[color:var(--color-accent)]";
  const borderStyle = { borderColor: "rgba(255,255,255,0.15)" } as React.CSSProperties;
  const inputCls =
    "w-16 text-center text-xs rounded-lg px-2 py-1.5 focus:outline-none bg-transparent border text-[color:var(--color-fg)] focus:border-[color:var(--color-accent)]";

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div
        className="glass-card p-4 flex flex-wrap gap-3 items-center"
        style={{ background: "rgba(13,6,26,0.5)" }}
      >
        <select
          value={cuveeFilter}
          onChange={(e) => setCuveeFilter(e.target.value)}
          className={selectCls}
          style={borderStyle}
        >
          <option value="__all__">{labels.allCuvees}</option>
          {cuveeNames.map((n) => (
            <option key={n} value={n}>
              {n || labels.grandVin}
            </option>
          ))}
        </select>

        <select
          value={colorFilter}
          onChange={(e) => setColorFilter(e.target.value)}
          className={selectCls}
          style={borderStyle}
        >
          <option value="__all__">{labels.allColors}</option>
          {uniqueColors.map((c) => (
            <option key={c} value={c}>
              {colorLabels[c] ?? c}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-2 text-xs" style={{ color: "rgba(250,247,245,0.5)" }}>
          <span>{labels.filterVintageFrom}</span>
          <input
            type="number"
            value={vintageFrom}
            onChange={(e) => setVintageFrom(e.target.value)}
            placeholder="2000"
            className={inputCls}
            style={borderStyle}
          />
          <span>{labels.filterVintageTo}</span>
          <input
            type="number"
            value={vintageTo}
            onChange={(e) => setVintageTo(e.target.value)}
            placeholder="2024"
            className={inputCls}
            style={borderStyle}
          />
        </div>

        <span className="ml-auto text-[10px]" style={{ color: "rgba(250,247,245,0.35)" }}>
          {filtered.length} / {rows.length}
        </span>
      </div>

      {/* Table */}
      {filtered.length === 0 ? (
        <div
          className="glass-card p-10 text-center text-sm"
          style={{ color: "rgba(250,247,245,0.4)" }}
        >
          {labels.noWinesFilter}
        </div>
      ) : (
        <div className="glass-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" style={{ minWidth: 1020 }}>
              <thead style={{ borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
                <tr className="text-left" style={{ color: "rgba(250,247,245,0.4)", fontSize: 10 }}>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.canonicalName}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.cuvee}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.vintage}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.appellation}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.color}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.classification}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.alcohol}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em]">{labels.bottleSize}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em] text-right">{labels.bestRating}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em] text-right">{labels.priceRange}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em] text-right">{labels.inCellar}</th>
                  <th className="px-4 py-3 font-semibold uppercase tracking-[0.06em] text-right">{labels.sources}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => (
                  <tr
                    key={row.wineKey}
                    className="transition-colors hover:bg-[rgba(165,56,96,0.05)]"
                    style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}
                  >
                    {/* Canonical name */}
                    <td className="px-4 py-3 font-semibold max-w-[200px]" style={{ color: "var(--color-fg)" }}>
                      <p className="truncate text-xs" title={row.canonicalName}>
                        {row.canonicalName}
                      </p>
                    </td>
                    {/* Cuvée */}
                    <td className="px-4 py-3 max-w-[150px]" style={{ color: "rgba(250,247,245,0.65)" }}>
                      <p className="truncate text-xs">
                        <CuveeName name={row.cuveeName} grandVinLabel={labels.grandVin} />
                      </p>
                    </td>
                    {/* Vintage */}
                    <td className="px-4 py-3 font-mono text-xs" style={{ color: "rgba(250,247,245,0.6)" }}>
                      {row.isNonVintage ? "NV" : (row.vintage ?? "—")}
                    </td>
                    {/* Appellation */}
                    <td className="px-4 py-3 max-w-[140px]" style={{ color: "rgba(250,247,245,0.6)" }}>
                      <p className="truncate text-xs">{row.appellationName}</p>
                    </td>
                    {/* Color */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="inline-block size-2 rounded-full shrink-0"
                          style={{ background: COLOR_DOT[row.color] ?? "#FAF7F5" }}
                        />
                        <span className="text-[10px]" style={{ color: "rgba(250,247,245,0.55)" }}>
                          {colorLabels[row.color] ?? row.color}
                        </span>
                      </div>
                    </td>
                    {/* Classification */}
                    <td className="px-4 py-3 text-[10px]" style={{ color: "rgba(250,247,245,0.55)" }}>
                      {row.classification ?? <span style={{ color: "rgba(250,247,245,0.2)" }}>—</span>}
                    </td>
                    {/* Alcohol */}
                    <td className="px-4 py-3 font-mono text-[10px]" style={{ color: "rgba(250,247,245,0.55)" }}>
                      {row.alcoholPct !== null ? `${row.alcoholPct}%` : <span style={{ color: "rgba(250,247,245,0.2)" }}>—</span>}
                    </td>
                    {/* Bottle size */}
                    <td className="px-4 py-3 font-mono text-[10px]" style={{ color: "rgba(250,247,245,0.55)" }}>
                      {row.bottleMl === 750 ? "75cl" : `${row.bottleMl}ml`}
                    </td>
                    {/* Best rating + critic breakdown */}
                    <td className="px-4 py-3 text-right">
                      {row.bestRating !== null ? (
                        <div className="inline-flex flex-col items-end gap-1">
                          <span
                            className="font-mono font-semibold text-xs"
                            style={{ color: "var(--color-accent)" }}
                          >
                            {row.bestRating.toFixed(1)}/100
                          </span>
                          {row.criticBreakdown.length > 0 && (
                            <div className="flex gap-1 flex-wrap justify-end">
                              {row.criticBreakdown.map((c) => (
                                <span
                                  key={c.criticCode}
                                  title={`${c.criticCode}: ${c.score.toFixed(1)}/100`}
                                  className="text-[9px] font-mono px-1 py-px rounded"
                                  style={{
                                    background: "rgba(165,56,96,0.22)",
                                    color: "rgba(250,247,245,0.65)",
                                  }}
                                >
                                  {c.criticCode}&nbsp;{c.score.toFixed(0)}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span style={{ color: "rgba(250,247,245,0.2)" }}>—</span>
                      )}
                    </td>
                    {/* Price range */}
                    <td className="px-4 py-3 text-right font-mono text-xs" style={{ color: "var(--color-fg)" }}>
                      {row.priceMin !== null && row.priceMax !== null ? (
                        row.priceMin === row.priceMax ? (
                          `€${row.priceMin.toFixed(0)}`
                        ) : (
                          `€${row.priceMin.toFixed(0)}–${row.priceMax.toFixed(0)}`
                        )
                      ) : (
                        <span style={{ color: "rgba(250,247,245,0.2)" }}>—</span>
                      )}
                    </td>
                    {/* In cellar */}
                    <td className="px-4 py-3 text-right font-mono text-xs">
                      {row.inCellar > 0 ? (
                        <span style={{ color: "#6fffe9", fontWeight: 600 }}>{row.inCellar}</span>
                      ) : (
                        <span style={{ color: "rgba(250,247,245,0.2)" }}>—</span>
                      )}
                    </td>
                    {/* Sources / confidence */}
                    <td className="px-4 py-3 text-right">
                      <ConfidenceBadge
                        confidence={deriveConfidence(row.sourceCount)}
                        sourceCount={row.sourceCount}
                        labels={confidenceLabels}
                        size="sm"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
