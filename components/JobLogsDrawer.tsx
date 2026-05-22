"use client";

import { useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X, ScrollText, RefreshCw } from "lucide-react";

interface LogsResponse {
  lines: string[];
  batchId: string | null;
  status: string;
  available: boolean;
}

interface Props {
  jobId: string | null;
  jobStatus: string | null;
  sourceCode: string | null;
  onClose: () => void;
}

export function JobLogsDrawer({ jobId, jobStatus, sourceCode, onClose }: Props) {
  const [data, setData] = useState<LogsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const open = jobId !== null;

  useEffect(() => {
    if (!open || !jobId) return;
    let cancelled = false;

    const fetchLogs = async () => {
      try {
        setLoading(true);
        const r = await fetch(`/api/jobs/${jobId}/logs?lines=100`);
        if (cancelled) return;
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          setError(String(j.error ?? r.statusText));
          return;
        }
        const j: LogsResponse = await r.json();
        setData(j);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchLogs();
    if (autoRefresh && jobStatus === "running") {
      const id = setInterval(fetchLogs, 3000);
      return () => {
        cancelled = true;
        clearInterval(id);
      };
    }
    return () => {
      cancelled = true;
    };
  }, [jobId, jobStatus, open, autoRefresh]);

  useEffect(() => {
    // Reset when drawer closes
    if (!open) {
      setData(null);
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    // Auto-scroll to bottom on new content
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [data?.lines.length]);

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-[rgba(13,6,26,0.6)] backdrop-blur-sm z-40" />
        <Dialog.Content
          className="fixed top-0 right-0 bottom-0 z-50 w-[min(720px,92vw)] glass-card border-l border-[color:var(--color-border)] flex flex-col"
          style={{ borderRadius: 0 }}
        >
          <div className="flex items-center justify-between p-4 border-b border-[color:var(--color-border)]">
            <div className="flex items-center gap-3 min-w-0">
              <ScrollText className="size-4 text-[color:var(--color-coral-400)] shrink-0" strokeWidth={2.5} />
              <div className="min-w-0">
                <Dialog.Title className="font-display text-base text-[color:var(--color-fg)] truncate">
                  {sourceCode ?? "scraper"} · <span className="font-mono text-sm text-[color:var(--color-fg-muted)]">{jobId?.slice(-8)}</span>
                </Dialog.Title>
                <p className="text-[10px] uppercase tracking-[0.08em] text-[color:var(--color-fg-subtle)] mt-0.5">
                  {data?.batchId ? `batch ${data.batchId.slice(0, 12)}…` : "no batch id"}
                  {" · "}
                  <span
                    className={
                      jobStatus === "running"
                        ? "text-[color:var(--color-mint-400)]"
                        : jobStatus === "failed"
                          ? "text-[color:var(--color-coral-400)]"
                          : "text-[color:var(--color-fg-muted)]"
                    }
                  >
                    {jobStatus}
                  </span>
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <label className="flex items-center gap-1.5 text-[10px] text-[color:var(--color-fg-muted)] cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh(e.target.checked)}
                  className="size-3 accent-[color:var(--color-coral-500)]"
                />
                auto-refresh
              </label>
              {loading && (
                <RefreshCw className="size-3 text-[color:var(--color-fg-subtle)] animate-spin" strokeWidth={2.5} />
              )}
              <Dialog.Close className="text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)]">
                <X className="size-4" />
              </Dialog.Close>
            </div>
          </div>

          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto font-mono text-[11px] leading-relaxed p-4 bg-[rgba(13,6,26,0.7)]"
          >
            {error && (
              <p className="text-[color:var(--color-coral-400)]">error: {error}</p>
            )}
            {!error && data && data.lines.length === 0 && (
              <p className="text-[color:var(--color-fg-subtle)] italic">
                {data.batchId
                  ? "No log file yet for this batch (logs/" + data.batchId + ".log). Check that the runner writes per-batch logs."
                  : "No batch_id assigned yet — job hasn't claimed work."}
              </p>
            )}
            {data?.lines.map((line, i) => (
              <div
                key={i}
                className={
                  /\b(error|fail|exception|traceback)\b/i.test(line)
                    ? "text-[color:var(--color-coral-400)]"
                    : /\b(warn|warning|retry)\b/i.test(line)
                      ? "text-[color:var(--color-warning)]"
                      : /\b(ok|success|done|inserted|promoted)\b/i.test(line)
                        ? "text-[color:var(--color-mint-400)]"
                        : "text-[color:var(--color-fg-muted)]"
                }
              >
                {line || " "}
              </div>
            ))}
          </div>

          <div className="px-4 py-2 border-t border-[color:var(--color-border)] text-[10px] text-[color:var(--color-fg-subtle)] font-mono flex items-center justify-between">
            <span>{data ? `${data.lines.length} lines (tail)` : "—"}</span>
            <span>logs/{data?.batchId ?? "—"}.log</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
