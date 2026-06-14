"use client";

import { useState, useMemo, useCallback } from "react";
import { ResponsiveContainer } from "recharts";

/* ─── Types ────────────────────────────────────────────────────────────────── */

export interface DivergenceCell {
  year: number;
  critic: string;
  avg: number;
  count: number;
  divergence: number;
}

export interface DivergenceLabels {
  title: string;
  subtitle: string;
  legend: string;
  tooltipYear: string;
  tooltipCritic: string;
  tooltipAvg: string;
  tooltipCount: string;
  tooltipDivergence: string;
  noData: string;
}

interface Props {
  cells: DivergenceCell[];
  labels: DivergenceLabels;
}

/* ─── Colour scale ──────────────────────────────────────────────────────────
 * Three-stop gradient: dark aubergine → magenta vin → champagne gold
 *   0 → #2D1B2E   (low / empty)
 *  50 → #A53860   (mid)
 * 100 → #E5B25D   (excellent)
 */

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

const STOPS: Array<{ at: number; rgb: [number, number, number] }> = [
  { at: 0,   rgb: hexToRgb("#2D1B2E") },
  { at: 50,  rgb: hexToRgb("#A53860") },
  { at: 100, rgb: hexToRgb("#E5B25D") },
];

function scoreToColor(score: number): string {
  const clamped = Math.max(0, Math.min(100, score));
  // Find surrounding stops
  let lo = STOPS[0];
  let hi = STOPS[STOPS.length - 1];
  for (let i = 0; i < STOPS.length - 1; i++) {
    if (clamped >= STOPS[i].at && clamped <= STOPS[i + 1].at) {
      lo = STOPS[i];
      hi = STOPS[i + 1];
      break;
    }
  }
  const range = hi.at - lo.at;
  const t = range === 0 ? 0 : (clamped - lo.at) / range;
  const r = Math.round(lo.rgb[0] + t * (hi.rgb[0] - lo.rgb[0]));
  const g = Math.round(lo.rgb[1] + t * (hi.rgb[1] - lo.rgb[1]));
  const b = Math.round(lo.rgb[2] + t * (hi.rgb[2] - lo.rgb[2]));
  return `rgb(${r},${g},${b})`;
}

/* ─── Layout constants ──────────────────────────────────────────────────────── */

const CELL_W = 24;
const CELL_H = 22;
const LABEL_W = 72;  // critic label column
const HEADER_H = 32; // year header row
const LEGEND_BAR_W = 180;
const LEGEND_BAR_H = 10;

/* ─── Component ──────────────────────────────────────────────────────────── */

interface TooltipState {
  x: number;
  y: number;
  cell: DivergenceCell;
}

