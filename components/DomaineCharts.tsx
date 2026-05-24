"use client";

import { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const SERIES_COLORS = [
  "#FF5C8A", "#6FFFE9", "#FFD166", "#FFB3C8",
  "#8EFEED", "#FF89A6", "#A53860", "#E5B25D",
  "#c97aee", "#7ECCD4",
];

export interface CuveeYearPoint {
  cuveeName: string;
  vintage: number;
  avgPrice: number | null;
  bestRating: number | null;
}

export interface CuveeEvolutionChartProps {
  data: CuveeYearPoint[];
  cuveeNames: string[];
  labels: {
    metricPrice: string;
    metricRating: string;
    allCuvees: string;
    noData: string;
    priceAxis: string;
    ratingAxis: string;
    evolution: string;
  };
}

export function CuveeEvolutionChart({ data, cuveeNames, labels }: CuveeEvolutionChartProps) {
  const [metric, setMetric] = useState<"rating" | "price">("rating");
  const [selectedCuvees, setSelectedCuvees] = useState<Set<string>>(
    () => new Set(cuveeNames.slice(0, 8)),
  );

  const years = useMemo(() => {
    const ys = new Set(data.map((d) => d.vintage));
    return Array.from(ys).sort((a, b) => a - b);
  }, [data]);

  const chartData = useMemo(() => {
    return years.map((year) => {
      const point: Record<string, number | null> & { vintage: number } = { vintage: year };
      for (const cuvee of selectedCuvees) {
        const dp = data.find((d) => d.vintage === year && d.cuveeName === cuvee);
        point[cuvee] = dp ? (metric === "price" ? dp.avgPrice : dp.bestRating) : null;
      }
      return point;
    });
  }, [years, selectedCuvees, metric, data]);

  const activeCuvees = Array.from(selectedCuvees);
  const hasData = chartData.some((p) => activeCuvees.some((c) => p[c] !== null));

  function toggleCuvee(name: string) {
    setSelectedCuvees((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        if (next.size > 1) next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }

  return (
    <div className="glass-card p-5 space-y-4" style={{ background: "rgba(13,6,26,0.7)" }}>
      {/* Controls row */}
      <div className="flex flex-wrap gap-3 items-start">
        {/* Metric toggle */}
        <div
          className="flex items-center gap-0.5 rounded-lg p-0.5"
          style={{ background: "rgba(255,255,255,0.06)" }}
        >
          {(["rating", "price"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className="px-3 py-1 text-xs rounded-md transition-colors"
              style={
                metric === m
                  ? { background: "var(--color-accent)", color: "var(--color-bg)" }
                  : { color: "rgba(250,247,245,0.5)" }
              }
            >
              {m === "price" ? labels.metricPrice : labels.metricRating}
            </button>
          ))}
        </div>

        {/* Cuvée chip filters */}
        <div className="flex flex-wrap gap-1.5">
          {cuveeNames.map((name, i) => {
            const active = selectedCuvees.has(name);
            const col = SERIES_COLORS[i % SERIES_COLORS.length];
            return (
              <button
                key={name}
                onClick={() => toggleCuvee(name)}
                className="px-2 py-0.5 text-[10px] rounded-full border transition-all"
                style={
                  active
                    ? { background: col + "28", borderColor: col, color: col }
                    : { background: "transparent", borderColor: "rgba(255,255,255,0.12)", color: "rgba(250,247,245,0.4)" }
                }
              >
                {name}
              </button>
            );
          })}
        </div>
      </div>

      {/* Chart */}
      {!hasData ? (
        <div className="h-64 flex items-center justify-center text-sm" style={{ color: "rgba(250,247,245,0.35)" }}>
          {labels.noData}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,92,138,0.1)" />
            <XAxis
              dataKey="vintage"
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,92,138,0.2)" }}
              allowDecimals={false}
            />
            <YAxis
              domain={metric === "rating" ? [60, 100] : ["auto", "auto"]}
              tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "rgba(255,92,138,0.2)" }}
              label={{
                value: metric === "price" ? labels.priceAxis : labels.ratingAxis,
                angle: -90,
                position: "insideLeft",
                style: { fill: "rgba(250,247,245,0.4)", fontSize: 10 },
              }}
            />
            <Tooltip
              contentStyle={{
                background: "rgba(26,11,46,0.96)",
                border: "1px solid rgba(255,92,138,0.35)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "rgba(250,247,245,0.65)", marginBottom: 4 }}
              formatter={(value, name) => [
                typeof value === "number"
                  ? metric === "price"
                    ? `€${value.toFixed(2)}`
                    : `${value.toFixed(1)}/100`
                  : String(value),
                String(name),
              ]}
              labelFormatter={(v) => `${v}`}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: "rgba(250,247,245,0.65)" }}
              iconType="circle"
            />
            {activeCuvees.map((cuvee, i) => (
              <Line
                key={cuvee}
                type="monotone"
                dataKey={cuvee}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 4, fill: SERIES_COLORS[i % SERIES_COLORS.length] }}
                activeDot={{ r: 6 }}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
