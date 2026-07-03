"use client";

import { criticLabel, criticName } from "@/lib/critics";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell as RechartsCell,
} from "recharts";

const SERIES_COLORS = [
  "#A53860",
  "#E5B25D",
  "#E07898",
  "#F5D08C",
  "#5EA87A",
  "#6E1F3D",
];

export interface PricePoint {
  recordedAt: number;
  [seriesKey: string]: number;
}

export interface PriceHistoryChartProps {
  data: PricePoint[];
  sources: string[];
  labels: {
    noData: string;
    priceAxis: string;
  };
}

interface PriceTooltipEntry {
  color?: string;
  dataKey?: string | number;
  value?: number;
}

function formatDate(value: number): string {
  const d = new Date(value * 1000);
  return d.toLocaleDateString(undefined, { year: "2-digit", month: "short", day: "2-digit" });
}

function PriceTooltip({ active, payload, label }: { active?: boolean; payload?: PriceTooltipEntry[]; label?: number }) {
  if (!active || !payload?.length || typeof label !== "number") return null;
  return (
    <div
      className="glass-card p-3 text-xs space-y-1"
      style={{ background: "rgba(15, 14, 23, 0.94)", border: "1px solid rgba(165,56,96,0.4)" }}
    >
      <p className="font-mono text-[color:var(--color-fg-muted)]">{formatDate(label)}</p>
      {payload.map((p, i) => (
        <p key={i} className="font-mono" style={{ color: p.color ?? "#FAF7F5" }}>
          {String(p.dataKey ?? "")} — €{typeof p.value === "number" ? p.value.toFixed(2) : "—"}
        </p>
      ))}
    </div>
  );
}

export function PriceHistoryChart({ data, sources, labels }: PriceHistoryChartProps) {
  if (data.length === 0 || sources.length === 0) {
    return (
      <div className="glass-card p-8 flex items-center justify-center text-[color:var(--color-fg-subtle)] text-sm">
        {labels.noData}
      </div>
    );
  }

  return (
    <div className="glass-card p-4" style={{ background: "rgba(9, 8, 15, 0.7)" }}>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 16, right: 24, bottom: 16, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(165,56,96,0.12)" />
          <XAxis
            dataKey="recordedAt"
            type="number"
            domain={["dataMin", "dataMax"]}
            scale="time"
            tickFormatter={formatDate}
            tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "rgba(165,56,96,0.2)" }}
          />
          <YAxis
            tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "rgba(165,56,96,0.2)" }}
            label={{
              value: labels.priceAxis,
              angle: -90,
              position: "insideLeft",
              style: { fill: "rgba(250,247,245,0.45)", fontSize: 11 },
            }}
          />
          <Tooltip content={<PriceTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 11, color: "rgba(250,247,245,0.7)" }}
            iconType="circle"
          />
          {sources.map((s, i) => (
            <Line
              key={s}
              type="monotone"
              dataKey={s}
              stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 3, fill: SERIES_COLORS[i % SERIES_COLORS.length] }}
              activeDot={{ r: 5 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface RatingPoint {
  criticCode: string;
  score: number;
}

export interface RatingsByCriticChartProps {
  data: RatingPoint[];
  labels: {
    noData: string;
    scoreAxis: string;
  };
}

interface RatingTooltipEntry {
  payload?: RatingPoint;
}

function RatingTooltip({ active, payload }: { active?: boolean; payload?: RatingTooltipEntry[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div
      className="glass-card p-3 text-xs space-y-1"
      style={{ background: "rgba(15, 14, 23, 0.94)", border: "1px solid rgba(165,56,96,0.4)" }}
    >
      <p className="font-semibold text-[color:var(--color-fg)]">{criticName(d.criticCode)}</p>
      <p className="font-mono text-[color:var(--color-accent)]">{d.score.toFixed(1)} / 100</p>
    </div>
  );
}

export function RatingsByCriticChart({ data, labels }: RatingsByCriticChartProps) {
  if (data.length === 0) {
    return (
      <div className="glass-card p-8 flex items-center justify-center text-[color:var(--color-fg-subtle)] text-sm">
        {labels.noData}
      </div>
    );
  }

  return (
    <div className="glass-card p-4" style={{ background: "rgba(9, 8, 15, 0.7)" }}>
      <ResponsiveContainer width="100%" height={320}>
        <BarChart data={data} margin={{ top: 16, right: 24, bottom: 16, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(165,56,96,0.12)" />
          <XAxis
            dataKey="criticCode"
            tickFormatter={criticLabel}
            tick={{ fill: "rgba(250,247,245,0.65)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "rgba(165,56,96,0.2)" }}
          />
          <YAxis
            domain={[60, 100]}
            tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "rgba(165,56,96,0.2)" }}
            label={{
              value: labels.scoreAxis,
              angle: -90,
              position: "insideLeft",
              style: { fill: "rgba(250,247,245,0.45)", fontSize: 11 },
            }}
          />
          <Tooltip content={<RatingTooltip />} cursor={{ fill: "rgba(165,56,96,0.06)" }} />
          <Bar dataKey="score" radius={[4, 4, 0, 0]}>
            {data.map((_, i) => (
              <RechartsCell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} fillOpacity={0.85} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface DrinkingWindowBandProps {
  drinkFrom: number;
  drinkTo: number;
  label: string;
}

export function DrinkingWindowBand({ drinkFrom, drinkTo, label }: DrinkingWindowBandProps) {
  const span = Math.max(drinkTo - drinkFrom + 1, 1);
  const ticks: number[] = [];
  for (let y = drinkFrom; y <= drinkTo; y++) ticks.push(y);

  return (
    <div className="glass-card p-5" style={{ background: "rgba(9, 8, 15, 0.7)" }}>
      <p className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-3">
        {label}
      </p>
      <div className="relative h-12 rounded-md overflow-hidden">
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(90deg, rgba(165,56,96,0.55) 0%, rgba(165,56,96,0.85) 50%, rgba(165,56,96,0.55) 100%)",
          }}
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-[color:var(--color-ivory-100)] font-mono text-sm font-semibold">
            {drinkFrom} — {drinkTo}
            <span className="ml-2 text-[10px] opacity-75">({span} {span > 1 ? "yrs" : "yr"})</span>
          </span>
        </div>
      </div>
      <div className="flex justify-between mt-1 text-[10px] font-mono text-[color:var(--color-fg-subtle)]">
        {ticks.length <= 12 && ticks.map((y) => <span key={y}>{y}</span>)}
      </div>
    </div>
  );
}
