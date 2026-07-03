"use client";

import { useEffect, useRef, useState } from "react";
import { Link } from "@/i18n/navigation";
import { JobLogsDrawer } from "@/components/JobLogsDrawer";

type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

interface Job {
  jobId: string;
  sourceKey: number | null;
  requestedBy: string;
  // Drizzle timestamp mode → Date serialized to ISO string in JSON
  requestedAt: string | number | null;
  status: JobStatus;
  startedAt: string | number | null;
  finishedAt: string | number | null;
  rowsFetched: number;
  rowsInserted: number;
  rowsDlq: number;
  errorMessage: string | null;
  batchId: string | null;
  params: Record<string, unknown> | null;
}

interface Source {
  sourceKey: number;
  sourceCode: string;
  sourceName: string;
  sourceTier: string;
  countryCode: string | null;
  cadence: string;
  requiresAuth: boolean;
  recommendedBatchSize: number | null;
  lastBenchmarkAt: number | null;
  benchmarkSuccessRate: number | null;
}

const STATUS_BADGE: Record<JobStatus, string> = {
  queued: "bg-slate-700 text-slate-200",
  running: "bg-blue-600 text-white animate-pulse",
  done: "bg-emerald-700 text-white",
  failed: "bg-red-700 text-white",
  cancelled: "bg-gray-600 text-gray-200",
};

function toDate(ts: string | number | null): Date | null {
  if (ts === null || ts === undefined) return null;
  if (typeof ts === "string") return new Date(ts);
  // Drizzle may return unix epoch (seconds) as a number
  return ts > 1e10 ? new Date(ts) : new Date(ts * 1000);
}

