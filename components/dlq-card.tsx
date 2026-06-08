"use client";

import { useState } from "react";
import { AlertTriangle, Check, Ban, EyeOff } from "lucide-react";

type Resolution = "approved_manual" | "blacklisted" | "ignored";

interface DlqRecord {
  dlqId: number;
  errorClass: string;
  errorMessage: string;
  rawRecord: unknown;
  createdAt: Date | number | null;
  sourceKey: number | null;
}

interface DlqCardProps {
  dlq: DlqRecord;
  sourceName: string | null;
  locale: string;
  labels: {
    approve: string;
    blacklist: string;
    ignore: string;
  };
}

export function DlqCard({ dlq, sourceName, locale, labels }: DlqCardProps) {
  const [resolved, setResolved] = useState(false);
  const [resolvedWith, setResolvedWith] = useState<Resolution | null>(null);
  const [loading, setLoading] = useState<Resolution | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleResolve = async (resolution: Resolution) => {
    setLoading(resolution);
    setError(null);
    try {
      const res = await fetch(`/api/dlq/${dlq.dlqId}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { error?: string }).error ?? `HTTP ${res.status}`);
      }
      setResolvedWith(resolution);
      setResolved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(null);
    }
  };

  const createdAtDate =
    dlq.createdAt instanceof Date
      ? dlq.createdAt
      : typeof dlq.createdAt === "number"
        ? new Date(dlq.createdAt > 1e10 ? dlq.createdAt : dlq.createdAt * 1000)
        : null;

  if (resolved) {
    return (
      <div className="glass-card p-4 opacity-50">
        <div className="flex items-center gap-2 text-sm text-[color:var(--color-fg-muted)]">
          <Check className="size-4 text-emerald-400" strokeWidth={2.5} />
          <span className="font-mono text-xs">#{dlq.dlqId}</span>
          <span>—</span>
          <span className="capitalize">{resolvedWith?.replace("_", " ")}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-card p-4">
      <div className="flex items-start gap-4">
        <AlertTriangle
          className="size-5 text-[color:var(--color-champagne-400)] mt-0.5 shrink-0"
          strokeWidth={2}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="badge badge-needs-review text-[10px]">{dlq.errorClass}</span>
            <span className="text-xs text-[color:var(--color-fg-subtle)]">
              {sourceName ?? "—"} ·{" "}
              {createdAtDate ? createdAtDate.toLocaleString(locale) : "—"}
            </span>
          </div>
          <p className="text-sm text-[color:var(--color-fg)] mb-2">{dlq.errorMessage}</p>
          {dlq.rawRecord != null && (
            <details className="mt-2">
              <summary className="text-xs text-[color:var(--color-fg-muted)] cursor-pointer hover:text-[color:var(--color-primary)]">
                Raw record
              </summary>
              <pre className="mt-2 text-[10px] bg-[color:var(--color-noir-950)] p-3 rounded-md overflow-x-auto font-mono">
                {JSON.stringify(dlq.rawRecord, null, 2)}
              </pre>
            </details>
          )}
          {error && (
            <p className="mt-1 text-xs text-red-400">{error}</p>
          )}
        </div>
        <div className="flex flex-col gap-1.5 shrink-0">
          <button
            onClick={() => handleResolve("approved_manual")}
            disabled={loading !== null}
            className="btn btn-primary text-xs disabled:opacity-50"
          >
            <Check className="size-3.5" strokeWidth={3} />
            {loading === "approved_manual" ? "…" : labels.approve}
          </button>
          <button
            onClick={() => handleResolve("blacklisted")}
            disabled={loading !== null}
            className="btn btn-ghost text-xs disabled:opacity-50"
          >
            <Ban className="size-3.5" strokeWidth={2.5} />
            {loading === "blacklisted" ? "…" : labels.blacklist}
          </button>
          <button
            onClick={() => handleResolve("ignored")}
            disabled={loading !== null}
            className="btn btn-ghost text-xs disabled:opacity-50"
          >
            <EyeOff className="size-3.5" strokeWidth={2.5} />
            {loading === "ignored" ? "…" : labels.ignore}
          </button>
        </div>
      </div>
    </div>
  );
}
