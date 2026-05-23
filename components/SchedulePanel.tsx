"use client";

import { useEffect, useState, useCallback } from "react";
import { Clock, Check, X, CalendarClock } from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface SourceRow {
  sourceCode: string;
  sourceName: string;
  sourceTier: string;
  cronExpr: string | null;
}

interface ScheduleLabels {
  title: string;
  subtitle: string;
  source: string;
  cronExpr: string;
  description: string;
  save: string;
  clear: string;
  saved: string;
  invalid: string;
  placeholder: string;
  manualOnly: string;
  groupRetail: string;
  groupEmail: string;
  groupCritic: string;
  groupVintage: string;
  restartHint: string;
}

// ─── Schedule state → cron ────────────────────────────────────────────────────

type Freq = "manual" | "daily" | "twice_daily" | "weekly" | "monthly";

interface SchedState {
  freq: Freq;
  hour: number;   // 0-23 (0-11 for twice_daily, second fires at hour+12)
  minute: number; // 0 | 15 | 30 | 45
  dow: number;    // 0=Sun … 6=Sat (weekly only)
  dom: number;    // 1-28 (monthly only)
}

const DOW_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MINUTES = [0, 15, 30, 45];
const HOURS_ALL = Array.from({ length: 24 }, (_, i) => i);
const HOURS_HALF = Array.from({ length: 12 }, (_, i) => i); // 0-11 for twice_daily

function stateToCron(s: SchedState): string | null {
  if (s.freq === "manual") return null;
  const M = String(s.minute);
  const H = String(s.hour);
  if (s.freq === "daily") return `${M} ${H} * * *`;
  if (s.freq === "twice_daily") {
    const h2 = (s.hour + 12) % 24;
    return `${M} ${H},${h2} * * *`;
  }
  if (s.freq === "weekly") return `${M} ${H} * * ${s.dow}`;
  if (s.freq === "monthly") return `${M} ${H} ${s.dom} * *`;
  return null;
}

function cronToState(cron: string | null): SchedState {
  const defaults: SchedState = { freq: "manual", hour: 3, minute: 0, dow: 1, dom: 1 };
  if (!cron) return defaults;
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return defaults;
  const [minStr, hourStr, domStr, , dowStr] = parts;
  const minute = MINUTES.includes(parseInt(minStr)) ? parseInt(minStr) : 0;

  // weekly
  if (dowStr !== "*" && /^\d+$/.test(dowStr)) {
    return { freq: "weekly", hour: parseInt(hourStr) || 0, minute, dow: parseInt(dowStr), dom: 1 };
  }
  // monthly
  if (domStr !== "*" && /^\d+$/.test(domStr)) {
    return { freq: "monthly", hour: parseInt(hourStr) || 0, minute, dow: 1, dom: parseInt(domStr) || 1 };
  }
  // twice daily: "M H1,H2 * * *" where |H1-H2|=12
  if (hourStr.includes(",")) {
    const [h1, h2] = hourStr.split(",").map(Number);
    if (!isNaN(h1) && !isNaN(h2) && Math.abs(h1 - h2) === 12) {
      return { freq: "twice_daily", hour: Math.min(h1, h2), minute, dow: 1, dom: 1 };
    }
  }
  // daily
  if (hourStr !== "*" && /^\d+$/.test(hourStr)) {
    return { freq: "daily", hour: parseInt(hourStr), minute, dow: 1, dom: 1 };
  }
  return defaults;
}

function pad(n: number) { return String(n).padStart(2, "0"); }

function describeState(s: SchedState): string {
  if (s.freq === "manual") return "";
  const t = `${pad(s.hour)}:${pad(s.minute)} UTC`;
  if (s.freq === "daily") return `Every day at ${t}`;
  if (s.freq === "twice_daily") {
    const t2 = `${pad((s.hour + 12) % 24)}:${pad(s.minute)} UTC`;
    return `Every day at ${t} and ${t2}`;
  }
  if (s.freq === "weekly") return `Every ${DOW_NAMES[s.dow]} at ${t}`;
  if (s.freq === "monthly") return `Every month on day ${s.dom} at ${t}`;
  return "";
}

// ─── Shared select style ──────────────────────────────────────────────────────

const SEL = [
  "bg-[rgba(13,6,26,0.7)] border border-[color:var(--color-border)]",
  "text-[color:var(--color-fg)] text-xs rounded px-2 py-1.5 outline-none",
  "focus:border-[color:var(--color-primary)] cursor-pointer transition-colors",
  "hover:border-[color:var(--color-primary)]",
].join(" ");

