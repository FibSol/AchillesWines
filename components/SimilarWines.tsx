"use client";

import type { SimilarWineItem } from "@/app/api/wines/[wineKey]/similar/route";

/* ─── Color dot ─────────────────────────────────────────────────────────── */
const COLOR_MAP: Record<string, string> = {
  red: "#b71f55",
  white: "#FFD166",
  "rosé": "#FF89A6",
  sparkling: "#8EFEED",
  sweet: "#FFB3C8",
  fortified: "#553987",
  orange: "#FF5C8A",
};

function ColorDot({ color }: { color: string }) {
  return (
    <span
      className="inline-block size-2 rounded-full shrink-0 mt-0.5"
      style={{ background: COLOR_MAP[color] ?? "#FAF7F5" }}
    />
  );
}

/* ─── Match badge ────────────────────────────────────────────────────────── */
function MatchBadge({ score, label }: { score: number; label: string }) {
  const pct = Math.round(score * 100);
  const strength =
    pct >= 85 ? "high" : pct >= 65 ? "mid" : "low";
  const styles = {
    high: { background: "rgba(165,56,96,0.18)", color: "#e07898", border: "1px solid rgba(165,56,96,0.4)" },
    mid: { background: "rgba(229,178,93,0.15)", color: "#E5B25D", border: "1px solid rgba(229,178,93,0.35)" },
    low: { background: "rgba(255,255,255,0.06)", color: "rgba(250,247,245,0.5)", border: "1px solid rgba(255,255,255,0.12)" },
  };
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.07em] px-2 py-0.5 rounded-full"
      style={styles[strength]}
    >
      {label} {pct}%
    </span>
  );
}

/* ─── Single wine card ───────────────────────────────────────────────────── */
function SimilarWineCard({
  wine,
  labels,
}: {
  wine: SimilarWineItem;
  labels: {
    match: string;
  };
}) {
  return (
    <div
      className="shrink-0 w-52 rounded-xl border p-4 flex flex-col gap-2 transition-all hover:scale-[1.015]"
      style={{
        background: "rgba(26,24,37,0.85)",
        border: "1px solid rgba(165,56,96,0.2)",
        boxShadow: "0 4px 20px -6px rgba(0,0,0,0.45)",
      }}
    >
      {/* Top: match badge */}
      <div className="flex items-center justify-between">
        <MatchBadge score={wine.similarity_score} label={labels.match} />
        <ColorDot color={wine.color} />
      </div>

      {/* Producer + Cuvée */}
      <div>
        <p
          className="text-xs font-semibold leading-tight line-clamp-1"
          style={{ color: "var(--color-fg)" }}
        >
          {wine.producer_name}
        </p>
        <p
          className="text-[11px] leading-tight line-clamp-1 mt-0.5"
          style={{ color: "rgba(250,247,245,0.65)" }}
        >
          {wine.cuvee_name || <em style={{ opacity: 0.45 }}>Grand Vin</em>}
          {wine.vintage ? ` · ${wine.vintage}` : ""}
        </p>
      </div>

      {/* Appellation */}
      <p
        className="text-[10px] line-clamp-1"
        style={{ color: "rgba(250,247,245,0.4)" }}
      >
        {wine.appellation_name}
      </p>

      {/* Score + Price */}
      <div className="flex items-center justify-between mt-auto pt-1" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
        {wine.avg_score != null ? (
          <span
            className="font-mono text-xs font-semibold"
            style={{ color: "var(--color-accent)" }}
          >
            {wine.avg_score.toFixed(1)}/100
          </span>
        ) : (
          <span className="text-xs" style={{ color: "rgba(250,247,245,0.25)" }}>—</span>
        )}
        {wine.min_price != null ? (
          <span
            className="font-mono text-xs"
            style={{ color: "rgba(250,247,245,0.65)" }}
          >
            €{wine.min_price.toFixed(0)}
          </span>
        ) : (
          <span className="text-xs" style={{ color: "rgba(250,247,245,0.25)" }}>—</span>
        )}
      </div>
    </div>
  );
}

/* ─── Main component ─────────────────────────────────────────────────────── */

export interface SimilarWinesProps {
  wines: SimilarWineItem[];
  labels: {
    title: string;
    subtitle: string;
    match: string;
    noResults: string;
  };
}

export function SimilarWines({ wines, labels }: SimilarWinesProps) {
  if (wines.length === 0) {
    return (
      <div
        className="glass-card p-6 text-sm text-center"
        style={{ color: "rgba(250,247,245,0.4)" }}
      >
        {labels.noResults}
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-xl font-display" style={{ color: "var(--color-fg)" }}>
          {labels.title}
        </h2>
        <p className="text-xs mt-1" style={{ color: "rgba(250,247,245,0.45)" }}>
          {labels.subtitle}
        </p>
      </div>

      {/* Horizontal scroll row */}
      <div
        className="flex gap-3 overflow-x-auto pb-3"
        style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(165,56,96,0.3) transparent" }}
      >
        {wines.map((wine) => (
          <SimilarWineCard key={wine.wine_key} wine={wine} labels={{ match: labels.match }} />
        ))}
      </div>
    </div>
  );
}
