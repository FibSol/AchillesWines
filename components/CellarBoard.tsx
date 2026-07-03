"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { Camera, CheckCircle2, Loader2, Plus, X, Wine, Warehouse, Search, GlassWater, Star, Euro, Info, Grape, Percent, MapPin } from "lucide-react";

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
  purchasePriceEur: number | null;
  purchaseDate: Date | null;
  purchaseSource: string | null;
  // Hover ID-card fields
  appellationName: string;
  region: string;
  primaryVariety: string | null;
  alcoholPct: number | null;
  avgRating: number | null;
  avgPriceEur: number | null;
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
  ocrScan: string;
  ocrScanning: string;
  ocrError: string;
  editDetails: string;
  purchasePrice: string;
  purchaseDate: string;
  purchaseSource: string;
  marketPrice: string;
  criticScore: string;
  noRatings: string;
  noPrices: string;
  saved: string;
  // Filter bar
  filterSearch: string;
  filterAllColors: string;
  filterAllRegions: string;
  filterVintageFrom: string;
  filterVintageTo: string;
  filterReset: string;
  filterResultsSuffix: string;
  colorLabels: Record<string, string>;
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

interface WineDetails {
  ratings: Array<{ criticCode: string; score: number; scale: string }>;
  prices: Array<{ amountEur: number | null; retailer: string | null; priceKind: string; inStock: boolean | null }>;
  avgPrice: number | null;
}

