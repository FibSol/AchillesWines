"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, AlertTriangle, KeyRound, ExternalLink, ChevronRight } from "lucide-react";

export interface AuthSourceRow {
  sourceKey: number;
  sourceCode: string;
  sourceName: string;
  sourceTier: string;
  baseUrl: string | null;
  enabled: boolean;
  hasCredentials: boolean;
  envUserVar: string;
  envPassVar: string;
}

interface AuthLabels {
  source: string;
  status: string;
  envVars: string;
  credsPresent: string;
  credsMissing: string;
  testLogin: string;
  testing: string;
  empty: string;
  jobQueued: string;
  viewJob: string;
  docsHint: string;
  docsLink: string;
}

export function AuthSourceList({
  rows,
  labels,
  locale,
}: {
  rows: AuthSourceRow[];
  labels: AuthLabels;
  locale: string;
}) {
  const [testing, setTesting] = useState<number | null>(null);
  const [results, setResults] = useState<Record<number, { ok: boolean; jobId?: string; msg?: string }>>({});

  async function testLogin(sourceKey: number) {
    setTesting(sourceKey);
    setResults((r) => {
      const next = { ...r };
      delete next[sourceKey];
      return next;
    });
    try {
      const r = await fetch("/api/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sourceKey, params: { test_auth: true } }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setResults((prev) => ({ ...prev, [sourceKey]: { ok: false, msg: String(j.error ?? r.statusText) } }));
        return;
      }
      const j = await r.json();
      setResults((prev) => ({ ...prev, [sourceKey]: { ok: true, jobId: j.jobId } }));
    } catch (e) {
      setResults((prev) => ({ ...prev, [sourceKey]: { ok: false, msg: String(e) } }));
    } finally {
      setTesting(null);
    }
  }

  if (rows.length === 0) {
    return (
      <div className="glass-card p-12 text-center">
        <KeyRound
          className="size-10 mx-auto mb-4 text-[color:var(--color-fg-subtle)]"
          strokeWidth={1.5}
        />
        <p className="text-[color:var(--color-fg-muted)]">{labels.empty}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-[color:var(--color-fg-subtle)]">
        {labels.docsHint}{" "}
        <a
          href="https://github.com/FibSol/AchillesWines/blob/main/docs/AUTH.md"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[color:var(--color-magenta-400)] hover:text-[color:var(--color-accent)] inline-flex items-center gap-1"
        >
          {labels.docsLink}
          <ExternalLink className="size-3" strokeWidth={2.5} />
        </a>
      </p>

      <div className="space-y-3">
        {rows.map((r) => {
          const result = results[r.sourceKey];
          return (
            <div key={r.sourceKey} className="glass-card p-5">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-semibold text-[color:var(--color-fg)]">
                      {r.sourceName}
                    </h3>
                    <span className="font-mono text-[10px] text-[color:var(--color-fg-subtle)] uppercase tracking-wider">
                      {r.sourceCode}
                    </span>
                    {!r.enabled && (
                      <span className="badge badge-needs-review text-[10px] py-0.5">disabled</span>
                    )}
                  </div>
                  {r.baseUrl && (
                    <a
                      href={r.baseUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)] inline-flex items-center gap-1 mt-0.5"
                    >
                      {r.baseUrl.replace(/^https?:\/\//, "")}
                      <ExternalLink className="size-3" strokeWidth={2.5} />
                    </a>
                  )}
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  {r.hasCredentials ? (
                    <span className="badge badge-verified text-xs">
                      <CheckCircle2 className="size-3" strokeWidth={2.5} />
                      {labels.credsPresent}
                    </span>
                  ) : (
                    <span className="badge badge-needs-review text-xs">
                      <AlertTriangle className="size-3" strokeWidth={2.5} />
                      {labels.credsMissing}
                    </span>
                  )}
                  <button
                    onClick={() => testLogin(r.sourceKey)}
                    disabled={!r.hasCredentials || testing === r.sourceKey}
                    className="btn btn-ghost text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                    title={!r.hasCredentials ? labels.credsMissing : labels.testLogin}
                  >
                    <KeyRound className="size-3.5" strokeWidth={2.5} />
                    {testing === r.sourceKey ? labels.testing : labels.testLogin}
                  </button>
                </div>
              </div>

              <details className="mt-3">
                <summary className="cursor-pointer text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                  {labels.envVars}
                </summary>
                <div className="mt-2 space-y-1 font-mono text-[11px] text-[color:var(--color-fg-muted)] bg-[rgba(9,8,15,0.5)] rounded p-2">
                  <p>{r.envUserVar}=…</p>
                  <p>{r.envPassVar}=…</p>
                </div>
              </details>

              {result && (
                <div
                  className={`mt-3 p-3 rounded-md text-xs ${
                    result.ok
                      ? "border border-[color:var(--color-success)] bg-[rgba(94,168,122,0.1)]"
                      : "border border-[color:var(--color-champagne-700)] bg-[rgba(165,56,96,0.08)]"
                  }`}
                >
                  {result.ok ? (
                    <div className="flex items-center justify-between">
                      <span className="text-[color:var(--color-success)]">
                        {labels.jobQueued}{" "}
                        <span className="font-mono text-[10px] text-[color:var(--color-fg-muted)]">
                          {result.jobId?.slice(-8)}
                        </span>
                      </span>
                      <Link
                        href={`/${locale}/admin/jobs`}
                        className="text-[color:var(--color-magenta-400)] hover:text-[color:var(--color-accent)] inline-flex items-center gap-1"
                      >
                        {labels.viewJob}
                        <ChevronRight className="size-3" strokeWidth={2.5} />
                      </Link>
                    </div>
                  ) : (
                    <p className="text-[color:var(--color-champagne-400)] font-mono">{result.msg}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
