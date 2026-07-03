"use client";

import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Label,
  type ScatterShapeProps,
} from "recharts";

export interface BestValuePoint {
  wineKey: string;
  canonicalName: string;
  priceEur: number;
  ratingNorm100: number;
  score: number;
}

interface TooltipPayload {
  payload?: BestValuePoint;
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayload[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div
      className="glass-card p-3 text-sm space-y-1"
      style={{ background: "rgba(15, 14, 23, 0.92)", border: "1px solid rgba(165,56,96,0.4)" }}
    >
      <p className="font-semibold text-[color:var(--color-fg)] leading-tight max-w-[200px]">{d.canonicalName}</p>
      <p className="text-[color:var(--color-fg-muted)]">
        <span className="font-mono text-[color:var(--color-accent)]">€{d.priceEur.toFixed(2)}</span>
        {" · "}
        <span className="font-mono text-[color:var(--color-accent)]">{d.ratingNorm100.toFixed(1)}/100</span>
      </p>
      <p className="text-xs text-[color:var(--color-fg-muted)]">
        score {d.score.toFixed(2)}
      </p>
    </div>
  );
}

/** Dot radius scaled proportionally to score in [4, 14] px range. */
function scaledRadius(score: number, minScore: number, maxScore: number): number {
  if (maxScore === minScore) return 8;
  const t = (score - minScore) / (maxScore - minScore);
  return 4 + t * 10;
}

interface BestValueScatterProps {
  data: BestValuePoint[];
}

export function BestValueScatter({ data }: BestValueScatterProps) {
  if (data.length === 0) {
    return (
      <div className="glass-card p-8 flex items-center justify-center text-[color:var(--color-fg-muted)] text-sm">
        No data to display
      </div>
    );
  }

  const scores = data.map((d) => d.score);
  const minScore = Math.min(...scores);
  const maxScore = Math.max(...scores);

  // Recharts scatter needs x/y props; we attach radius via the data itself
  const chartData = data.map((d) => ({
    ...d,
    r: scaledRadius(d.score, minScore, maxScore),
  }));

  return (
    <div
      className="glass-card p-4"
      style={{ background: "rgba(9, 8, 15, 0.7)" }}
    >
      <ResponsiveContainer width="100%" height={340}>
        <ScatterChart margin={{ top: 16, right: 24, bottom: 32, left: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(165,56,96,0.12)" />
          <XAxis
            dataKey="priceEur"
            type="number"
            name="Price (€)"
            tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "rgba(165,56,96,0.2)" }}
          >
            <Label
              value="Price (€)"
              offset={-8}
              position="insideBottom"
              style={{ fill: "rgba(250,247,245,0.45)", fontSize: 11 }}
            />
          </XAxis>
          <YAxis
            dataKey="ratingNorm100"
            type="number"
            name="Rating /100"
            domain={[60, 100]}
            tick={{ fill: "rgba(250,247,245,0.55)", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "rgba(165,56,96,0.2)" }}
          >
            <Label
              value="Rating /100"
              angle={-90}
              position="insideLeft"
              style={{ fill: "rgba(250,247,245,0.45)", fontSize: 11 }}
            />
          </YAxis>
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: "rgba(165,56,96,0.3)" }} />
          <Scatter
            data={chartData}
            fill="#A53860"
            fillOpacity={0.75}
            shape={(props: ScatterShapeProps) => {
              const cx = typeof props.cx === "number" ? props.cx : 0;
              const cy = typeof props.cy === "number" ? props.cy : 0;
              const payload = props.payload as { r?: number } | undefined;
              const r = payload?.r ?? 6;
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill="#A53860"
                  fillOpacity={0.75}
                  stroke="#A53860"
                  strokeWidth={1}
                  strokeOpacity={0.4}
                />
              );
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
