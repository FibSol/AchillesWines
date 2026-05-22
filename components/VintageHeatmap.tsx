"use client";

import { useState, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell as RechartsCell,
} from "recharts";
import { ConfidenceBadge, deriveConfidence, type ConfidenceLabels } from "@/components/ConfidenceBadge";

export interface VintageCell {
  region: string;
  vintage: number;
  wineCount: number;
  avgScore: number | null;
}

export interface HeatmapLabels {
  noData: string;
  scoreLabel: string;
  clickToExplore: string;
  loadingWines: string;
  noWines: string;
  chartTitle: string;
  confidence: ConfidenceLabels;
}

interface WineEntry {
  wineKey: string;
  canonicalName: string;
  producerName: string;
  cuveeName: string;
  sourceCount?: number;
}

interface Props {
  cells: VintageCell[];
  regions: string[];
  years: number[];
  labels: HeatmapLabels;
}

function cellBackground(wineCount: number, avgScore: number | null, maxCount: number): string {
  if (avgScore !== null) {
    if (avgScore >= 95) return "rgba(111,255,233,0.85)";
    if (avgScore >= 90) return "rgba(255,92,138,0.92)";
    if (avgScore >= 85) return "rgba(255,137,166,0.75)";
    if (avgScore >= 80) return "rgba(255,179,200,0.60)";
    if (avgScore >= 70) return "rgba(255,92,138,0.35)";
    return "rgba(255,92,138,0.18)";
  }
  if (wineCount > 0) {
    const t = Math.min(1, wineCount / Math.max(1, maxCount));
    return `rgba(255,92,138,${(0.08 + t * 0.28).toFixed(2)})`;
  }
  return "rgba(255,255,255,0.03)";
}