// ─── Tier grouping ────────────────────────────────────────────────────────────

type Group = "retail" | "email" | "critic" | "vintage";

function getGroup(row: SourceRow): Group {
  if (row.sourceCode.endsWith("_email")) return "email";
  if (row.sourceTier === "E_press_critic") return "critic";
  if (row.sourceTier === "F_vintage_authority") return "vintage";
  return "retail";
}

const TIER_COLORS: Record<string, string> = {
  B_retailer_major: "text-[color:var(--color-coral-400)]",
  C_retailer_minor: "text-[color:var(--color-fg-muted)]",
  D_user_aggregate: "text-[color:var(--color-fg-muted)]",
  E_press_critic: "text-[color:var(--color-mint-400)]",
  F_vintage_authority: "text-[color:var(--color-coral-200)]",
};

// ─── Row component ────────────────────────────────────────────────────────────

type SaveState = "idle" | "saving" | "saved" | "error";

function ScheduleRow({
  row,
  onSave,
}: {
  row: SourceRow;
  onSave: (sourceCode: string, cronExpr: string | null) => Promise<void>;
}) {
  const [s, setS] = useState<SchedState>(() => cronToState(row.cronExpr));
  const [saveState, setSaveState] = useState<SaveState>("idle");

  // Sync if parent data changes (e.g. initial load)
  useEffect(() => { setS(cronToState(row.cronExpr)); }, [row.cronExpr]);

  const cronExpr = stateToCron(s);
  const isDirty = cronExpr !== row.cronExpr;

  async function save(next: SchedState) {
    setSaveState("saving");
    try {
      await onSave(row.sourceCode, stateToCron(next));
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 2000);
    } catch {
      setSaveState("error");
      setTimeout(() => setSaveState("idle"), 2500);
    }
  }

  function update(patch: Partial<SchedState>) {
    setS((prev) => {
      const next = { ...prev, ...patch };
      // If switching to twice_daily and hour > 11, clamp it
      if (next.freq === "twice_daily" && next.hour > 11) next.hour = next.hour % 12;
      return next;
    });
  }

  const hourOptions = s.freq === "twice_daily" ? HOURS_HALF : HOURS_ALL;
  const desc = describeState(s);

  return (
    <div className="py-3 border-b border-[color:var(--color-border)] last:border-0">
      {/* Source name */}
      <div className="flex items-center gap-2 mb-2">
        <span className={`font-mono text-[10px] font-bold shrink-0 ${TIER_COLORS[row.sourceTier] ?? "text-[color:var(--color-fg-muted)]"}`}>
          {row.sourceTier.charAt(0)}
        </span>
        <span className="text-sm font-medium text-[color:var(--color-fg)]">{row.sourceName}</span>
        <span className="font-mono text-[10px] text-[color:var(--color-fg-subtle)]">{row.sourceCode}</span>
      </div>

      {/* Sentence-form controls */}
      <div className="flex items-center gap-2 flex-wrap">

        {/* Frequency */}
        <select className={SEL} value={s.freq} onChange={(e) => update({ freq: e.target.value as Freq })}>
          <option value="manual">— manual only —</option>
          <option value="daily">1 time a day</option>
          <option value="twice_daily">2 times a day</option>
          <option value="weekly">1 time a week</option>
          <option value="monthly">1 time a month</option>
        </select>

        {/* Day-of-week (weekly) */}
        {s.freq === "weekly" && (
          <>
            <span className="text-xs text-[color:var(--color-fg-subtle)]">on</span>
            <select className={SEL} value={s.dow} onChange={(e) => update({ dow: Number(e.target.value) })}>
              {DOW_NAMES.map((d, i) => <option key={i} value={i}>{d}</option>)}
            </select>
          </>
        )}

        {/* Day-of-month (monthly) */}
        {s.freq === "monthly" && (
          <>
            <span className="text-xs text-[color:var(--color-fg-subtle)]">on day</span>
            <select className={SEL} value={s.dom} onChange={(e) => update({ dom: Number(e.target.value) })}>
              {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </>
        )}

        {/* Time (hidden when manual) */}
        {s.freq !== "manual" && (
          <>
            <span className="text-xs text-[color:var(--color-fg-subtle)]">at</span>
            <select className={SEL} value={s.hour} onChange={(e) => update({ hour: Number(e.target.value) })}>
              {hourOptions.map((h) => <option key={h} value={h}>{pad(h)}</option>)}
            </select>
            <span className="text-xs text-[color:var(--color-fg-subtle)] -mx-1">:</span>
            <select className={SEL} value={s.minute} onChange={(e) => update({ minute: Number(e.target.value) })}>
              {MINUTES.map((m) => <option key={m} value={m}>{pad(m)}</option>)}
            </select>
            <span className="text-[10px] text-[color:var(--color-fg-subtle)]">UTC</span>
          </>
        )}

        {/* Save / clear */}
        {saveState === "saved" && (
          <span className="flex items-center gap-1 text-xs text-[color:var(--color-mint-400)]">
            <Check className="size-3" strokeWidth={2.5} /> saved
          </span>
        )}
        {saveState === "error" && (
          <span className="text-xs text-[color:var(--color-coral-400)]">error</span>
        )}
        {isDirty && (
          <button
            onClick={() => save(s)}
            disabled={saveState === "saving"}
            className="btn btn-ghost text-xs py-1 px-2 disabled:opacity-40"
          >
            {saveState === "saving" ? "…" : "Save"}
          </button>
        )}
        {s.freq !== "manual" && !isDirty && (
          <button
            onClick={() => { update({ freq: "manual" }); save({ ...s, freq: "manual" }); }}
            className="btn btn-ghost text-xs py-1 px-2 text-[color:var(--color-fg-subtle)]"
            title="Remove schedule"
          >
            <X className="size-3" strokeWidth={2.5} />
          </button>
        )}
      </div>

      {/* Human-readable confirmation */}
      {desc && (
        <p className="mt-1 text-[11px] text-[color:var(--color-fg-subtle)] italic">{desc}</p>
      )}
    </div>
  );
}