const COLOR_DOT: Record<string, string> = {
  red: "#A53860",
  white: "#E5B25D",
  "rosé": "#E07898",
  sparkling: "#F5D08C",
  sweet: "#EDC072",
  fortified: "#6E1F3D",
  orange: "#C99440",
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
  // HTML5 drag-and-drop only works with a fine pointer (mouse). On touch devices
  // a `draggable` element swallows the tap, so the chip would feel "disabled".
  // Enable drag only on fine-pointer devices; touch users move bottles via the dialog.
  const [dragEnabled, setDragEnabled] = useState(false);
  useEffect(() => {
    setDragEnabled(window.matchMedia("(hover: hover) and (pointer: fine)").matches);
  }, []);
  // Hover "ID card": which bottle, anchored to its chip's screen rect.
  const [hover, setHover] = useState<{ bottle: CellarBottleRow; rect: DOMRect } | null>(null);

  // ── Filter state ──────────────────────────────────────────────────────────
  const [search, setSearch] = useState("");
  const [colorFilter, setColorFilter] = useState<string | null>(null);
  const [regionFilter, setRegionFilter] = useState("");
  const [vintageFrom, setVintageFrom] = useState("");
  const [vintageTo, setVintageTo] = useState("");

  // Derived filter options (computed once from the full bottle list)
  const allColors = [...new Set(bottles.map((b) => b.color))].sort();
  const allRegions = [...new Set(bottles.map((b) => b.region).filter(Boolean))].sort();
  const vintageMin = Math.min(...bottles.map((b) => b.vintage ?? 9999).filter((v) => v < 9999));
  const vintageMax = Math.max(...bottles.map((b) => b.vintage ?? 0));

  const isFiltered = !!(search || colorFilter || regionFilter || vintageFrom || vintageTo);

  const filteredBottles = isFiltered
    ? bottles.filter((b) => {
        if (colorFilter && b.color !== colorFilter) return false;
        if (regionFilter && b.region !== regionFilter) return false;
        if (vintageFrom) {
          if (b.vintage === null || b.vintage < Number.parseInt(vintageFrom, 10)) return false;
        }
        if (vintageTo) {
          if (b.vintage === null || b.vintage > Number.parseInt(vintageTo, 10)) return false;
        }
        if (search) {
          const q = search.toLowerCase();
          if (
            !b.producerName.toLowerCase().includes(q) &&
            !b.cuveeName.toLowerCase().includes(q) &&
            !(b.appellationName ?? "").toLowerCase().includes(q)
          )
            return false;
        }
        return true;
      })
    : bottles;

  const visibleBottleCount = filteredBottles.reduce((a, b) => a + b.qty, 0);

  const bottlesByLoc = new Map<number, CellarBottleRow[]>();
  for (const b of filteredBottles) {
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
        <div className="mb-4 p-3 rounded-md border border-[color:var(--color-champagne-700)] bg-[color:var(--color-primary-wash)] text-sm text-[color:var(--color-champagne-400)]">
          {errorMsg}
        </div>
      )}
      {/* ── Filter bar ─────────────────────────────────────────────────── */}
      <div className="mb-5 glass-card p-3 space-y-3">
        {/* Row 1: search + reset */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[color:var(--color-fg-subtle)]" strokeWidth={2} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={labels.filterSearch}
              className="w-full pl-9 pr-3 py-1.5 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
            />
          </div>
          {isFiltered && (
            <button
              type="button"
              onClick={() => { setSearch(""); setColorFilter(null); setRegionFilter(""); setVintageFrom(""); setVintageTo(""); }}
              className="flex items-center gap-1 text-[10px] text-[color:var(--color-magenta-400)] hover:text-[color:var(--color-magenta-300)] whitespace-nowrap shrink-0"
            >
              <X className="size-3" strokeWidth={2.5} />
              {labels.filterReset}
            </button>
          )}
          {isFiltered && (
            <span className="text-[10px] font-mono text-[color:var(--color-fg-subtle)] whitespace-nowrap shrink-0">
              {visibleBottleCount} {labels.filterResultsSuffix}
            </span>
          )}
        </div>

        {/* Row 2: colour pills + region + vintage */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Colour pills */}
          <div className="flex items-center gap-1 flex-wrap">
            <button
              type="button"
              onClick={() => setColorFilter(null)}
              className={`text-[10px] px-2 py-0.5 rounded-full border transition ${
                !colorFilter
                  ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-wash)] text-[color:var(--color-magenta-300)]"
                  : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)]"
              }`}
            >
              {labels.filterAllColors}
            </button>
            {allColors.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setColorFilter(colorFilter === c ? null : c)}
                className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border transition ${
                  colorFilter === c
                    ? "border-[color:var(--color-magenta-400)] bg-[color:var(--color-primary-wash)] text-[color:var(--color-magenta-300)]"
                    : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)]"
                }`}
              >
                <span className="inline-block size-1.5 rounded-full shrink-0" style={{ background: COLOR_DOT[c] ?? "#FAF7F5" }} />
                {labels.colorLabels[c] ?? c}
              </button>
            ))}
          </div>

          {/* Separator */}
          <span className="hidden sm:block h-4 w-px bg-[color:var(--color-border)]" aria-hidden />

          {/* Region */}
          <select
            value={regionFilter}
            onChange={(e) => setRegionFilter(e.target.value)}
            className="text-[10px] px-2 py-1 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
          >
            <option value="">{labels.filterAllRegions}</option>
            {allRegions.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>

          {/* Vintage range */}
          <div className="flex items-center gap-1 text-[10px] text-[color:var(--color-fg-subtle)]">
            <span>{labels.filterVintageFrom}</span>
            <input
              type="number"
              min={vintageMin}
              max={vintageMax}
              value={vintageFrom}
              onChange={(e) => setVintageFrom(e.target.value)}
              placeholder={String(vintageMin || "—")}
              className="w-16 px-1.5 py-0.5 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-[color:var(--color-fg)] font-mono text-[10px] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
            />
            <span>{labels.filterVintageTo}</span>
            <input
              type="number"
              min={vintageMin}
              max={vintageMax}
              value={vintageTo}
              onChange={(e) => setVintageTo(e.target.value)}
              placeholder={String(vintageMax || "—")}
              className="w-16 px-1.5 py-0.5 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-[color:var(--color-fg)] font-mono text-[10px] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
            />
          </div>
        </div>
      </div>

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
                isDropTarget ? "ring-2 ring-[color:var(--color-magenta-400)]" : ""
              }`}
            >
              <div
                className="absolute inset-0 opacity-25 pointer-events-none"
                style={{
                  background: `linear-gradient(to top, var(--color-champagne-700) 0%, var(--color-champagne-700) ${pct}%, transparent ${pct}%)`,
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

                <div
                  className="space-y-1 flex-1 overflow-y-auto max-h-32 pr-1"
                  onScroll={() => setHover(null)}
                >
                  {cellBottles.length === 0 ? (
                    <p className="text-[10px] text-[color:var(--color-fg-subtle)] italic">
                      {labels.empty}
                    </p>
                  ) : (
                    cellBottles.map((b) => (
                      <button
                        type="button"
                        key={b.inventoryId}
                        draggable={dragEnabled}
                        onDragStart={(e) => {
                          if (!dragEnabled) return;
                          setHover(null);
                          setDraggingId(b.inventoryId);
                          e.dataTransfer.setData("text/inventory-id", String(b.inventoryId));
                          e.dataTransfer.effectAllowed = "move";
                        }}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDropTarget(null);
                        }}
                        onMouseEnter={(e) => {
                          if (dragEnabled) setHover({ bottle: b, rect: e.currentTarget.getBoundingClientRect() });
                        }}
                        onMouseLeave={() => setHover(null)}
                        onClick={() => {
                          setHover(null);
                          setConsumeBottle(b);
                        }}
                        className={`group block w-full text-left rounded px-1.5 py-1 bg-[color:var(--color-primary-tint)] hover:bg-[color:var(--color-primary-soft)] transition [touch-action:manipulation] ${
                          dragEnabled ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"
                        } ${
                          draggingId === b.inventoryId ? "opacity-40" : ""
                        }`}
                      >
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span
                            className="inline-block size-1.5 rounded-full shrink-0"
                            style={{ background: COLOR_DOT[b.color] ?? "#FAF7F5" }}
                            aria-label={b.color}
                          />
                          <span className="text-[10px] font-mono text-[color:var(--color-champagne-400)] shrink-0">
                            ×{b.qty}
                          </span>
                          <span className="text-[10px] text-[color:var(--color-fg)] truncate">
                            {b.cuveeName}
                            {b.vintage && (
                              <span className="ml-1 text-[color:var(--color-fg-muted)]">{b.vintage}</span>
                            )}
                          </span>
                        </div>
                      </button>
                    ))
                  )}
                </div>

                <button
                  onClick={() => setAddOpenForLocation(loc.locationId)}
                  disabled={isFull}
                  className="mt-2 w-full text-[10px] py-1 rounded border border-[color:var(--color-border)] hover:border-[color:var(--color-magenta-400)] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)] disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center gap-1 transition"
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

      {hover && dragEnabled && (
        <WineIdCard bottle={hover.bottle} rect={hover.rect} labels={labels} />
      )}
    </div>
  );
}