function formatDuration(startedAt: string | number | null, finishedAt: string | number | null): string {
  const start = toDate(startedAt);
  if (!start) return "—";
  const end = toDate(finishedAt) ?? new Date();
  const secs = Math.floor((end.getTime() - start.getTime()) / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  return `${mins}m ${secs % 60}s`;
}

function formatTs(ts: string | number | null): string {
  const d = toDate(ts);
  if (!d) return "—";
  return d.toLocaleString();
}

interface PromoteStats {
  pending: number;
  overlap: number;
  totalFactPrice: number;
}

export function JobsTable() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [draining, setDraining] = useState(false);
  const [drainMsg, setDrainMsg] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [promoteStats, setPromoteStats] = useState<PromoteStats | null>(null);
  const [promoteResult, setPromoteResult] = useState<{ promoted: number; pending: number; totalFactPrice: number } | null>(null);
  const [openLogsJob, setOpenLogsJob] = useState<Job | null>(null);
  const sourceRef = useRef<HTMLSelectElement>(null);
  const limitRef = useRef<HTMLInputElement>(null);

  const sourceByKey = new Map(sources.map((s) => [s.sourceKey, s]));
  const [selectedSourceKey, setSelectedSourceKey] = useState<number | null>(null);
  const selectedSource = selectedSourceKey ? sourceByKey.get(selectedSourceKey) : null;

  const fetchJobs = async () => {
    try {
      const res = await fetch("/api/jobs?limit=50");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setJobs(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  const fetchPromoteStats = async () => {
    fetch("/api/promote")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setPromoteStats(j))
      .catch(() => {});
  };

  useEffect(() => {
    fetchJobs();
    const id = setInterval(fetchJobs, 5000);
    // Sources rarely change — fetch once on mount.
    fetch("/api/sources")
      .then((r) => (r.ok ? r.json() : { sources: [] }))
      .then((j: { sources: Source[] }) => setSources(j.sources ?? []))
      .catch(() => setSources([]));
    fetchPromoteStats();
    return () => clearInterval(id);
  }, []);

  const handleSourceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const key = parseInt(e.target.value ?? "0") || null;
    setSelectedSourceKey(key);
    if (limitRef.current && key) {
      const src = sourceByKey.get(key);
      if (src?.recommendedBatchSize) {
        limitRef.current.value = String(src.recommendedBatchSize);
      }
    }
  };

  const handleLaunch = async () => {
    const sourceKey = parseInt(sourceRef.current?.value ?? "0");
    const limit = parseInt(limitRef.current?.value ?? "100");
    if (!sourceKey) return;
    setLaunching(true);
    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sourceKey, params: { limit } }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to launch job");
    } finally {
      setLaunching(false);
    }
  };

  const handleDrain = async () => {
    setDraining(true);
    setDrainMsg(null);
    try {
      const res = await fetch("/api/worker/run", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setDrainMsg(data.error ?? data.reason ?? `HTTP ${res.status}`);
      } else {
        setDrainMsg(`File en cours de traitement (pid ${data.pid})`);
        await fetchJobs();
      }
    } catch (e) {
      setDrainMsg(e instanceof Error ? e.message : "Échec du démarrage");
    } finally {
      setDraining(false);
    }
  };

  const handlePromote = async () => {
    setPromoting(true);
    setPromoteResult(null);
    try {
      const res = await fetch("/api/promote", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPromoteResult(data);
      await fetchPromoteStats();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run promoter");
    } finally {
      setPromoting(false);
    }
  };

  const handleCancel = async (jobId: string) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? `HTTP ${res.status}`);
        return;
      }
      await fetchJobs();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to cancel job");
    }
  };

  return (
    <div className="space-y-8">
      {/* Launch panel */}
      <div className="glass-card p-6">
        <h2 className="text-lg font-semibold mb-4 text-[color:var(--color-fg)]">
          Lancer un scraper
        </h2>
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-[color:var(--color-fg-muted)]">Source</label>
            <select
              ref={sourceRef}
              onChange={handleSourceChange}
              className="rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-fill-subtle)] px-3 py-2 text-sm text-[color:var(--color-fg)] focus:outline-none focus:ring-2 focus:ring-[color:var(--color-primary)] min-w-[16rem] [&>option]:bg-white [&>option]:text-gray-900"
              disabled={sources.length === 0}
            >
              <option value="">
                {sources.length === 0 ? "Chargement des sources…" : "Sélectionner source"}
              </option>
              {sources.map((s) => (
                <option key={s.sourceKey} value={s.sourceKey}>
                  {s.sourceName}
                  {s.countryCode ? ` (${s.countryCode})` : ""}
                  {s.requiresAuth ? " 🔑" : ""}
                  {s.recommendedBatchSize ? ` · rec=${s.recommendedBatchSize}` : ""}
                </option>
              ))}
            </select>
            {selectedSource?.recommendedBatchSize && (
              <div className="mt-1 text-xs text-[color:var(--color-accent)]">
                Recommended: {selectedSource.recommendedBatchSize}
                {selectedSource.benchmarkSuccessRate != null
                  ? ` · ${Math.round(selectedSource.benchmarkSuccessRate * 100)}% success rate`
                  : ""}
              </div>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-[color:var(--color-fg-muted)]">Limite</label>
            <input
              ref={limitRef}
              type="number"
              defaultValue={100}
              min={1}
              className="w-24 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-fill-subtle)] px-3 py-2 text-sm text-[color:var(--color-fg)] focus:outline-none focus:ring-2 focus:ring-[color:var(--color-primary)]"
            />
          </div>
          <button
            onClick={handleLaunch}
            disabled={launching}
            className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--color-primary)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {launching ? "…" : "🚀 Lancer"}
          </button>
          <div className="ml-auto flex flex-col items-end gap-1">
            <button
              onClick={handleDrain}
              disabled={draining}
              title="Démarre le worker pour traiter immédiatement les jobs en attente"
              className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-fill-subtle)] px-4 py-2 text-sm font-semibold text-[color:var(--color-fg)] transition-colors hover:bg-[color:var(--color-fill)] disabled:opacity-50"
            >
              {draining ? "…" : "⚙️ Traiter la file maintenant"}
            </button>
            {drainMsg && (
              <span className="text-xs text-[color:var(--color-fg-muted)] max-w-[18rem] text-right">
                {drainMsg}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Promote panel */}
      <div className="glass-card p-6">
        <h2 className="text-lg font-semibold mb-4 text-[color:var(--color-fg)]">
          Promoteur de prix
        </h2>
        <div className="flex flex-wrap items-center gap-6">
          {promoteStats && (
            <div className="flex gap-4 text-sm">
              <span className="text-[color:var(--color-fg-muted)]">
                En attente: <strong className="text-[color:var(--color-fg)]">{promoteStats.pending.toLocaleString()}</strong>
              </span>
              <span className="text-[color:var(--color-fg-muted)]">
                Overlap (≥2 sources): <strong className="text-[color:var(--color-accent)]">{promoteStats.overlap.toLocaleString()}</strong>
              </span>
              <span className="text-[color:var(--color-fg-muted)]">
                fact_price: <strong className="text-[color:var(--color-fg)]">{promoteStats.totalFactPrice.toLocaleString()}</strong>
              </span>
            </div>
          )}
          <button
            onClick={handlePromote}
            disabled={promoting}
            className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--color-accent)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {promoting ? "…" : "✨ Promouvoir"}
          </button>
          {promoteResult && (
            <div className="text-sm text-[color:var(--color-fg-muted)]">
              <span className="text-emerald-400 font-semibold">+{promoteResult.promoted}</span> promus
              {" · "}{promoteResult.pending.toLocaleString()} en attente
              {" · "}{promoteResult.totalFactPrice.toLocaleString()} total fact_price
            </div>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-700 bg-red-950/30 p-4 text-sm text-red-300 flex items-center justify-between">
          <span>{error}</span>
          <button
            onClick={() => { setError(null); fetchJobs(); }}
            className="ml-4 text-xs underline opacity-70 hover:opacity-100"
          >
            Réessayer
          </button>
        </div>
      )}

      {/* Jobs table */}
      <div className="glass-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-[color:var(--color-fg-subtle)] border-b border-[color:var(--color-border)]">
            <tr>
              <th className="text-left p-3">ID</th>
              <th className="text-left p-3">Source</th>
              <th className="text-left p-3">Statut</th>
              <th className="text-left p-3">Demandé à</th>
              <th className="text-right p-3">Durée</th>
              <th className="text-right p-3">Fetched</th>
              <th className="text-right p-3">Inserted</th>
              <th className="text-right p-3">DLQ</th>
              <th className="text-left p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-t border-[color:var(--color-border)] animate-pulse">
                  {Array.from({ length: 9 }).map((_, j) => (
                    <td key={j} className="p-3">
                      <div className="h-4 rounded bg-[color:var(--color-fill-subtle)]" />
                    </td>
                  ))}
                </tr>
              ))
            ) : jobs.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-[color:var(--color-fg-muted)]">
                  Aucun job
                </td>
              </tr>
            ) : (
              jobs.map((job) => {
                const isInspectable = job.status === "running" || job.status === "done" || job.status === "failed";
                return (
                <tr
                  key={job.jobId}
                  onClick={() => isInspectable && setOpenLogsJob(job)}
                  className={`border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-fill-subtle)] transition-colors ${
                    isInspectable ? "cursor-pointer" : ""
                  }`}
                  title={isInspectable ? "Click to view logs" : undefined}
                >
                  <td className="p-3 font-mono text-xs text-[color:var(--color-fg-muted)]">
                    {job.jobId.slice(-8)}
                  </td>
                  <td className="p-3 text-[color:var(--color-fg)]">
                    {job.sourceKey
                      ? (sourceByKey.get(job.sourceKey)?.sourceCode ?? `source_${job.sourceKey}`)
                      : "—"}
                  </td>
                  <td className="p-3">
                    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[job.status]}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="p-3 text-xs text-[color:var(--color-fg-muted)]">
                    {formatTs(job.requestedAt)}
                  </td>
                  <td className="p-3 text-right text-xs text-[color:var(--color-fg-muted)]">
                    {formatDuration(job.startedAt, job.finishedAt)}
                  </td>
                  <td className="p-3 text-right">{job.rowsFetched}</td>
                  <td className="p-3 text-right text-[color:var(--color-accent)]">{job.rowsInserted}</td>
                  <td className="p-3 text-right">
                    {job.rowsDlq > 0 ? (
                      <Link
                        href={`/qualite?batch_id=${job.batchId ?? ""}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-[color:var(--color-warning)] underline hover:opacity-80"
                      >
                        {job.rowsDlq}
                      </Link>
                    ) : (
                      <span className="text-[color:var(--color-fg-subtle)]">0</span>
                    )}
                  </td>
                  <td className="p-3">
                    {job.status === "queued" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancel(job.jobId);
                        }}
                        className="rounded px-2 py-1 text-xs font-medium bg-[color:var(--color-fill-subtle)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] hover:bg-[color:var(--color-fill)] transition-colors"
                      >
                        ✋ Annuler
                      </button>
                    )}
                    {job.status === "failed" && job.errorMessage && (
                      <span
                        title={job.errorMessage}
                        className="text-xs text-red-400 cursor-help truncate max-w-[120px] inline-block"
                      >
                        {job.errorMessage.slice(0, 30)}…
                      </span>
                    )}
                  </td>
                </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <JobLogsDrawer
        jobId={openLogsJob?.jobId ?? null}
        jobStatus={openLogsJob?.status ?? null}
        sourceCode={
          openLogsJob?.sourceKey
            ? (sourceByKey.get(openLogsJob.sourceKey)?.sourceCode ?? null)
            : null
        }
        onClose={() => setOpenLogsJob(null)}
      />
    </div>
  );
}
