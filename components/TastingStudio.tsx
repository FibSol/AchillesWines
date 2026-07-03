"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowUpNarrowWide,
  CalendarRange,
  Rows3,
  MapPin,
  Grape,
  Clock,
  Sparkles,
  RotateCcw,
  Lock,
  LockOpen,
  X,
  Plus,
  Replace,
  Thermometer,
  Wine,
  Star,
  ChevronRight,
  GlassWater,
  SlidersHorizontal,
  ChevronDown,
  Warehouse,
  Printer,
} from "lucide-react";
import { buildPrintHtml, type WineNote } from "@/lib/tasting/print";
import type {
  TastingFlight,
  TastingMode,
  FlightStop,
  DirectiveNote,
} from "@/lib/tasting/engine";

const COLOR_DOT: Record<string, string> = {
  red: "#A53860",
  white: "#E5B25D",
  "rosé": "#E07898",
  sparkling: "#F5D08C",
  sweet: "#EDC072",
  fortified: "#6E1F3D",
  orange: "#C99440",
};

const MODE_ICONS: Record<TastingMode, typeof Sparkles> = {
  progressive: ArrowUpNarrowWide,
  vertical: CalendarRange,
  horizontal: Rows3,
  regional: MapPin,
  grape: Grape,
  drink_now: Clock,
};

const COUNT_OPTIONS = [4, 5, 6, 7, 8];

interface PoolWine {
  wineKey: string;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  color: string;
  region: string;
  qty: number;
}

interface ModeFeasibility {
  feasible: boolean;
  axesCount: number;
  wineCount: number;
}

interface PoolResponse {
  poolSize: number;
  modes: Record<TastingMode, ModeFeasibility>;
  countries: string[];
  regions: string[];
  colors: string[];
}

interface TastingFilters {
  countries: string[];
  regions: string[];
  colors: string[];
  minRating: number | null;
  maxPriceEur: number | null;
}

const EMPTY_FILTERS: TastingFilters = {
  countries: [],
  regions: [],
  colors: [],
  minRating: null,
  maxPriceEur: null,
};

interface GenerateResponse {
  flight: TastingFlight | null;
  poolWines: PoolWine[];
  poolSize: number;
  empty: boolean;
}

const ALL_MODES: TastingMode[] = [
  "progressive",
  "vertical",
  "horizontal",
  "regional",
  "grape",
  "drink_now",
];

/** Compose a readable, factual wine description from a flight stop's attributes. */
function buildDescription(stop: FlightStop, t: ReturnType<typeof useTranslations>): string {
  const parts: string[] = [];
  parts.push(
    t("desc.origin", {
      // ICU select keys avoid the accented "rosé" token.
      color: stop.color === "rosé" ? "rose" : stop.color,
      appellation: stop.appellationName,
      region: stop.region,
    }),
  );
  if (stop.grapes.length > 0) {
    parts.push(t("desc.grapeBlend", { grapes: stop.grapes.join(", ") }));
  }
  if (stop.vintage !== null) parts.push(t("desc.vintageYear", { year: String(stop.vintage) }));
  else parts.push(t("desc.nonVintage"));
  if (stop.level !== "regional") parts.push(t("desc.classification", { level: stop.level }));
  if (stop.alcoholPct !== null && stop.alcoholPct > 0) {
    parts.push(t("desc.abv", { abv: stop.alcoholPct }));
  }
  if (stop.avgRating !== null) {
    parts.push(t("desc.critics", { rating: Math.round(stop.avgRating) }));
  }
  if (stop.vintageScore !== null && stop.vintage !== null) {
    parts.push(
      t("desc.vintageQuality", {
        region: stop.region,
        year: String(stop.vintage),
        score: Math.round(stop.vintageScore),
      }),
    );
  }
  return parts.join(" ");
}