export function VintageHeatmap({ cells, regions, years, labels }: Props) {
  const [selected, setSelected] = useState<{ region: string; vintage: number } | null>(null);
  const [wines, setWines] = useState<WineEntry[]>([]);
  const [loadingWines, setLoadingWines] = useState(false);

  // Build lookup map: `region|vintage` → cell
  const cellMap = new Map<string, VintageCell>();
  let globalMaxCount = 1;
  for (const c of cells) {
    cellMap.set(`${c.region}|${c.vintage}`, c);
    if (c.wineCount > globalMaxCount) globalMaxCount = c.wineCount;
  }

  // BarChart data for the selected region (all vintages)
  const regionBarData =
    selected !== null
      ? years
          .map((y) => ({
            vintage: y,
            count: cellMap.get(`${selected.region}|${y}`)?.wineCount ?? 0,
          }))
          .filter((d) => d.count > 0)
      : [];

  const selectedCell = selected !== null ? cellMap.get(`${selected.region}|${selected.vintage}`) : undefined;

  const handleCellClick = useCallback(async (region: string, vintage: number) => {
    const cell = cellMap.get(`${region}|${vintage}`);
    if (!cell || cell.wineCount === 0) return;
    setSelected({ region, vintage });
    setWines([]);
    setLoadingWines(true);
    try {
      const resp = await fetch(
        `/api/vintages/wines?region=${encodeURIComponent(region)}&vintage=${vintage}`
      );
      if (resp.ok) {
        const data = (await resp.json()) as { wines: WineEntry[] };
        setWines(data.wines);
      }
    } finally {
      setLoadingWines(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cells]);

  if (cells.length === 0) {
    return (
      <div className="glass-card p-12 flex items-center justify-center text-[rgba(250,247,245,0.5)] text-sm">
        {labels.noData}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Heatmap grid */}
      <div className="glass-card p-4 overflow-x-auto" style={{ background: "rgba(13,6,26,0.7)" }}>
        <div style={{ minWidth: `${148 + years.length * 28}px` }}>
          {/* Year header row */}
          <div className="flex" style={{ paddingLeft: "148px" }}>
            {years.map((y) => (
              <div
                key={y}
                style={{ width: "26px", flexShrink: 0, fontSize: "9px" }}
                className="text-center text-[rgba(250,247,245,0.38)] select-none"
              >
                {String(y).slice(2)}
              </div>
            ))}
          </div>

          {/* Region rows */}
          <div className="mt-1 space-y-[2px]">
            {regions.map((region) => (
              <div key={region} className="flex items-center">
                {/* Region label */}
                <div
                  className="text-[rgba(250,247,245,0.65)] text-[11px] font-medium truncate flex-shrink-0 pr-2"
                  style={{ width: "148px" }}
                  title={region}
                >
                  {region}
                </div>

                {/* Cells */}
                {years.map((y) => {
                  const cell = cellMap.get(`${region}|${y}`);
                  const wineCount = cell?.wineCount ?? 0;
                  const avgScore = cell?.avgScore ?? null;
                  const isSelected = selected?.region === region && selected?.vintage === y;
                  const bg = cellBackground(wineCount, avgScore, globalMaxCount);
                  const hasData = wineCount > 0 || avgScore !== null;

                  return (
                    <button
                      key={y}
                      onClick={() => handleCellClick(region, y)}
                      style={{
                        width: "24px",
                        height: "18px",
                        flexShrink: 0,
                        background: bg,
                        border: isSelected
                          ? "1.5px solid rgba(255,92,138,0.9)"
                          : hasData
                          ? "1px solid rgba(255,92,138,0.12)"
                          : "1px solid rgba(255,255,255,0.04)",
                        borderRadius: "3px",
                        marginRight: "2px",
                        cursor: hasData ? "pointer" : "default",
                        outline: "none",
                        transition: "border-color 0.1s",
                      }}
                      title={
                        hasData
                          ? `${region} ${y}: ${wineCount} wines${avgScore !== null ? `, score ${avgScore.toFixed(0)}/100` : ""}`
                          : `${region} ${y}: no data`
                      }
                      aria-label={`${region} ${y}${hasData ? ` — ${wineCount} wines` : ""}`}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Color legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-[rgba(250,247,245,0.45)] px-1">
        {[
          { bg: "rgba(111,255,233,0.85)", label: "95+ exceptional" },
          { bg: "rgba(255,92,138,0.92)", label: "90–94 excellent" },
          { bg: "rgba(255,179,200,0.60)", label: "80–89 good" },
          { bg: "rgba(255,92,138,0.35)", label: "70–79" },
          { bg: "rgba(255,92,138,0.22)", label: "density (no score)" },
          { bg: "rgba(255,255,255,0.03)", label: "no data", border: "1px solid rgba(255,255,255,0.1)" },
        ].map(({ bg, label, border }) => (
          <div key={label} className="flex items-center gap-1">
            <div
              className="size-3 rounded-[2px] flex-shrink-0"
              style={{ background: bg, border: border ?? "none" }}
            />
            <span>{label}</span>
          </div>
        ))}
      </div>

      {/* Detail panel */}
      {selected !== null ? (
        <div className="glass-card p-5 space-y-4">
          {/* Header */}
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-[color:var(--color-coral-400)] font-semibold text-lg font-display">
              {selected.region}
            </h3>
            <span className="font-mono text-[color:var(--color-fg-muted)] text-base">
              {selected.vintage}
            </span>
            {selectedCell?.avgScore !== undefined && selectedCell.avgScore !== null && (
              <span className="badge badge-verified text-xs">
                {labels.scoreLabel}: {selectedCell.avgScore.toFixed(0)}/100
              </span>
            )}
            {selectedCell && (
              <span className="text-xs text-[rgba(250,247,245,0.45)]">
                {selectedCell.wineCount} wines in registry
              </span>
            )}
          </div>

          {/* Recharts BarChart — vintage distribution for this region */}
          {regionBarData.length > 0 && (
            <div>
              <p className="text-xs text-[rgba(250,247,245,0.45)] mb-2">{labels.chartTitle}</p>
              <ResponsiveContainer width="100%" height={110}>
                <BarChart
                  data={regionBarData}
                  margin={{ top: 4, right: 8, bottom: 4, left: -28 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,92,138,0.08)" />
                  <XAxis
                    dataKey="vintage"
                    tick={{ fill: "rgba(250,247,245,0.4)", fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fill: "rgba(250,247,245,0.4)", fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                    width={28}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "rgba(26,11,46,0.95)",
                      border: "1px solid rgba(255,92,138,0.4)",
                      borderRadius: "6px",
                      fontSize: "12px",
                      color: "rgba(250,247,245,0.9)",
                    }}
                    cursor={{ fill: "rgba(255,92,138,0.06)" }}
                  />
                  <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                    {regionBarData.map((entry) => (
                      <RechartsCell
                        key={entry.vintage}
                        fill={
                          entry.vintage === selected.vintage
                            ? "#FF5C8A"
                            : "rgba(255,92,138,0.32)"
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Wine list */}
          <div>
            <p className="text-xs text-[rgba(250,247,245,0.45)] mb-2">
              {loadingWines
                ? labels.loadingWines
                : wines.length > 0
                ? `${wines.length} wines`
                : labels.noWines}
            </p>
            {wines.length > 0 && (
              <ul className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                {wines.map((w) => {
                  const sourceCount = w.sourceCount ?? 0;
                  return (
                    <li
                      key={w.wineKey}
                      className="text-sm text-[color:var(--color-fg-muted)] flex items-center gap-2 flex-wrap"
                    >
                      <span className="text-[color:var(--color-fg)]">{w.producerName}</span>
                      <span>·</span>
                      <span className="text-[color:var(--color-coral-400)]">{w.cuveeName}</span>
                      <ConfidenceBadge
                        confidence={deriveConfidence(sourceCount)}
                        sourceCount={sourceCount}
                        labels={labels.confidence}
                        size="sm"
                        iconOnly
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <p className="text-xs text-[rgba(250,247,245,0.38)] text-center py-1">
          {labels.clickToExplore}
        </p>
      )}
    </div>
  );
}
