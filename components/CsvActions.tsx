"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { Download, FileDown, Upload, X, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";

export interface CsvLabels {
  importBtn: string;
  exportBtn: string;
  templateBtn: string;
  importTitle: string;
  importing: string;
  close: string;
  resultAccepted: string;
  resultInserted: string;
  resultMerged: string;
  resultRejected: string;
  resultDetails: string;
  resultDone: string;
  uploadError: string;
}

export interface CsvEndpoints {
  /** GET endpoint that returns the current state as CSV. */
  export: string;
  /** GET endpoint that returns an example/template CSV. */
  template: string;
  /** POST endpoint that accepts text/csv and returns ImportResponse. */
  import: string;
}

interface ImportResponse {
  accepted: number;
  inserted: number;
  /** Updated/merged rows (label varies per resource: "merged" for cellar, "updated" for producers). */
  merged: number;
  rejected: number;
  rejections: { row: number; reason: string }[];
  totalRows: number;
}

/**
 * Generic CSV import/export/template trio. Used by /cellar (wineKey, location)
 * and /domaines (producer_norm, country_code). The dialog only appears once
 * there is something to show — clicking "Import CSV" opens the OS file picker
 * directly.
 */
export function CsvActions({
  endpoints,
  labels,
}: {
  endpoints: CsvEndpoints;
  labels: CsvLabels;
}) {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dialogOpen = busy || result !== null || error !== null;

  function closeDialog() {
    setResult(null);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const text = await file.text();
      const r = await fetch(endpoints.import, {
        method: "POST",
        headers: { "content-type": "text/csv; charset=utf-8" },
        body: text,
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setError(String(j.error ?? r.statusText));
        return;
      }
      const j: ImportResponse = await r.json();
      setResult(j);
      if (j.accepted > 0) router.refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <input
        ref={fileRef}
        type="file"
        accept=".csv,text/csv,application/vnd.ms-excel"
        className="sr-only"
        aria-hidden="true"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
        }}
      />

      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          className="btn btn-ghost text-xs disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Upload className="size-3.5" strokeWidth={2.5} />
          {busy ? labels.importing : labels.importBtn}
        </button>
        <a
          href={endpoints.export}
          download
          className="btn btn-ghost text-xs"
        >
          <Download className="size-3.5" strokeWidth={2.5} />
          {labels.exportBtn}
        </a>
        <a
          href={endpoints.template}
          download
          className="btn btn-ghost text-xs"
        >
          <FileDown className="size-3.5" strokeWidth={2.5} />
          {labels.templateBtn}
        </a>
      </div>

      <Dialog.Root open={dialogOpen} onOpenChange={(v) => !v && closeDialog()}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-[rgba(13,6,26,0.7)] backdrop-blur-sm z-40" />
          <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(560px,90vw)] max-h-[85vh] overflow-y-auto glass-card p-6">
            <div className="flex items-center justify-between mb-4">
              <Dialog.Title className="text-lg font-display text-[color:var(--color-fg)]">
                {labels.importTitle}
              </Dialog.Title>
              <Dialog.Close className="text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)]">
                <X className="size-4" />
              </Dialog.Close>
            </div>

            {busy && (
              <div className="flex items-center gap-3 p-4 text-sm text-[color:var(--color-fg-muted)]">
                <Loader2 className="size-4 animate-spin text-[color:var(--color-coral-400)]" strokeWidth={2.5} />
                {labels.importing}
              </div>
            )}

            {!busy && error && (
              <div className="space-y-3">
                <div className="flex items-start gap-2 p-3 rounded-md border border-[color:var(--color-coral-700)] bg-[rgba(255,92,138,0.1)]">
                  <AlertTriangle className="size-4 text-[color:var(--color-coral-400)] shrink-0 mt-0.5" />
                  <div className="text-sm">
                    <p className="font-semibold text-[color:var(--color-coral-400)]">{labels.uploadError}</p>
                    <p className="font-mono text-xs text-[color:var(--color-fg-muted)] mt-1">{error}</p>
                  </div>
                </div>
                <button type="button" onClick={closeDialog} className="btn btn-ghost text-xs">
                  {labels.close}
                </button>
              </div>
            )}

            {!busy && result && (
              <div className="space-y-4">
                <div className="flex items-start gap-2 p-3 rounded-md border border-[color:var(--color-mint-600)] bg-[rgba(111,255,233,0.08)]">
                  <CheckCircle2 className="size-5 text-[color:var(--color-mint-400)] shrink-0 mt-0.5" />
                  <div>
                    <p className="font-semibold text-[color:var(--color-mint-400)]">{labels.resultDone}</p>
                    <p className="text-xs text-[color:var(--color-fg-muted)] mt-1 font-mono">
                      {result.accepted}/{result.totalRows} {labels.resultAccepted}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="glass-card p-3">
                    <p className="text-2xl font-display text-[color:var(--color-mint-400)]">
                      {result.inserted}
                    </p>
                    <p className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                      {labels.resultInserted}
                    </p>
                  </div>
                  <div className="glass-card p-3">
                    <p className="text-2xl font-display text-[color:var(--color-coral-400)]">
                      {result.merged}
                    </p>
                    <p className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                      {labels.resultMerged}
                    </p>
                  </div>
                  <div className="glass-card p-3">
                    <p className="text-2xl font-display text-[color:var(--color-warning)]">
                      {result.rejected}
                    </p>
                    <p className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                      {labels.resultRejected}
                    </p>
                  </div>
                </div>

                {result.rejections.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)] mb-2">
                      {labels.resultDetails} ({result.rejections.length})
                    </summary>
                    <div className="max-h-48 overflow-y-auto space-y-1 font-mono text-[10px] bg-[rgba(13,6,26,0.5)] rounded p-2">
                      {result.rejections.map((r) => (
                        <p key={r.row} className="text-[color:var(--color-fg-muted)]">
                          <span className="text-[color:var(--color-warning)]">row {r.row}:</span>{" "}
                          {r.reason}
                        </p>
                      ))}
                    </div>
                  </details>
                )}

                <button type="button" onClick={closeDialog} className="btn btn-ghost text-xs">
                  {labels.close}
                </button>
              </div>
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