// ─── Group section ────────────────────────────────────────────────────────────

function GroupSection({
  title,
  rows,
  onSave,
}: {
  title: string;
  rows: SourceRow[];
  onSave: (sourceCode: string, cronExpr: string | null) => Promise<void>;
}) {
  if (rows.length === 0) return null;
  const scheduled = rows.filter((r) => r.cronExpr).length;
  return (
    <div className="glass-card p-4">
      <div className="flex items-center gap-2 mb-1">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-[color:var(--color-fg-muted)]">
          {title}
        </h3>
        {scheduled > 0 && (
          <span className="badge badge-verified text-[10px] py-0.5">
            {scheduled} scheduled
          </span>
        )}
      </div>
      <div>
        {rows.map((row) => (
          <ScheduleRow key={row.sourceCode} row={row} onSave={onSave} />
        ))}
      </div>
    </div>
  );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export function SchedulePanel({ labels }: { labels: ScheduleLabels }) {
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchSchedules = useCallback(async () => {
    try {
      const res = await fetch("/api/schedule");
      if (res.ok) {
        const data = await res.json();
        setSources(data.sources ?? []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  const handleSave = useCallback(
    async (sourceCode: string, cronExpr: string | null) => {
      const res = await fetch("/api/schedule", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sourceCode, cronExpr }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(String(j.error ?? res.statusText));
      }
      // Update local state immediately
      setSources((prev) =>
        prev.map((s) => (s.sourceCode === sourceCode ? { ...s, cronExpr } : s)),
      );
    },
    [],
  );

  const grouped: Record<Group, SourceRow[]> = {
    retail: [],
    email: [],
    critic: [],
    vintage: [],
  };
  for (const s of sources) {
    grouped[getGroup(s)].push(s);
  }

  const totalScheduled = sources.filter((s) => s.cronExpr).length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <p className="text-xs text-[color:var(--color-fg-subtle)] max-w-prose">
          {labels.subtitle}
        </p>
        {totalScheduled > 0 && (
          <span className="badge badge-verified text-xs shrink-0">
            <CalendarClock className="size-3" strokeWidth={2.5} />
            {totalScheduled} / {sources.length} scheduled
          </span>
        )}
      </div>

      {loading ? (
        <div className="glass-card p-8 text-center">
          <Clock className="size-8 mx-auto mb-3 text-[color:var(--color-fg-subtle)] animate-spin" strokeWidth={1.5} />
        </div>
      ) : (
        <div className="space-y-3">
          <GroupSection title={labels.groupRetail}  rows={grouped.retail}  onSave={handleSave} />
          <GroupSection title={labels.groupEmail}   rows={grouped.email}   onSave={handleSave} />
          <GroupSection title={labels.groupCritic}  rows={grouped.critic}  onSave={handleSave} />
          <GroupSection title={labels.groupVintage} rows={grouped.vintage} onSave={handleSave} />
        </div>
      )}

      <p className="text-[10px] text-[color:var(--color-fg-subtle)] italic">
        {labels.restartHint}
      </p>
    </div>
  );
}