export function TastingStudio() {
  const t = useTranslations("tasting");
  const locale = useLocale();

  const [mode, setMode] = useState<TastingMode>("progressive");
  const [cellarTemp, setCellarTemp] = useState(19);
  const [fridgeOvernight, setFridgeOvernight] = useState(false);
  const [printing, setPrinting] = useState(false);
  const [count, setCount] = useState(6);
  const [axisId, setAxisId] = useState<string | undefined>(undefined);
  const [locked, setLocked] = useState<string[]>([]);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [filters, setFilters] = useState<TastingFilters>(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const [pool, setPool] = useState<PoolResponse | null>(null);
  const [flight, setFlight] = useState<TastingFlight | null>(null);
  const [poolWines, setPoolWines] = useState<PoolWine[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [empty, setEmpty] = useState(false);
  const [pickerFor, setPickerFor] = useState<string | "add" | null>(null);

  const renderNote = useCallback(
    (note: DirectiveNote) => t(`notes.${note.key}`, note.params ?? {}),
    [t],
  );

  // Core generate call. Accepts overrides so callers can change one axis of state
  // and generate atomically (avoids stale-closure races on rapid clicks).
  const generate = useCallback(
    async (override?: {
      mode?: TastingMode;
      count?: number;
      axisId?: string | undefined;
      locked?: string[];
      excluded?: string[];
      filters?: TastingFilters;
    }) => {
      const activeFilters = override?.filters !== undefined ? override.filters : filters;
      const req = {
        mode: override?.mode ?? mode,
        count: override?.count ?? count,
        axisId: override?.axisId !== undefined ? override.axisId : axisId,
        lockedWineKeys: override?.locked ?? locked,
        excludeWineKeys: override?.excluded ?? excluded,
        filters: activeFilters,
      };
      setLoading(true);
      setError(null);
      try {
        const r = await fetch("/api/tasting/generate", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(req),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          setError(String(j.error ?? r.statusText));
          return;
        }
        const data: GenerateResponse = await r.json();
        setEmpty(data.empty);
        setFlight(data.flight);
        setPoolWines(data.poolWines ?? []);
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [mode, count, axisId, locked, excluded, filters],
  );

  // On mount: load feasibility + auto-curate the default progressive flight.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/tasting/pool");
        if (!r.ok) return;
        const data: PoolResponse = await r.json();
        if (cancelled) return;
        setPool(data);
        if (data.poolSize === 0) {
          setEmpty(true);
          return;
        }
        await generate({ mode: "progressive" });
      } catch {
        /* surfaced on first manual generate */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectMode(m: TastingMode) {
    if (pool && !pool.modes[m]?.feasible) return;
    setMode(m);
    setAxisId(undefined);
    setLocked([]);
    setExcluded([]);
    void generate({ mode: m, axisId: undefined, locked: [], excluded: [] });
  }

  function changeCount(n: number) {
    setCount(n);
    void generate({ count: n });
  }

  function changeAxis(id: string) {
    setAxisId(id);
    setLocked([]);
    setExcluded([]);
    void generate({ axisId: id, locked: [], excluded: [] });
  }

  function toggleLock(wineKey: string) {
    const next = locked.includes(wineKey)
      ? locked.filter((k) => k !== wineKey)
      : [...locked, wineKey];
    setLocked(next);
    // No regenerate needed — lock only affects the *next* generation.
  }

  function removeStop(wineKey: string) {
    const nextExcluded = [...excluded, wineKey];
    const nextLocked = locked.filter((k) => k !== wineKey);
    setExcluded(nextExcluded);
    setLocked(nextLocked);
    void generate({ excluded: nextExcluded, locked: nextLocked });
  }

  function surprise() {
    if (!flight) return;
    // Exclude every currently-shown wine that the user did not lock, then re-roll.
    const toExclude = flight.stops
      .map((s) => s.wineKey)
      .filter((k) => !locked.includes(k));
    const nextExcluded = [...new Set([...excluded, ...toExclude])];
    setExcluded(nextExcluded);
    void generate({ excluded: nextExcluded });
  }

  function reset() {
    setLocked([]);
    setExcluded([]);
    setAxisId(undefined);
    void generate({ locked: [], excluded: [], axisId: undefined });
  }

  async function printSheet() {
    if (!flight || flight.stops.length === 0 || printing) return;
    // Open the window synchronously (inside the click) so popup blockers allow it,
    // then fill it once the AI blurbs are fetched.
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(
      `<p style="font-family:system-ui,sans-serif;padding:2rem;color:#555">${t("print.generating")}</p>`,
    );
    setPrinting(true);
    let wineNotes: Record<string, WineNote> | undefined;
    try {
      const r = await fetch("/api/tasting/wine-notes", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          locale,
          wines: flight.stops.map((s) => ({
            wineKey: s.wineKey,
            producerName: s.producerName,
            cuveeName: s.cuveeName,
            vintage: s.vintage,
            color: s.color,
            appellationName: s.appellationName,
            region: s.region,
            grapes: s.grapes,
          })),
        }),
      });
      if (r.ok) {
        const data: { notes?: Record<string, WineNote> } = await r.json();
        wineNotes = data.notes;
      }
    } catch {
      /* print without blurbs */
    } finally {
      setPrinting(false);
    }
    const html = buildPrintHtml({
      flight,
      cellarTempC: cellarTemp,
      locale,
      t: (key, values) => t(key, values),
      renderNote,
      wineNotes,
      bottlesStart: fridgeOvernight ? "fridgeOvernight" : "cellar",
    });
    w.document.open();
    w.document.write(html);
    w.document.close();
  }

  function applyFilters(next: TastingFilters) {
    setFilters(next);
    setLocked([]);
    setExcluded([]);
    void generate({ filters: next, locked: [], excluded: [] });
  }

  function resetFilters() {
    applyFilters(EMPTY_FILTERS);
  }

  const activeFilterCount =
    filters.countries.length +
    filters.regions.length +
    filters.colors.length +
    (filters.minRating !== null ? 1 : 0) +
    (filters.maxPriceEur !== null ? 1 : 0);

  function pickReplacement(targetWineKey: string | "add", newWineKey: string) {
    setPickerFor(null);
    let nextLocked = [...locked];
    let nextExcluded = [...excluded];
    if (targetWineKey !== "add") {
      nextExcluded = [...new Set([...nextExcluded, targetWineKey])];
      nextLocked = nextLocked.filter((k) => k !== targetWineKey);
    }
    if (!nextLocked.includes(newWineKey)) nextLocked.push(newWineKey);
    nextExcluded = nextExcluded.filter((k) => k !== newWineKey);
    setLocked(nextLocked);
    setExcluded(nextExcluded);
    void generate({ locked: nextLocked, excluded: nextExcluded });
  }

  const inFlightKeys = new Set(flight?.stops.map((s) => s.wineKey) ?? []);
  const availablePoolWines = poolWines.filter((w) => !inFlightKeys.has(w.wineKey));

  /* ---- Empty cellar ---- */
  if (empty) {
    return (
      <div className="glass-card p-12 text-center">
        <GlassWater className="size-10 mx-auto mb-4 text-[color:var(--color-fg-subtle)]" strokeWidth={1.5} />
        <p className="text-[color:var(--color-fg-muted)]">{t("ui.emptyCellar")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Filter panel */}
      <section>
        <button
          onClick={() => setFiltersOpen((v) => !v)}
          className="flex items-center gap-2 text-xs text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-primary)] transition mb-3"
        >
          <SlidersHorizontal className="size-3.5" strokeWidth={2.5} />
          <span className="uppercase tracking-[0.06em]">{t("filters.title")}</span>
          {activeFilterCount > 0 && (
            <span className="px-1.5 py-0.5 rounded bg-[rgba(165,56,96,0.2)] text-[color:var(--color-primary)] font-mono text-[10px]">
              {t("filters.active", { count: activeFilterCount })}
            </span>
          )}
          <ChevronDown className={`size-3.5 transition-transform ${filtersOpen ? "rotate-180" : ""}`} strokeWidth={2.5} />
        </button>

        {filtersOpen && pool && (
          <div className="glass-card p-4 space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {/* Country */}
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {t("filters.country")}
                </label>
                <select
                  value={filters.countries[0] ?? ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    applyFilters({ ...filters, countries: val ? [val] : [], regions: [] });
                  }}
                  className="w-full px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-primary)]"
                >
                  <option value="">{t("filters.all")}</option>
                  {pool.countries.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              {/* Region */}
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {t("filters.region")}
                </label>
                <select
                  value={filters.regions[0] ?? ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    applyFilters({ ...filters, regions: val ? [val] : [] });
                  }}
                  className="w-full px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-primary)]"
                >
                  <option value="">{t("filters.all")}</option>
                  {pool.regions.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>

              {/* Color */}
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {t("filters.color")}
                </label>
                <select
                  value={filters.colors[0] ?? ""}
                  onChange={(e) => {
                    const val = e.target.value;
                    applyFilters({ ...filters, colors: val ? [val] : [] });
                  }}
                  className="w-full px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-primary)]"
                >
                  <option value="">{t("filters.all")}</option>
                  {pool.colors.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              {/* Min rating */}
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {t("filters.minRating")}
                </label>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={filters.minRating ?? ""}
                  onChange={(e) => {
                    const val = e.target.value !== "" ? Number(e.target.value) : null;
                    applyFilters({ ...filters, minRating: val });
                  }}
                  placeholder="0–100"
                  className="w-full px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-primary)]"
                />
              </div>

              {/* Max price */}
              <div>
                <label className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1 block">
                  {t("filters.maxPrice")}
                </label>
                <input
                  type="number"
                  min={0}
                  value={filters.maxPriceEur ?? ""}
                  onChange={(e) => {
                    const val = e.target.value !== "" ? Number(e.target.value) : null;
                    applyFilters({ ...filters, maxPriceEur: val });
                  }}
                  placeholder="€"
                  className="w-full px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-primary)]"
                />
              </div>

              {/* Reset */}
              {activeFilterCount > 0 && (
                <div className="flex items-end">
                  <button
                    onClick={resetFilters}
                    className="w-full btn btn-ghost text-xs"
                  >
                    <RotateCcw className="size-3" strokeWidth={2.5} />
                    {t("filters.reset")}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Mode selector */}
      <section>
        <p className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-3">
          {t("ui.chooseMode")}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {ALL_MODES.map((m) => {
            const Icon = MODE_ICONS[m];
            const feas = pool?.modes[m];
            const disabled = pool ? !feas?.feasible : false;
            const active = mode === m;
            return (
              <button
                key={m}
                onClick={() => selectMode(m)}
                disabled={disabled}
                className={[
                  "glass-card p-4 text-left transition-all",
                  active ? "ring-2 ring-[color:var(--color-primary)]" : "",
                  disabled ? "opacity-40 cursor-not-allowed" : "hover:border-[color:var(--color-primary)] cursor-pointer",
                ].join(" ")}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <Icon className="size-4 text-[color:var(--color-primary)]" strokeWidth={2.5} />
                  <span className="font-semibold text-sm text-[color:var(--color-fg)]">
                    {t(`modes.${m}.name`)}
                  </span>
                </div>
                <p className="text-xs text-[color:var(--color-fg-muted)] leading-snug">
                  {t(`modes.${m}.desc`)}
                </p>
                {feas && (
                  <p className="mt-2 font-mono text-[10px] text-[color:var(--color-fg-subtle)]">
                    {disabled ? t("ui.needsMore") : `${feas.wineCount} ${t("ui.wines")}`}
                  </p>
                )}
              </button>
            );
          })}
        </div>
      </section>

      {/* Controls */}
      <section className="flex flex-wrap items-center gap-3">
        {/* Axis selector for theme modes */}
        {flight && flight.availableAxes.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-[color:var(--color-fg-muted)]">
            <span className="uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
              {t(`axisLabel.${mode}`)}
            </span>
            <select
              value={flight.selectedAxis?.id ?? ""}
              onChange={(e) => changeAxis(e.target.value)}
              className="px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-primary)] max-w-[16rem]"
            >
              {flight.availableAxes.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label} ({a.count})
                </option>
              ))}
            </select>
          </label>
        )}

        {/* Count */}
        <label className="flex items-center gap-2 text-xs text-[color:var(--color-fg-muted)]">
          <span className="uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
            {t("ui.count")}
          </span>
          <select
            value={count}
            onChange={(e) => changeCount(Number.parseInt(e.target.value, 10))}
            className="px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-primary)]"
          >
            {COUNT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>

        <button onClick={surprise} disabled={loading || !flight} className="btn btn-ghost text-xs">
          <Sparkles className="size-3.5" strokeWidth={2.5} />
          {t("ui.surprise")}
        </button>
        <button onClick={reset} disabled={loading} className="btn btn-ghost text-xs">
          <RotateCcw className="size-3.5" strokeWidth={2.5} />
          {t("ui.reset")}
        </button>
        <button
          onClick={() => setPickerFor("add")}
          disabled={loading || availablePoolWines.length === 0}
          className="btn btn-ghost text-xs"
        >
          <Plus className="size-3.5" strokeWidth={2.5} />
          {t("ui.addFromCellar")}
        </button>

        {/* Cellar temperature + printable prep sheet */}
        <label className="flex items-center gap-2 text-xs text-[color:var(--color-fg-muted)]">
          <span className="uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
            {t("print.cellarTemp")}
          </span>
          <input
            type="number"
            min={0}
            max={30}
            value={cellarTemp}
            disabled={fridgeOvernight}
            onChange={(e) => setCellarTemp(Number(e.target.value))}
            className="w-16 px-2 py-1.5 rounded bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-primary)] disabled:opacity-40"
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-[color:var(--color-fg-muted)] cursor-pointer">
          <input
            type="checkbox"
            checked={fridgeOvernight}
            onChange={(e) => setFridgeOvernight(e.target.checked)}
            className="accent-[#A53860]"
          />
          {t("print.fridgeOvernight")}
        </label>
        <button
          onClick={printSheet}
          disabled={loading || printing || !flight || flight.stops.length === 0}
          className="btn btn-ghost text-xs"
        >
          <Printer className="size-3.5" strokeWidth={2.5} />
          {printing ? t("print.generating") : t("print.button")}
        </button>
        {loading && (
          <span className="text-xs text-[color:var(--color-fg-subtle)] font-mono">{t("ui.loading")}</span>
        )}
      </section>

      {error && (
        <div className="p-3 rounded-md border border-[color:var(--color-champagne-700)] bg-[rgba(165,56,96,0.1)] text-sm text-[color:var(--color-champagne-400)] font-mono">
          {error}
        </div>
      )}

      {/* No feasible flight for this mode */}
      {flight && flight.stops.length === 0 && (
        <div className="glass-card p-8 text-center text-sm text-[color:var(--color-fg-muted)]">
          {t("ui.emptyMode")}
        </div>
      )}

      {/* Flight-level directives */}
      {flight && flight.stops.length > 0 && (
        <section className="glass-card p-5">
          <h3 className="flex items-center gap-2 text-sm font-display text-[color:var(--color-fg)] mb-3">
            <Sparkles className="size-4 text-[color:var(--color-accent)]" strokeWidth={2.5} />
            {t("ui.directives")}
          </h3>
          <ul className="space-y-1.5">
            {flight.overall.map((note, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-[color:var(--color-fg-muted)]">
                <ChevronRight className="size-3.5 mt-0.5 text-[color:var(--color-primary)] shrink-0" strokeWidth={2.5} />
                {renderNote(note)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* The flight, in serving order */}
      {flight && flight.stops.length > 0 && (
        <section className="space-y-3">
          {flight.stops.map((stop) => (
            <StopCard
              key={stop.wineKey}
              stop={stop}
              isLocked={locked.includes(stop.wineKey)}
              total={flight.stops.length}
              onToggleLock={() => toggleLock(stop.wineKey)}
              onRemove={() => removeStop(stop.wineKey)}
              onSwap={() => setPickerFor(stop.wineKey)}
              renderNote={renderNote}
              t={t}
            />
          ))}
        </section>
      )}

      {/* Replacement / add picker */}
      {pickerFor !== null && (
        <PoolPicker
          wines={availablePoolWines}
          title={pickerFor === "add" ? t("ui.addFromCellar") : t("ui.chooseReplacement")}
          onPick={(wineKey) => pickReplacement(pickerFor, wineKey)}
          onClose={() => setPickerFor(null)}
          searchLabel={t("ui.searchWine")}
          cancelLabel={t("ui.cancel")}
        />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------- */

function StopCard({
  stop,
  isLocked,
  total,
  onToggleLock,
  onRemove,
  onSwap,
  renderNote,
  t,
}: {
  stop: FlightStop;
  isLocked: boolean;
  total: number;
  onToggleLock: () => void;
  onRemove: () => void;
  onSwap: () => void;
  renderNote: (n: DirectiveNote) => string;
  t: ReturnType<typeof useTranslations>;
}) {
  // Compose a readable description from the wine's real attributes.
  const description = buildDescription(stop, t);

  return (
    <div className="glass-card p-5">
      <div className="flex items-start gap-4">
        {/* Order number */}
        <div className="shrink-0 flex flex-col items-center">
          <span className="display-xl text-2xl text-gradient leading-none">{stop.position}</span>
          <span className="mt-1 font-mono text-[9px] uppercase text-[color:var(--color-fg-subtle)]">
            {stop.position === 1 ? t("ui.first") : stop.position === total ? t("ui.last") : t("ui.then")}
          </span>
        </div>

        {/* Body */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span
              className="inline-block size-2.5 rounded-full shrink-0"
              style={{ background: COLOR_DOT[stop.color] ?? "#FAF7F5" }}
              title={stop.color}
            />
            <span className="font-semibold text-[color:var(--color-fg)] leading-tight truncate">
              {stop.producerName}
            </span>
          </div>
          <p className="text-sm text-[color:var(--color-primary)]">
            {stop.cuveeName}
            {stop.vintage !== null && (
              <span className="ml-1.5 font-mono text-[color:var(--color-fg-muted)]">{stop.vintage}</span>
            )}
          </p>
          <p className="text-[11px] text-[color:var(--color-fg-subtle)] mt-0.5">
            {stop.appellationName}
            {stop.primaryVariety && <span> · {stop.primaryVariety}</span>}
            {stop.qty > 0 && <span> · ×{stop.qty}</span>}
          </p>

          {/* Cellar location(s) */}
          {stop.locations.length > 0 && (
            <p className="mt-1 flex items-center gap-1.5 flex-wrap text-[11px] text-[color:var(--color-fg-muted)]">
              <Warehouse className="size-3 text-[color:var(--color-accent)] shrink-0" strokeWidth={2.5} />
              <span className="uppercase tracking-[0.06em] text-[9px] text-[color:var(--color-fg-subtle)]">
                {t("ui.cellarLocation")}
              </span>
              {stop.locations.map((l, i) => (
                <span key={l.locationId} className="text-[color:var(--color-fg)]">
                  {l.name}
                  {stop.locations.length > 1 && (
                    <span className="text-[color:var(--color-fg-muted)]"> ×{l.qty}</span>
                  )}
                  {i < stop.locations.length - 1 && (
                    <span className="text-[color:var(--color-fg-subtle)]"> ·</span>
                  )}
                </span>
              ))}
            </p>
          )}

          {/* Wine description */}
          {description && (
            <p className="mt-3 text-xs leading-relaxed text-[color:var(--color-fg-muted)] italic border-l-2 border-[color:var(--color-border)] pl-3">
              {description}
            </p>
          )}

          {/* Body / weight bar */}
          <div className="mt-3 flex items-center gap-2">
            <span className="font-mono text-[9px] text-[color:var(--color-fg-subtle)] w-8">{t("ui.light")}</span>
            <div className="flex-1 h-1.5 rounded-full bg-[rgba(255,255,255,0.08)] overflow-hidden">
              <div
                className="h-full rounded-full bg-gradient-to-r from-[color:var(--color-accent)] to-[color:var(--color-primary)]"
                style={{ width: `${stop.weight}%` }}
              />
            </div>
            <span className="font-mono text-[9px] text-[color:var(--color-fg-subtle)] w-8 text-right">{t("ui.full")}</span>
          </div>

          {/* Quick facts */}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] font-mono text-[color:var(--color-fg-muted)]">
            <span className="flex items-center gap-1">
              <Thermometer className="size-3 text-[color:var(--color-accent)]" strokeWidth={2.5} />
              {stop.serveTempC[0]}–{stop.serveTempC[1]} °C
            </span>
            <span className="flex items-center gap-1">
              <GlassWater className="size-3 text-[color:var(--color-accent)]" strokeWidth={2.5} />
              {t(`glass.${stop.glassType}`)}
            </span>
            {stop.decantMinutes > 0 && (
              <span className="flex items-center gap-1">
                <Wine className="size-3 text-[color:var(--color-accent)]" strokeWidth={2.5} />
                {t("ui.decantMin", { minutes: stop.decantMinutes })}
              </span>
            )}
            {stop.avgRating !== null && (
              <span className="flex items-center gap-1 text-[color:var(--color-fg)]">
                <Star className="size-3 text-[color:var(--color-accent)]" strokeWidth={2.5} />
                {stop.avgRating.toFixed(0)}/100
              </span>
            )}
          </div>

          {/* Notes */}
          <ul className="mt-3 space-y-0.5">
            {stop.notes.map((note, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-[color:var(--color-fg-muted)]">
                <ChevronRight className="size-3 mt-0.5 text-[color:var(--color-primary)] shrink-0" strokeWidth={2.5} />
                {renderNote(note)}
              </li>
            ))}
          </ul>
        </div>

        {/* Actions */}
        <div className="shrink-0 flex flex-col gap-1.5">
          <IconBtn onClick={onToggleLock} active={isLocked} title={isLocked ? t("ui.locked") : t("ui.lock")}>
            {isLocked ? <Lock className="size-3.5" strokeWidth={2.5} /> : <LockOpen className="size-3.5" strokeWidth={2.5} />}
          </IconBtn>
          <IconBtn onClick={onSwap} title={t("ui.swap")}>
            <Replace className="size-3.5" strokeWidth={2.5} />
          </IconBtn>
          <IconBtn onClick={onRemove} title={t("ui.remove")}>
            <X className="size-3.5" strokeWidth={2.5} />
          </IconBtn>
        </div>
      </div>
    </div>
  );
}

function IconBtn({
  onClick,
  title,
  active,
  children,
}: {
  onClick: () => void;
  title: string;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={[
        "p-1.5 rounded-md transition",
        active
          ? "bg-[rgba(165,56,96,0.18)] text-[color:var(--color-primary)]"
          : "text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-primary)] hover:bg-[rgba(165,56,96,0.08)]",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function PoolPicker({
  wines,
  title,
  onPick,
  onClose,
  searchLabel,
  cancelLabel,
}: {
  wines: PoolWine[];
  title: string;
  onPick: (wineKey: string) => void;
  onClose: () => void;
  searchLabel: string;
  cancelLabel: string;
}) {
  const [q, setQ] = useState("");
  const filtered = q.trim()
    ? wines.filter((w) =>
        `${w.producerName} ${w.cuveeName} ${w.vintage ?? ""} ${w.region}`
          .toLowerCase()
          .includes(q.toLowerCase()),
      )
    : wines;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(8,5,15,0.7)] backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="glass-card w-full max-w-lg max-h-[80vh] flex flex-col p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-display text-[color:var(--color-fg)]">{title}</h3>
          <button onClick={onClose} className="p-1 text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-primary)]" aria-label={cancelLabel}>
            <X className="size-4" strokeWidth={2.5} />
          </button>
        </div>
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={searchLabel}
          autoFocus
          className="w-full px-3 py-2 rounded-md bg-[rgba(9,8,15,0.6)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-primary)] mb-3"
        />
        <div className="overflow-y-auto scrollbar-thin space-y-1">
          {filtered.map((w) => (
            <button
              key={w.wineKey}
              onClick={() => onPick(w.wineKey)}
              className="w-full text-left p-2.5 rounded-md hover:bg-[rgba(165,56,96,0.08)] transition flex items-center gap-2"
            >
              <span
                className="inline-block size-2 rounded-full shrink-0"
                style={{ background: COLOR_DOT[w.color] ?? "#FAF7F5" }}
              />
              <span className="flex-1 min-w-0">
                <span className="text-sm text-[color:var(--color-fg)] truncate block">
                  {w.producerName} — {w.cuveeName}
                  {w.vintage !== null && (
                    <span className="ml-1.5 font-mono text-[color:var(--color-fg-muted)]">{w.vintage}</span>
                  )}
                </span>
                <span className="text-[10px] text-[color:var(--color-fg-subtle)]">
                  {w.region} · ×{w.qty}
                </span>
              </span>
            </button>
          ))}
          {filtered.length === 0 && (
            <p className="text-xs text-[color:var(--color-fg-subtle)] italic p-2">—</p>
          )}
        </div>
      </div>
    </div>
  );
}
