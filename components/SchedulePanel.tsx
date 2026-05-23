"use client";

import { useEffect, useState, useCallback } from "react";
import { Clock, Check, X, AlertTriangle, CalendarClock } from "lucide-react";

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

// ─── Cron helpers ─────────────────────────────────────────────────────────────

function isValidCron(expr: string): boolean {
  const parts = expr.trim().split(/\s+/);
  return parts.length === 5 && parts.every((p) => /^[\d*/,\-]+$/.test(p));
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function describeCron(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return "";
  const [min, hour, dom, , dow] = parts;

  const allWild = (v: string) => v === "*";
  const fixed = (v: string) => /^\d+$/.test(v);

  // Time component
  let time = "";
  if (fixed(hour) && fixed(min)) {
    time = `${hour.padStart(2, "0")}:${min.padStart(2, "0")} UTC`;
  } else if (fixed(hour)) {
    time = `${hour}h UTC`;
  }

  if (!allWild(dow) && fixed(dow)) {
    const dayName = DAYS[parseInt(dow)] ?? `day ${dow}`;
    return time ? `Every ${dayName} at ${time}` : `Every ${dayName}`;
  }
  if (!allWild(dom) && fixed(dom)) {
    return time ? `Monthly on day ${dom} at ${time}` : `Monthly on day ${dom}`;
  }
  if (time) return `Daily at ${time}`;
  if (min === "0" && allWild(hour)) return "Every hour";
  if (allWild(min) && allWild(hour)) return "Every minute";
  return expr;
}

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

const TIER_SHORT: Record<string, string> = {
  B_retailer_major: "B",
  C_retailer_minor: "C",
  D_user_aggregate: "D",
  E_press_critic: "E",
  F_vintage_authority: "F",
};

// ─── Row component ────────────────────────────────────────────────────────────

type RowState = "idle" | "saving" | "saved" | "error";

function ScheduleRow({
  row,
  labels,
  onSave,
}: {
  row: SourceRow;
  labels: ScheduleLabels;
  onSave: (sourceCode: string, cronExpr: string | null) => Promise<void>;
}) {
  const [value, setValue] = useState(row.cronExpr ?? "");
  const [state, setState] = useState<RowState>("idle");
  const [validationMsg, setValidationMsg] = useState("");

  // Keep local value in sync if parent data refreshes
  useEffect(() => {
    setValue(row.cronExpr ?? "");
  }, [row.cronExpr]);

  const isDirty = value !== (row.cronExpr ?? "");
  const hasValue = value.trim().length > 0;
  const valid = !hasValue || isValidCron(value);

  async function handleSave() {
    if (!valid) {
      setValidationMsg(labels.invalid);
      return;
    }
    setValidationMsg("");
    setState("saving");
    try {
      await onSave(row.sourceCode, hasValue ? value.trim() : null);
      setState("saved");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 3000);
    }
  }

  function handleClear() {
    setValue("");
    if (row.cronExpr !== null) {
      onSave(row.sourceCode, null)
        .then(() => {
          setState("saved");
          setTimeout(() => setState("idle"), 2000);
        })
        .catch(() => setState("idle"));
    }
  }

  const desc = hasValue && valid ? describeCron(value) : "";

  return (
    <div className="flex items-center gap-3 py-2 border-b border-[color:var(--color-border)] last:border-0 flex-wrap sm:flex-nowrap">
      {/* Source name */}
      <div className="flex items-center gap-2 min-w-0 flex-1 basis-36">
        <span
          className={`font-mono text-[10px] w-4 shrink-0 font-bold ${TIER_COLORS[row.sourceTier] ?? "text-[color:var(--color-fg-muted)]"}`}
        >
          {TIER_SHORT[row.sourceTier] ?? "?"}
        </span>
        <span
          className="truncate text-sm text-[color:var(--color-fg)] font-mono"
          title={row.sourceName}
        >
          {row.sourceCode}
        </span>
      </div>

      {/* Cron input */}
      <div className="flex flex-col gap-0.5 flex-1 basis-40 min-w-0">
        <input
          type="text"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setValidationMsg("");
            setState("idle");
          }}
          onKeyDown={(e) => e.key === "Enter" && handleSave()}
          placeholder={labels.placeholder}
          spellCheck={false}
          className={`w-full font-mono text-xs px-2 py-1.5 rounded bg-[rgba(13,6,26,0.6)] border text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] outline-none focus:ring-1 transition-colors ${
            !valid && hasValue
              ? "border-[color:var(--color-coral-600)] focus:ring-[color:var(--color-coral-700)]"
              : "border-[color:var(--color-border)] focus:ring-[color:var(--color-coral-800)]"
          }`}
        />
        {validationMsg && (
          <p className="text-[10px] text-[color:var(--color-coral-400)] leading-none">
            {validationMsg}
          </p>
        )}
      </div>

      {/* Human-readable description */}
      <div className="flex-1 basis-32 min-w-0">
        <span className="text-xs text-[color:var(--color-fg-muted)] truncate block">
          {desc || (
            <span className="text-[color:var(--color-fg-subtle)] italic">
              {labels.manualOnly}
            </span>
          )}
        </span>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1.5 shrink-0">
        {state === "saved" && (
          <span className="text-[color:var(--color-mint-400)] flex items-center gap-1 text-xs">
            <Check className="size-3" strokeWidth={2.5} />
            {labels.saved}
          </span>
        )}
        {state === "error" && (
          <span className="text-[color:var(--color-coral-400)] flex items-center gap-1 text-xs">
            <AlertTriangle className="size-3" strokeWidth={2.5} />
          </span>
        )}
        {(state === "idle" || state === "saving") && isDirty && hasValue && (
          <button
            onClick={handleSave}
            disabled={state === "saving" || !valid}
            className="btn btn-ghost text-xs py-1 px-2 disabled:opacity-40"
          >
            {state === "saving" ? "…" : labels.save}
          </button>
        )}
        {(state === "idle" || state === "saving") && (row.cronExpr !== null || (hasValue && !isDirty)) && (
          <button
            onClick={handleClear}
            disabled={state === "saving"}
            className="btn btn-ghost text-xs py-1 px-2 text-[color:var(--color-fg-muted)] disabled:opacity-40"
            title={labels.clear}
          >
            <X className="size-3" strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Group section ────────────────────────────────────────────────────────────

function GroupSection({
  title,
  rows,
  labels,
  onSave,
}: {
  title: string;
  rows: SourceRow[];
  labels: ScheduleLabels;
  onSave: (sourceCode: string, cronExpr: string | null) => Promise<void>;
}) {
  if (rows.length === 0) return null;
  const scheduled = rows.filter((r) => r.cronExpr).length;
  return (
    <div className="glass-card p-4">
      <div className="flex items-center gap-2 mb-3">
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
          <ScheduleRow key={row.sourceCode} row={row} labels={labels} onSave={onSave} />
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
          <GroupSection
            title={labels.groupRetail}
            rows={grouped.retail}
            labels={labels}
            onSave={handleSave}
          />
          <GroupSection
            title={labels.groupEmail}
            rows={grouped.email}
            labels={labels}
            onSave={handleSave}
          />
          <GroupSection
            title={labels.groupCritic}
            rows={grouped.critic}
            labels={labels}
            onSave={handleSave}
          />
          <GroupSection
            title={labels.groupVintage}
            rows={grouped.vintage}
            labels={labels}
            onSave={handleSave}
          />
        </div>
      )}

      <p className="text-[10px] text-[color:var(--color-fg-subtle)] italic">
        {labels.restartHint}
      </p>
    </div>
  );
}
