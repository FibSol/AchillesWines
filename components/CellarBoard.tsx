"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { Plus, X, Wine, Warehouse, Search, GlassWater } from "lucide-react";

export interface CellarLocationRow {
  locationId: number;
  name: string;
  capacity: number;
}

export interface CellarBottleRow {
  inventoryId: number;
  wineKey: string;
  locationId: number;
  qty: number;
  cuveeName: string;
  producerName: string;
  vintage: number | null;
  color: string;
}

export interface CellarLabels {
  addBottle: string;
  consume: string;
  move: string;
  qty: string;
  wine: string;
  location: string;
  search: string;
  noResults: string;
  cancel: string;
  save: string;
  capacityFull: string;
  capacityExceeded: string;
  personalScore: string;
  occasion: string;
  tastingNote: string;
  consumed: string;
  moved: string;
  empty: string;
  dragHint: string;
}

interface WineSearchResult {
  wineKey: string;
  canonicalName: string;
  cuveeName: string;
  vintage: number | null;
  color: string;
  producerName: string;
  appellationName: string;
}

const COLOR_DOT: Record<string, string> = {
  red: "#b71f55",
  white: "#FFD166",
  "rosé": "#FF89A6",
  sparkling: "#8EFEED",
  sweet: "#FFB3C8",
  fortified: "#553987",
  orange: "#FF5C8A",
};

interface Props {
  locations: CellarLocationRow[];
  bottles: CellarBottleRow[];
  labels: CellarLabels;
}