export function VintageDivergenceHeatmap({ cells, labels }: Props) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  /* Derive axes */
  const { years, critics, cellMap } = useMemo(() => {
    const yearsSet = new Set<number>();
    const criticsSet = new Set<string>();
    const cellMap = new Map<string, DivergenceCell>();

    for (const c of cells) {
      yearsSet.add(c.year);
      criticsSet.add(c.critic);
      cellMap.set(`${c.critic}|${c.year}`, c);
    }

    const years = Array.from(yearsSet).sort((a, b) => a - b);
    // Preferred order for known critics; rest appended alphabetically
    const CRITIC_ORDER = ["WA", "Vinous", "BH", "JMIB", "RVF", "Decanter", "JS", "JG", "WS", "Hachette", "CT", "XW", "WE", "VI"];
    const known = CRITIC_ORDER.filter(c => criticsSet.has(c));
    const rest = Array.from(criticsSet).filter(c => !CRITIC_ORDER.includes(c)).sort();
    const critics = [...known, ...rest];

    return { years, critics, cellMap };
  }, [cells]);

  const handleMouseEnter = useCallback(
    (e: React.MouseEvent<SVGRectElement>, cell: DivergenceCell) => {
      const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
      setTooltip({ x: rect.left + rect.width / 2, y: rect.top, cell });
    },
    []
  );

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  if (cells.length === 0) {
    return (
      <div className="glass-card p-12 flex items-center justify-center text-[rgba(250,247,245,0.5)] text-sm">
        {labels.noData}
      </div>
    );
  }

  const svgWidth = LABEL_W + years.length * CELL_W;
  const svgHeight = HEADER_H + critics.length * CELL_H;

  return (
    <div className="space-y-4">
      {/* Subtitle */}
      <p className="text-xs text-[rgba(250,247,245,0.50)]">{labels.subtitle}</p>

      {/* Heatmap — horizontally scrollable */}
      <div className="glass-card p-4 overflow-x-auto" style={{ background: "rgba(9,8,15,0.7)" }}>
        <ResponsiveContainer width="100%" height={svgHeight + 8}>
          <svg
            width={svgWidth}
            height={svgHeight}
            style={{ display: "block" }}
            onMouseLeave={handleMouseLeave}
          >
            {/* ── Year header ── */}
            {years.map((year, xi) => (
              <text
                key={year}
                x={LABEL_W + xi * CELL_W + CELL_W / 2}
                y={HEADER_H - 8}
                textAnchor="middle"
                fontSize={8}
                fill="rgba(250,247,245,0.35)"
                fontFamily="monospace"
              >
                {String(year).slice(2)}
              </text>
            ))}

            {/* ── Critic rows ── */}
            {critics.map((critic, yi) => {
              const cellY = HEADER_H + yi * CELL_H;
              return (
                <g key={critic}>
                  {/* Row label */}
                  <text
                    x={LABEL_W - 6}
                    y={cellY + CELL_H / 2 + 4}
                    textAnchor="end"
                    fontSize={9}
                    fill="rgba(250,247,245,0.60)"
                    fontFamily="monospace"
                    fontWeight={500}
                  >
                    {critic}
                  </text>

                  {/* Cells for this row */}
                  {years.map((year, xi) => {
                    const cell = cellMap.get(`${critic}|${year}`);
                    const cx = LABEL_W + xi * CELL_W;

                    if (!cell) {
                      // Empty cell placeholder
                      return (
                        <rect
                          key={year}
                          x={cx + 1}
                          y={cellY + 1}
                          width={CELL_W - 2}
                          height={CELL_H - 2}
                          rx={2}
                          fill="rgba(255,255,255,0.03)"
                          stroke="rgba(255,255,255,0.05)"
                          strokeWidth={0.5}
                        />
                      );
                    }

                    const bg = scoreToColor(cell.avg);
                    const textFill = cell.avg > 55 ? "rgba(15,14,23,0.85)" : "rgba(250,247,245,0.85)";

                    return (
                      <g key={year}>
                        <rect
                          x={cx + 1}
                          y={cellY + 1}
                          width={CELL_W - 2}
                          height={CELL_H - 2}
                          rx={2}
                          fill={bg}
                          stroke="rgba(0,0,0,0.15)"
                          strokeWidth={0.5}
                          style={{ cursor: "pointer" }}
                          onMouseEnter={(e) => handleMouseEnter(e, cell)}
                        />
                        {/* Score text — only if cell is wide enough to read */}
                        <text
                          x={cx + CELL_W / 2}
                          y={cellY + CELL_H / 2 + 3.5}
                          textAnchor="middle"
                          fontSize={7}
                          fill={textFill}
                          fontFamily="monospace"
                          fontWeight={600}
                          style={{ pointerEvents: "none", userSelect: "none" }}
                        >
                          {Math.round(cell.avg)}
                        </text>
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 px-1">
        <span className="text-[10px] text-[rgba(250,247,245,0.45)]">{labels.legend}</span>
        <svg width={LEGEND_BAR_W} height={LEGEND_BAR_H + 20} overflow="visible">
          <defs>
            <linearGradient id="divergenceLegendGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="#2D1B2E" />
              <stop offset="50%"  stopColor="#A53860" />
              <stop offset="100%" stopColor="#E5B25D" />
            </linearGradient>
          </defs>
          <rect x={0} y={0} width={LEGEND_BAR_W} height={LEGEND_BAR_H} rx={3} fill="url(#divergenceLegendGrad)" />
          {/* Tick labels */}
          {[0, 50, 75, 100].map((v) => (
            <text
              key={v}
              x={(v / 100) * LEGEND_BAR_W}
              y={LEGEND_BAR_H + 12}
              textAnchor="middle"
              fontSize={8}
              fill="rgba(250,247,245,0.45)"
              fontFamily="monospace"
            >
              {v}
            </text>
          ))}
        </svg>
      </div>

      {/* Floating tooltip (portal-style via fixed positioning) */}
      {tooltip && (
        <div
          style={{
            position: "fixed",
            left: tooltip.x,
            top: tooltip.y - 8,
            transform: "translate(-50%, -100%)",
            zIndex: 50,
            pointerEvents: "none",
          }}
          className="glass-card px-3 py-2 text-[11px] space-y-0.5 shadow-xl border border-[rgba(165,56,96,0.4)]"
        >
          <div className="font-semibold text-[color:var(--color-champagne,#E5B25D)]">
            {tooltip.cell.critic} · {tooltip.cell.year}
          </div>
          <div className="text-[rgba(250,247,245,0.85)]">
            {labels.tooltipAvg}: <span className="font-mono font-semibold">{tooltip.cell.avg.toFixed(1)}</span>
          </div>
          <div className="text-[rgba(250,247,245,0.65)]">
            {labels.tooltipCount}: <span className="font-mono">{tooltip.cell.count}</span>
          </div>
          <div className="text-[rgba(250,247,245,0.65)]">
            {labels.tooltipDivergence}: <span className="font-mono">±{tooltip.cell.divergence.toFixed(1)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