/** Floating, fixed-position wine "ID card" shown on hover over a bottle chip. */
function WineIdCard({
  bottle,
  rect,
  labels,
}: {
  bottle: CellarBottleRow;
  rect: DOMRect;
  labels: CellarLabels;
}) {
  const WIDTH = 264;
  const EST_HEIGHT = 230;
  const MARGIN = 8;

  // Prefer placing to the right of the chip; flip left if it would overflow.
  let left = rect.right + MARGIN;
  if (left + WIDTH > window.innerWidth - MARGIN) left = rect.left - WIDTH - MARGIN;
  if (left < MARGIN) left = MARGIN;
  let top = rect.top;
  if (top + EST_HEIGHT > window.innerHeight - MARGIN) {
    top = Math.max(MARGIN, window.innerHeight - EST_HEIGHT - MARGIN);
  }

  const eur = (v: number) =>
    new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: "EUR",
      maximumFractionDigits: 0,
    }).format(v);

  return (
    <div className="fixed z-[60] pointer-events-none" style={{ left, top, width: WIDTH }}>
      <div className="glass-card p-3.5 shadow-2xl">
        <div className="flex items-start gap-2">
          <span
            className="inline-block size-3 rounded-full mt-1 shrink-0"
            style={{ background: COLOR_DOT[bottle.color] ?? "#FAF7F5" }}
            aria-hidden
          />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[color:var(--color-fg)] leading-tight">
              {bottle.producerName}
            </p>
            <p className="text-xs text-[color:var(--color-champagne-400)] leading-tight mt-0.5">
              {bottle.cuveeName}
              {bottle.vintage !== null && (
                <span className="ml-1.5 font-mono text-[color:var(--color-fg-muted)]">
                  {bottle.vintage}
                </span>
              )}
            </p>
          </div>
        </div>

        <p className="mt-2 flex items-center gap-1 text-[10px] text-[color:var(--color-fg-subtle)]">
          <MapPin className="size-3 shrink-0" strokeWidth={2} />
          {bottle.appellationName}
          {bottle.region && bottle.region !== bottle.appellationName && <> · {bottle.region}</>}
        </p>

        <div className="mt-3 pt-3 border-t border-[color:var(--color-border)] grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px] font-mono">
          {bottle.primaryVariety && (
            <span className="col-span-2 flex items-center gap-1.5 text-[color:var(--color-fg-muted)]">
              <Grape className="size-3 text-[color:var(--color-accent)] shrink-0" strokeWidth={2} />
              <span className="truncate">{bottle.primaryVariety}</span>
            </span>
          )}
          {bottle.alcoholPct !== null && bottle.alcoholPct > 0 && (
            <span className="flex items-center gap-1.5 text-[color:var(--color-fg-muted)]">
              <Percent className="size-3 text-[color:var(--color-accent)] shrink-0" strokeWidth={2} />
              {bottle.alcoholPct}%
            </span>
          )}
          <span className="flex items-center gap-1.5 text-[color:var(--color-fg-muted)]">
            <Wine className="size-3 text-[color:var(--color-accent)] shrink-0" strokeWidth={2} />
            ×{bottle.qty}
          </span>
          {bottle.avgRating !== null && (
            <span className="flex items-center gap-1.5 text-[color:var(--color-fg)]">
              <Star className="size-3 text-[color:var(--color-accent)] shrink-0" strokeWidth={2} />
              {Math.round(bottle.avgRating)}/100
            </span>
          )}
          {bottle.avgPriceEur !== null && (
            <span className="flex items-center gap-1.5 text-[color:var(--color-fg)]" title={labels.marketPrice}>
              <Euro className="size-3 text-[color:var(--color-accent)] shrink-0" strokeWidth={2} />
              {eur(bottle.avgPriceEur)}
            </span>
          )}
        </div>

        {bottle.purchasePriceEur !== null && (
          <p className="mt-2 text-[10px] text-[color:var(--color-fg-subtle)]">
            {labels.purchasePrice}: <span className="font-mono">{eur(bottle.purchasePriceEur)}</span>
          </p>
        )}
      </div>
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
  const [ocrState, setOcrState] = useState<"idle" | "scanning" | "done" | "error">("idle");
  const [ocrResult, setOcrResult] = useState<{ producer?: string | null; cuvee?: string | null; vintage?: number | null; confidence?: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // iOS WebKit dispatches a stray pointer/focus event right after the dialog
  // opens, which Radix's dismissable layer misreads as an outside click and
  // closes the dialog instantly. Ignore outside-interactions in the first
  // moments after opening so the dialog stays put on touch devices.
  const openedAtRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    openedAtRef.current = Date.now();
    setQuery("");
    setResults([]);
    setPicked(null);
    setQty(1);
    setPickedLocationId(locationId);
    setErr(null);
    setOcrState("idle");
    setOcrResult(null);
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

  async function handleOcrFile(file: File) {
    if (file.size > 5 * 1024 * 1024) return; // 5 MB guard
    setOcrState("scanning");
    setOcrResult(null);
    const fd = new FormData();
    fd.append("image", file);
    try {
      const r = await fetch("/api/cellar/ocr", { method: "POST", body: fd });
      if (!r.ok) { setOcrState("error"); return; }
      const data = await r.json() as { producer?: string | null; cuvee?: string | null; vintage?: number | null; confidence?: string };
      setOcrResult(data);
      setOcrState("done");
      // Pre-fill the search query with producer + cuvée + vintage
      const parts = [data.producer, data.cuvee, data.vintage].filter(Boolean);
      setQuery(parts.join(" "));
    } catch {
      setOcrState("error");
    }
  }

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
        <Dialog.Overlay className="fixed inset-0 bg-[color:var(--color-overlay)] backdrop-blur-sm z-40" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(560px,90vw)] max-h-[85vh] overflow-hidden glass-card p-6 flex flex-col"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onPointerDownOutside={(e) => {
            if (Date.now() - openedAtRef.current < 600) e.preventDefault();
          }}
          onInteractOutside={(e) => {
            if (Date.now() - openedAtRef.current < 600) e.preventDefault();
          }}
        >
          <div className="flex items-center justify-between mb-4">
            <Dialog.Title className="text-lg font-semibold text-[color:var(--color-fg)]">
              {labels.addBottle}
            </Dialog.Title>
            <Dialog.Close className="text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)]">
              <X className="size-4" />
            </Dialog.Close>
          </div>

          <div className="space-y-3">
            {/* OCR label scanner */}
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                capture="environment"
                className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleOcrFile(f); e.target.value = ""; }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={ocrState === "scanning"}
                className="btn btn-ghost text-xs flex items-center gap-1.5 w-full justify-center border border-dashed border-[color:var(--color-border)] rounded-md py-2 hover:border-[color:var(--color-magenta-400)] disabled:opacity-50"
              >
                {ocrState === "scanning" ? (
                  <><Loader2 className="size-3.5 animate-spin" />{labels.ocrScanning}</>
                ) : (
                  <><Camera className="size-3.5" />{labels.ocrScan}</>
                )}
              </button>
              {ocrState === "done" && ocrResult && (
                <div className="mt-1.5 px-2 py-1.5 rounded bg-[color:var(--color-primary-tint)] border border-[color:var(--color-border)] text-[10px] text-[color:var(--color-fg-muted)] flex items-start gap-2">
                  <CheckCircle2 className="size-3.5 text-[color:var(--color-champagne-400)] shrink-0 mt-0.5" />
                  <span>
                    <span className="font-semibold text-[color:var(--color-fg)]">{ocrResult.producer}</span>
                    {ocrResult.cuvee && <> · {ocrResult.cuvee}</>}
                    {ocrResult.vintage && <> · {ocrResult.vintage}</>}
                    {ocrResult.confidence && <span className="ml-1 opacity-60">({ocrResult.confidence})</span>}
                  </span>
                </div>
              )}
              {ocrState === "error" && (
                <p className="mt-1 text-[10px] text-[color:var(--color-champagne-400)]">{labels.ocrError}</p>
              )}
            </div>

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
                  className="w-full pl-9 pr-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
                />
              </div>
            </div>

            <div className="max-h-48 overflow-y-auto rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-inset-bg)]">
              {results.length === 0 ? (
                <p className="px-3 py-2 text-xs text-[color:var(--color-fg-subtle)] italic">
                  {labels.noResults}
                </p>
              ) : (
                results.map((w) => (
                  <button
                    key={w.wineKey}
                    onClick={() => setPicked(w)}
                    className={`block w-full text-left px-3 py-2 text-xs border-b border-[color:var(--color-border)] last:border-b-0 hover:bg-[color:var(--color-primary-tint)] ${
                      picked?.wineKey === w.wineKey ? "bg-[color:var(--color-primary-wash)]" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-block size-2 rounded-full shrink-0"
                        style={{ background: COLOR_DOT[w.color] ?? "#FAF7F5" }}
                      />
                      <span className="font-semibold text-[color:var(--color-fg)]">{w.producerName}</span>
                      <span className="text-[color:var(--color-magenta-400)]">{w.cuveeName}</span>
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
                  className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
                />
              </div>
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {labels.location}
                </label>
                <select
                  value={pickedLocationId ?? ""}
                  onChange={(e) => setPickedLocationId(Number.parseInt(e.target.value, 10))}
                  className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
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
              <p className="text-xs text-[color:var(--color-champagne-400)] font-mono">{err}</p>
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
  const [mode, setMode] = useState<"consume" | "move" | "details">("consume");
  const [qty, setQty] = useState(1);
  const [score, setScore] = useState<string>("");
  const [occasion, setOccasion] = useState("");
  const [note, setNote] = useState("");
  const [moveTo, setMoveTo] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState(false);

  // Details tab state
  const [purchasePrice, setPurchasePrice] = useState<string>("");
  const [purchaseDateStr, setPurchaseDateStr] = useState<string>("");
  const [purchaseSourceStr, setPurchaseSourceStr] = useState<string>("");
  const [wineDetails, setWineDetails] = useState<WineDetails | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  const openedAtRef = useRef(0);

  useEffect(() => {
    if (!bottle) return;
    openedAtRef.current = Date.now();
    setMode("consume");
    setQty(1);
    setScore("");
    setOccasion("");
    setNote("");
    setMoveTo(bottle.locationId);
    setErr(null);
    setSavedMsg(false);
    setPurchasePrice(bottle.purchasePriceEur !== null ? String(bottle.purchasePriceEur) : "");
    setPurchaseDateStr(
      bottle.purchaseDate
        ? new Date(bottle.purchaseDate).toISOString().slice(0, 10)
        : "",
    );
    setPurchaseSourceStr(bottle.purchaseSource ?? "");
    setWineDetails(null);
  }, [bottle]);

  // Fetch wine details (ratings + market price) when details tab opens
  useEffect(() => {
    if (mode !== "details" || !bottle || wineDetails !== null) return;
    let cancelled = false;
    setDetailsLoading(true);
    fetch(`/api/cellar/wines/${encodeURIComponent(bottle.wineKey)}/details`)
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setWineDetails(data as WineDetails);
      })
      .catch(() => {
        if (!cancelled) setWineDetails({ ratings: [], prices: [], avgPrice: null });
      })
      .finally(() => {
        if (!cancelled) setDetailsLoading(false);
      });
    return () => { cancelled = true; };
  }, [mode, bottle, wineDetails]);

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
        onSuccess();
      } else if (mode === "move") {
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
        onSuccess();
      } else {
        // details mode — save purchase info
        const body: Record<string, unknown> = {};
        body.purchasePriceEur = purchasePrice !== "" ? parseFloat(purchasePrice) : null;
        body.purchaseDate = purchaseDateStr || null;
        body.purchaseSource = purchaseSourceStr || null;
        const r = await fetch(`/api/cellar/inventory/${bottle.inventoryId}`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          setErr(String(j.error ?? r.statusText));
          return;
        }
        setSavedMsg(true);
        setTimeout(() => setSavedMsg(false), 2000);
        onSuccess();
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog.Root open={bottle !== null} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-[color:var(--color-overlay)] backdrop-blur-sm z-40" />
        <Dialog.Content
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[min(520px,90vw)] max-h-[90vh] overflow-y-auto glass-card p-6"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onPointerDownOutside={(e) => {
            if (Date.now() - openedAtRef.current < 600) e.preventDefault();
          }}
          onInteractOutside={(e) => {
            if (Date.now() - openedAtRef.current < 600) e.preventDefault();
          }}
        >
          <div className="flex items-center justify-between mb-3">
            <Dialog.Title className="text-base font-semibold text-[color:var(--color-fg)]">
              {bottle?.producerName} ·{" "}
              <span className="text-[color:var(--color-champagne-400)]">{bottle?.cuveeName}</span>
              {bottle?.vintage && (
                <span className="ml-2 font-mono text-sm text-[color:var(--color-fg-muted)]">
                  {bottle.vintage}
                </span>
              )}
            </Dialog.Title>
            <Dialog.Close className="text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)]">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <p className="text-xs text-[color:var(--color-fg-subtle)] mb-4">
            {labels.qty}: <span className="font-mono">{bottle?.qty}</span>
          </p>

          {/* 3-tab switcher */}
          <div className="flex items-center gap-1 mb-4 p-1 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-inset-bg)]">
            {(["consume", "move", "details"] as const).map((m) => {
              const Icon = m === "consume" ? GlassWater : m === "move" ? Warehouse : Info;
              const label = m === "consume" ? labels.consume : m === "move" ? labels.move : labels.editDetails;
              return (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`flex-1 text-xs py-1.5 rounded flex items-center justify-center gap-1.5 ${
                    mode === m
                      ? "bg-[color:var(--color-magenta-700)] text-[color:var(--color-ivory-100)]"
                      : "text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]"
                  }`}
                >
                  <Icon className="size-3.5" strokeWidth={2.5} />
                  {label}
                </button>
              );
            })}
          </div>

          {mode === "consume" && (
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
                    className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
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
                    className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
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
                  className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
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
                  className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)] resize-none"
                />
              </div>
            </div>
          )}

          {mode === "move" && (
            <div>
              <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                {labels.location}
              </label>
              <select
                value={moveTo ?? ""}
                onChange={(e) => setMoveTo(Number.parseInt(e.target.value, 10))}
                className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
              >
                {locations.map((l) => (
                  <option key={l.locationId} value={l.locationId}>
                    #{String(l.locationId).padStart(2, "0")} — {l.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {mode === "details" && (
            <div className="space-y-4">
              {/* Editable purchase info */}
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                      {labels.purchasePrice}
                    </label>
                    <div className="relative">
                      <Euro className="absolute left-3 top-1/2 -translate-y-1/2 size-3.5 text-[color:var(--color-fg-subtle)]" strokeWidth={2} />
                      <input
                        type="number"
                        min={0}
                        step={0.01}
                        value={purchasePrice}
                        onChange={(e) => setPurchasePrice(e.target.value)}
                        placeholder="0.00"
                        className="w-full pl-9 pr-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                      {labels.purchaseDate}
                    </label>
                    <input
                      type="date"
                      value={purchaseDateStr}
                      onChange={(e) => setPurchaseDateStr(e.target.value)}
                      className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                    {labels.purchaseSource}
                  </label>
                  <input
                    type="text"
                    value={purchaseSourceStr}
                    onChange={(e) => setPurchaseSourceStr(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
                  />
                </div>
              </div>

              {/* Ratings & market price (read-only) */}
              <div className="border-t border-[color:var(--color-border)] pt-4 space-y-3">
                {/* Critic scores */}
                <div>
                  <p className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-2 flex items-center gap-1.5">
                    <Star className="size-3.5 text-[color:var(--color-champagne-400)]" strokeWidth={2.5} />
                    {labels.criticScore}
                  </p>
                  {detailsLoading ? (
                    <Loader2 className="size-4 animate-spin text-[color:var(--color-fg-subtle)]" />
                  ) : !wineDetails || wineDetails.ratings.length === 0 ? (
                    <p className="text-xs text-[color:var(--color-fg-subtle)] italic">{labels.noRatings}</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {wineDetails.ratings.map((r, i) => (
                        <span
                          key={i}
                          className="px-2 py-0.5 rounded bg-[color:var(--color-primary-tint)] border border-[color:var(--color-border)] text-xs font-mono text-[color:var(--color-fg)]"
                        >
                          <span className="text-[color:var(--color-champagne-400)] font-semibold mr-1">{r.criticCode}</span>
                          {Math.round(r.score)}/100
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Market price */}
                <div>
                  <p className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-2 flex items-center gap-1.5">
                    <Euro className="size-3.5 text-[color:var(--color-champagne-400)]" strokeWidth={2.5} />
                    {labels.marketPrice}
                  </p>
                  {detailsLoading ? (
                    <Loader2 className="size-4 animate-spin text-[color:var(--color-fg-subtle)]" />
                  ) : !wineDetails || wineDetails.avgPrice === null ? (
                    <p className="text-xs text-[color:var(--color-fg-subtle)] italic">{labels.noPrices}</p>
                  ) : (
                    <p className="text-sm font-mono text-[color:var(--color-fg)]">
                      avg.{" "}
                      <span className="text-[color:var(--color-champagne-400)] font-semibold">
                        {new Intl.NumberFormat(undefined, {
                          style: "currency",
                          currency: "EUR",
                          maximumFractionDigits: 0,
                        }).format(wineDetails.avgPrice)}
                      </span>
                      {wineDetails.prices.length > 0 && (
                        <span className="ml-2 text-[10px] text-[color:var(--color-fg-subtle)]">
                          ({wineDetails.prices.length} source{wineDetails.prices.length > 1 ? "s" : ""})
                        </span>
                      )}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {err && (
            <p className="text-xs text-[color:var(--color-champagne-400)] font-mono mt-3">{err}</p>
          )}
          {savedMsg && (
            <p className="text-xs text-[color:var(--color-accent)] font-mono mt-3">{labels.saved}</p>
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