export function CellarBoard({ locations, bottles, labels }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dropTarget, setDropTarget] = useState<number | null>(null);
  const [addOpenForLocation, setAddOpenForLocation] = useState<number | null>(null);
  const [consumeBottle, setConsumeBottle] = useState<CellarBottleRow | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const bottlesByLoc = new Map<number, CellarBottleRow[]>();
  for (const b of bottles) {
    const arr = bottlesByLoc.get(b.locationId) ?? [];
    arr.push(b);
    bottlesByLoc.set(b.locationId, arr);
  }

  function refresh() {
    startTransition(() => router.refresh());
  }

  async function moveInventory(inventoryId: number, toLocationId: number) {
    setErrorMsg(null);
    try {
      const r = await fetch(`/api/cellar/inventory/${inventoryId}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ locationId: toLocationId }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        if (j.error === "capacity_exceeded") {
          setErrorMsg(labels.capacityExceeded);
        } else {
          setErrorMsg(String(j.error ?? r.statusText));
        }
        return;
      }
      refresh();
    } catch (e) {
      setErrorMsg(String(e));
    }
  }

  return (
    <div>
      {errorMsg && (
        <div className="mb-4 p-3 rounded-md border border-[color:var(--color-coral-700)] bg-[rgba(255,92,138,0.1)] text-sm text-[color:var(--color-coral-400)]">
          {errorMsg}
        </div>
      )}
      <p className="text-xs text-[color:var(--color-fg-subtle)] mb-4 italic">{labels.dragHint}</p>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {locations.map((loc) => {
          const cellBottles = bottlesByLoc.get(loc.locationId) ?? [];
          const used = cellBottles.reduce((a, b) => a + b.qty, 0);
          const pct = Math.min(100, Math.round((used / loc.capacity) * 100));
          const isDropTarget = dropTarget === loc.locationId;
          const isFull = used >= loc.capacity;

          return (
            <div
              key={loc.locationId}
              onDragOver={(e) => {
                if (draggingId === null) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                if (dropTarget !== loc.locationId) setDropTarget(loc.locationId);
              }}
              onDragLeave={() => {
                if (dropTarget === loc.locationId) setDropTarget(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                const idStr = e.dataTransfer.getData("text/inventory-id");
                const invId = Number.parseInt(idStr, 10);
                setDropTarget(null);
                setDraggingId(null);
                if (Number.isFinite(invId)) {
                  const src = bottles.find((b) => b.inventoryId === invId);
                  if (src && src.locationId !== loc.locationId) {
                    moveInventory(invId, loc.locationId);
                  }
                }
              }}
              className={`glass-card p-3 relative overflow-hidden min-h-[140px] flex flex-col ${
                isDropTarget ? "ring-2 ring-[color:var(--color-coral-400)]" : ""
              }`}
            >
              <div
                className="absolute inset-0 opacity-25 pointer-events-none"
                style={{
                  background: `linear-gradient(to top, var(--color-coral-700) 0%, var(--color-coral-700) ${pct}%, transparent ${pct}%)`,
                }}
                aria-hidden
              />
              <div className="relative flex-1 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5">
                    <Warehouse className="size-3 text-[color:var(--color-fg-subtle)]" strokeWidth={2} />
                    <span className="font-mono text-[10px] text-[color:var(--color-fg-subtle)]">
                      #{String(loc.locationId).padStart(2, "0")}
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-[color:var(--color-fg-muted)]">
                    {used}/{loc.capacity}
                  </span>
                </div>

                <div className="space-y-1 flex-1 overflow-y-auto max-h-32 pr-1">
                  {cellBottles.length === 0 ? (
                    <p className="text-[10px] text-[color:var(--color-fg-subtle)] italic">
                      {labels.empty}
                    </p>
                  ) : (
                    cellBottles.map((b) => (
                      <div
                        key={b.inventoryId}
                        draggable
                        onDragStart={(e) => {
                          setDraggingId(b.inventoryId);
                          e.dataTransfer.setData("text/inventory-id", String(b.inventoryId));
                          e.dataTransfer.effectAllowed = "move";
                        }}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDropTarget(null);
                        }}
                        onClick={() => setConsumeBottle(b)}
                        className={`group cursor-grab active:cursor-grabbing rounded px-1.5 py-1 bg-[rgba(255,92,138,0.07)] hover:bg-[rgba(255,92,138,0.18)] transition ${
                          draggingId === b.inventoryId ? "opacity-40" : ""
                        }`}
                        title={`${b.producerName} · ${b.cuveeName}`}
                      >
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span
                            className="inline-block size-1.5 rounded-full shrink-0"
                            style={{ background: COLOR_DOT[b.color] ?? "#FAF7F5" }}
                            aria-label={b.color}
                          />
                          <span className="text-[10px] font-mono text-[color:var(--color-coral-400)] shrink-0">
                            ×{b.qty}
                          </span>
                          <span className="text-[10px] text-[color:var(--color-fg)] truncate">
                            {b.cuveeName}
                            {b.vintage && (
                              <span className="ml-1 text-[color:var(--color-fg-muted)]">{b.vintage}</span>
                            )}
                          </span>
                        </div>
                      </div>
                    ))
                  )}
                </div>

                <button
                  onClick={() => setAddOpenForLocation(loc.locationId)}
                  disabled={isFull}
                  className="mt-2 w-full text-[10px] py-1 rounded border border-[color:var(--color-border)] hover:border-[color:var(--color-coral-400)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)] disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center gap-1 transition"
                >
                  <Plus className="size-3" strokeWidth={2.5} />
                  {isFull ? labels.capacityFull : labels.addBottle}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <AddBottleDialog
        open={addOpenForLocation !== null}
        locationId={addOpenForLocation}
        locations={locations}
        labels={labels}
        onClose={() => setAddOpenForLocation(null)}
        onSuccess={() => {
          setAddOpenForLocation(null);
          refresh();
        }}
      />

      <ConsumeDialog
        bottle={consumeBottle}
        locations={locations}
        labels={labels}
        onClose={() => setConsumeBottle(null)}
        onSuccess={() => {
          setConsumeBottle(null);
          refresh();
        }}
      />

      {isPending && (
        <div className="fixed bottom-4 right-4 text-xs text-[color:var(--color-fg-muted)] font-mono">
          …
        </div>
      )}
    </div>
  );
}

function AddBottleDialog({
  open,
  locationId,
  locations,
  labels,
  onClose,
  onSuccess,
}: {
  open: boolean;
  locationId: number | null;
  locations: CellarLocationRow[];
  labels: CellarLabels;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<WineSearchResult[]>([]);
  const [picked, setPicked] = useState<WineSearchResult | null>(null);
  const [qty, setQty] = useState(1);
  const [pickedLocationId, setPickedLocationId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    setPicked(null);
    setQty(1);
    setPickedLocationId(locationId);
    setErr(null);
  }, [open, locationId]);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        const r = await fetch(
          `/api/cellar/wines?q=${encodeURIComponent(query)}&limit=20`,
          { signal: ctrl.signal },
        );
        if (r.ok) {
          const j = await r.json();
          setResults(j.wines ?? []);
        }
      } catch {
        /* ignore aborts */
      }
    }, 180);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, open]);

  async function submit() {
    if (!picked || !pickedLocationId) return;
    setSubmitting(true);
    setErr(null);
    try {
      const r = await fetch("/api/cellar/inventory", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ wineKey: picked.wineKey, locationId: pickedLocationId, qty }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setErr(j.error === "capacity_exceeded" ? labels.capacityExceeded : String(j.error ?? r.statusText));
        return;
      }
      onSuccess();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-[rgba(13,6,26,0.7)] backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(560px,90vw)] max-h-[85vh] overflow-hidden glass-card p-6 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <Dialog.Title className="text-lg font-display text-[color:var(--color-fg)]">
              {labels.addBottle}
            </Dialog.Title>
            <Dialog.Close className="text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)]">
              <X className="size-4" />
            </Dialog.Close>
          </div>

          <div className="space-y-3">
            <div>
              <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                {labels.wine}
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[color:var(--color-fg-subtle)]" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder={labels.search}
                  className="w-full pl-9 pr-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
                />
              </div>
            </div>

            <div className="max-h-48 overflow-y-auto rounded-md border border-[color:var(--color-border)] bg-[rgba(13,6,26,0.4)]">
              {results.length === 0 ? (
                <p className="px-3 py-2 text-xs text-[color:var(--color-fg-subtle)] italic">
                  {labels.noResults}
                </p>
              ) : (
                results.map((w) => (
                  <button
                    key={w.wineKey}
                    onClick={() => setPicked(w)}
                    className={`block w-full text-left px-3 py-2 text-xs border-b border-[color:var(--color-border)] last:border-b-0 hover:bg-[rgba(255,92,138,0.08)] ${
                      picked?.wineKey === w.wineKey ? "bg-[rgba(255,92,138,0.12)]" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block size-2 rounded-full shrink-0"
                        style={{ background: COLOR_DOT[w.color] ?? "#FAF7F5" }}
                      />
                      <span className="font-semibold text-[color:var(--color-fg)]">{w.producerName}</span>
                      <span className="text-[color:var(--color-coral-400)]">{w.cuveeName}</span>
                      {w.vintage && (
                        <span className="font-mono text-[color:var(--color-fg-muted)]">{w.vintage}</span>
                      )}
                    </div>
                    <p className="text-[10px] text-[color:var(--color-fg-subtle)] mt-0.5 ml-4">
                      {w.appellationName}
                    </p>
                  </button>
                ))
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {labels.qty}
                </label>
                <input
                  type="number"
                  min={1}
                  value={qty}
                  onChange={(e) => setQty(Math.max(1, Number.parseInt(e.target.value, 10) || 1))}
                  className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {labels.location}
                </label>
                <select
                  value={pickedLocationId ?? ""}
                  onChange={(e) => setPickedLocationId(Number.parseInt(e.target.value, 10))}
                  className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
                >
                  {locations.map((l) => (
                    <option key={l.locationId} value={l.locationId}>
                      #{String(l.locationId).padStart(2, "0")} — {l.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {err && (
              <p className="text-xs text-[color:var(--color-coral-400)] font-mono">{err}</p>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={onClose}
                className="btn btn-ghost text-xs"
                disabled={submitting}
              >
                {labels.cancel}
              </button>
              <button
                onClick={submit}
                disabled={!picked || !pickedLocationId || submitting}
                className="btn btn-primary text-xs disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Wine className="size-3.5" strokeWidth={2.5} />
                {labels.save}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ConsumeDialog({
  bottle,
  locations,
  labels,
  onClose,
  onSuccess,
}: {
  bottle: CellarBottleRow | null;
  locations: CellarLocationRow[];
  labels: CellarLabels;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [mode, setMode] = useState<"consume" | "move">("consume");
  const [qty, setQty] = useState(1);
  const [score, setScore] = useState<string>("");
  const [occasion, setOccasion] = useState("");
  const [note, setNote] = useState("");
  const [moveTo, setMoveTo] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!bottle) return;
    setMode("consume");
    setQty(1);
    setScore("");
    setOccasion("");
    setNote("");
    setMoveTo(bottle.locationId);
    setErr(null);
  }, [bottle]);

  async function submit() {
    if (!bottle) return;
    setSubmitting(true);
    setErr(null);
    try {
      if (mode === "consume") {
        const r = await fetch("/api/cellar/consume", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            inventoryId: bottle.inventoryId,
            qty,
            personalScore: score ? Number.parseInt(score, 10) : undefined,
            occasion: occasion || undefined,
            tastingNote: note || undefined,
          }),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          setErr(String(j.error ?? r.statusText));
          return;
        }
      } else {
        if (moveTo === null || moveTo === bottle.locationId) {
          onClose();
          return;
        }
        const r = await fetch(`/api/cellar/inventory/${bottle.inventoryId}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ locationId: moveTo }),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          setErr(j.error === "capacity_exceeded" ? labels.capacityExceeded : String(j.error ?? r.statusText));
          return;
        }
      }
      onSuccess();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog.Root open={bottle !== null} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-[rgba(13,6,26,0.7)] backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(480px,90vw)] glass-card p-6">
          <div className="flex items-center justify-between mb-3">
            <Dialog.Title className="text-base font-display text-[color:var(--color-fg)]">
              {bottle?.producerName} ·{" "}
              <span className="text-[color:var(--color-coral-400)]">{bottle?.cuveeName}</span>
              {bottle?.vintage && (
                <span className="ml-2 font-mono text-sm text-[color:var(--color-fg-muted)]">
                  {bottle.vintage}
                </span>
              )}
            </Dialog.Title>
            <Dialog.Close className="text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-coral-400)]">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <p className="text-xs text-[color:var(--color-fg-subtle)] mb-4">
            {labels.qty}: <span className="font-mono">{bottle?.qty}</span>
          </p>

          <div className="flex items-center gap-2 mb-4 p-1 rounded-md border border-[color:var(--color-border)] bg-[rgba(13,6,26,0.4)]">
            <button
              onClick={() => setMode("consume")}
              className={`flex-1 text-xs py-1.5 rounded ${
                mode === "consume"
                  ? "bg-[color:var(--color-coral-700)] text-[color:var(--color-ivory-100)]"
                  : "text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]"
              }`}
            >
              <GlassWater className="inline size-3.5 mr-1.5" strokeWidth={2.5} />
              {labels.consume}
            </button>
            <button
              onClick={() => setMode("move")}
              className={`flex-1 text-xs py-1.5 rounded ${
                mode === "move"
                  ? "bg-[color:var(--color-coral-700)] text-[color:var(--color-ivory-100)]"
                  : "text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]"
              }`}
            >
              <Warehouse className="inline size-3.5 mr-1.5" strokeWidth={2.5} />
              {labels.move}
            </button>
          </div>

          {mode === "consume" ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                    {labels.qty}
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={bottle?.qty ?? 1}
                    value={qty}
                    onChange={(e) =>
                      setQty(Math.max(1, Math.min(bottle?.qty ?? 1, Number.parseInt(e.target.value, 10) || 1)))
                    }
                    className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
                  />
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                    {labels.personalScore}
                  </label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={score}
                    onChange={(e) => setScore(e.target.value)}
                    placeholder="0–100"
                    className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {labels.occasion}
                </label>
                <input
                  type="text"
                  value={occasion}
                  onChange={(e) => setOccasion(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {labels.tastingNote}
                </label>
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)] resize-none"
                />
              </div>
            </div>
          ) : (
            <div>
              <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                {labels.location}
              </label>
              <select
                value={moveTo ?? ""}
                onChange={(e) => setMoveTo(Number.parseInt(e.target.value, 10))}
                className="w-full px-3 py-2 rounded-md bg-[rgba(13,6,26,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-coral-400)]"
              >
                {locations.map((l) => (
                  <option key={l.locationId} value={l.locationId}>
                    #{String(l.locationId).padStart(2, "0")} — {l.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {err && (
            <p className="text-xs text-[color:var(--color-coral-400)] font-mono mt-3">{err}</p>
          )}

          <div className="flex items-center justify-end gap-2 mt-5">
            <button onClick={onClose} className="btn btn-ghost text-xs" disabled={submitting}>
              {labels.cancel}
            </button>
            <button
              onClick={submit}
              disabled={submitting}
              className="btn btn-primary text-xs disabled:opacity-40"
            >
              {labels.save}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
