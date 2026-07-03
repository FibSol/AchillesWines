"use client";

import { useState } from "react";
import {
  Plus,
  Trash2,
  Sparkles,
  Users,
  Wallet,
  ChevronRight,
  Wine,
  Euro,
  MinusCircle,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { ConfidenceBadge, deriveConfidence, type ConfidenceLabels } from "@/components/ConfidenceBadge";

type CourseType = "aperitif" | "entree" | "plat" | "fromage" | "dessert" | "other";

interface Course {
  id: string;
  type: CourseType;
  dish: string;
}

interface WineCandidate {
  wineKey: string;
  canonicalName: string;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  color: string;
  appellationName: string;
  avgRating: number | null;
  avgPriceEur: number | null;
  inventoryQty: number;
  sourceCount: number;
}

interface Pick {
  candidate: WineCandidate;
  score: number;
  breakdown: {
    total: number;
    colorMatch: number;
    inventoryBonus: number;
    ratingScore: number;
    budgetPenalty: number;
  };
  rationale: string[];
}

interface Suggestion {
  courseId: string;
  picks: Pick[];
}

interface ProposeResponse {
  suggestions: Suggestion[];
  poolSize: number;
  budgetPerGuest: number | null;
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

export interface MenuLabels {
  courseTypes: Record<CourseType, string>;
  courses: string;
  budget: string;
  guests: string;
  addCourse: string;
  propose: string;
  proposing: string;
  dishPlaceholder: string;
  remove: string;
  noPicks: string;
  noPoolBottlesYet: string;
  scoreLabel: string;
  poolSize: string;
  budgetPerGuest: string;
  fromCellar: string;
  fromRegistry: string;
  consumeBtn: string;
  consumeQty: string;
  consumeConfirm: string;
  consumeCancel: string;
  consumeSuccess: string;
  confidence: ConfidenceLabels;
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10);
}

// Inline consume widget state keyed by wineKey
interface ConsumeState {
  mode: "idle" | "confirm" | "loading" | "done";
  qty: number;
  remainingQty: number; // local optimistic update
}

export function MenuComposer({ labels }: { labels: MenuLabels }) {
  const [courses, setCourses] = useState<Course[]>([
    { id: uid(), type: "entree", dish: "" },
    { id: uid(), type: "plat", dish: "" },
  ]);
  const [guests, setGuests] = useState(2);
  const [budget, setBudget] = useState<string>("");
  const [response, setResponse] = useState<ProposeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Per-wine consume state (keyed by wineKey)
  const [consumeMap, setConsumeMap] = useState<Map<string, ConsumeState>>(new Map());

  function getConsumeState(wineKey: string, inventoryQty: number): ConsumeState {
    return consumeMap.get(wineKey) ?? { mode: "idle", qty: 1, remainingQty: inventoryQty };
  }

  function patchConsumeState(wineKey: string, patch: Partial<ConsumeState>, inventoryQty = 0) {
    setConsumeMap((m) => {
      const next = new Map(m);
      const cur = next.get(wineKey) ?? { mode: "idle", qty: 1, remainingQty: inventoryQty };
      next.set(wineKey, { ...cur, ...patch });
      return next;
    });
  }

  async function doConsume(wineKey: string, qty: number) {
    patchConsumeState(wineKey, { mode: "loading" });
    try {
      const r = await fetch("/api/cellar/consume-by-wine", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ wineKey, qty }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        patchConsumeState(wineKey, { mode: "idle" });
        setError(String(j.error ?? r.statusText));
        return;
      }
      const remaining: number = j.remaining ?? 0;
      patchConsumeState(wineKey, { mode: "done", remainingQty: remaining });
      // Auto-reset after 3 s
      setTimeout(() => {
        patchConsumeState(wineKey, { mode: "idle", qty: 1, remainingQty: remaining });
      }, 3000);
    } catch (e) {
      patchConsumeState(wineKey, { mode: "idle" });
      setError(String(e));
    }
  }

  function addCourse() {
    setCourses((cs) => [...cs, { id: uid(), type: "plat", dish: "" }]);
  }
  function removeCourse(id: string) {
    setCourses((cs) => cs.filter((c) => c.id !== id));
  }
  function updateCourse(id: string, patch: Partial<Course>) {
    setCourses((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  }

  async function propose() {
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const r = await fetch("/api/pairing/propose", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          courses: courses.map((c) => ({ id: c.id, type: c.type, dish: c.dish })),
          guests,
          budgetEur: budget ? Number.parseFloat(budget) : undefined,
          preferCellar: true,
        }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setError(String(j.error ?? r.statusText));
        return;
      }
      setResponse(await r.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      {/* Composer */}
      <section className="glass-card p-6">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <label className="block">
            <span className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1.5 flex items-center gap-1.5">
              <Users className="size-3" strokeWidth={2.5} />
              {labels.guests}
            </span>
            <input
              type="number"
              min={1}
              max={50}
              value={guests}
              onChange={(e) => setGuests(Math.max(1, Number.parseInt(e.target.value, 10) || 1))}
              className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
            />
          </label>
          <label className="block">
            <span className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-1.5 flex items-center gap-1.5">
              <Wallet className="size-3" strokeWidth={2.5} />
              {labels.budget} (€)
            </span>
            <input
              type="number"
              min={0}
              step={5}
              value={budget}
              placeholder="optional"
              onChange={(e) => setBudget(e.target.value)}
              className="w-full px-3 py-2 rounded-md bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
            />
          </label>
          <div className="flex items-end">
            <button
              onClick={propose}
              disabled={loading || courses.length === 0}
              className="btn btn-primary text-sm w-full disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Sparkles className="size-4" strokeWidth={2.5} />
              {loading ? labels.proposing : labels.propose}
            </button>
          </div>
        </div>

        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
            {labels.courses}
          </p>
          {courses.map((c, idx) => (
            <div
              key={c.id}
              className="flex items-center gap-2 p-3 rounded-md bg-[color:var(--color-inset-bg)] border border-[color:var(--color-border)]"
            >
              <span className="font-mono text-[10px] text-[color:var(--color-fg-subtle)] w-5 shrink-0">
                {idx + 1}.
              </span>
              <select
                value={c.type}
                onChange={(e) => updateCourse(c.id, { type: e.target.value as CourseType })}
                className="px-2 py-1.5 rounded bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-xs text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)] shrink-0"
              >
                {(Object.keys(labels.courseTypes) as CourseType[]).map((k) => (
                  <option key={k} value={k}>
                    {labels.courseTypes[k]}
                  </option>
                ))}
              </select>
              <input
                type="text"
                value={c.dish}
                onChange={(e) => updateCourse(c.id, { dish: e.target.value })}
                placeholder={labels.dishPlaceholder}
                className="flex-1 px-3 py-1.5 rounded bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-sm text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
              />
              <button
                onClick={() => removeCourse(c.id)}
                className="p-1.5 rounded text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)] hover:bg-[color:var(--color-primary-tint)] transition shrink-0"
                title={labels.remove}
                aria-label={labels.remove}
              >
                <Trash2 className="size-3.5" strokeWidth={2.5} />
              </button>
            </div>
          ))}
          <button
            onClick={addCourse}
            className="btn btn-ghost text-xs"
          >
            <Plus className="size-3" strokeWidth={2.5} />
            {labels.addCourse}
          </button>
        </div>
      </section>

      {/* Errors */}
      {error && (
        <div className="p-3 rounded-md border border-[color:var(--color-champagne-700)] bg-[color:var(--color-primary-wash)] text-sm text-[color:var(--color-champagne-400)] font-mono">
          {error}
        </div>
      )}

      {/* Pool summary */}
      {response && (
        <section className="flex items-center gap-4 flex-wrap text-xs text-[color:var(--color-fg-muted)]">
          <span className="font-mono">
            {labels.poolSize}: <span className="text-[color:var(--color-champagne-400)]">{response.poolSize}</span>
          </span>
          {response.budgetPerGuest !== null && (
            <span className="font-mono">
              {labels.budgetPerGuest}: <span className="text-[color:var(--color-champagne-400)]">€{response.budgetPerGuest.toFixed(2)}</span>
            </span>
          )}
        </section>
      )}

      {/* Suggestions */}
      {response && (
        <section className="space-y-6">
          {response.suggestions.map((s, idx) => {
            const course = courses.find((c) => c.id === s.courseId);
            if (!course) return null;
            return (
              <div key={s.courseId}>
                <div className="flex items-baseline gap-3 mb-3">
                  <span className="font-mono text-xs text-[color:var(--color-fg-subtle)]">
                    {idx + 1}.
                  </span>
                  <h3 className="text-base font-display text-[color:var(--color-fg)]">
                    {labels.courseTypes[course.type]}
                  </h3>
                  {course.dish && (
                    <span className="text-sm text-[color:var(--color-champagne-400)] italic">
                      « {course.dish} »
                    </span>
                  )}
                </div>

                {s.picks.length === 0 ? (
                  <p className="glass-card p-4 text-xs text-[color:var(--color-fg-subtle)] italic">
                    {labels.noPicks}
                  </p>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {s.picks.map((p, i) => {
                      const cs = getConsumeState(p.candidate.wineKey, p.candidate.inventoryQty);
                      const effectiveQty = cs.remainingQty;
                      const hasStock = effectiveQty > 0;

                      return (
                        <div key={p.candidate.wineKey} className="glass-card p-4 relative flex flex-col">
                          <div className="absolute top-3 right-3">
                            <ConfidenceBadge
                              confidence={deriveConfidence(p.candidate.sourceCount)}
                              sourceCount={p.candidate.sourceCount}
                              labels={labels.confidence}
                              size="sm"
                              iconOnly
                            />
                          </div>

                          <div className="flex items-center gap-2 mb-2 pr-6">
                            <span className="font-mono text-[10px] text-[color:var(--color-fg-subtle)]">
                              #{i + 1}
                            </span>
                            <span
                              className="inline-block size-2 rounded-full shrink-0"
                              style={{ background: COLOR_DOT[p.candidate.color] ?? "#FAF7F5" }}
                              aria-label={p.candidate.color}
                            />
                            <span className="font-mono text-[10px] text-[color:var(--color-champagne-400)]">
                              {p.score.toFixed(0)} {labels.scoreLabel}
                            </span>
                          </div>

                          <p className="font-semibold text-sm text-[color:var(--color-fg)] leading-tight">
                            {p.candidate.producerName}
                          </p>
                          <p className="text-xs text-[color:var(--color-champagne-400)] mt-0.5">
                            {p.candidate.cuveeName}
                            {p.candidate.vintage && (
                              <span className="ml-1.5 font-mono text-[color:var(--color-fg-muted)]">
                                {p.candidate.vintage}
                              </span>
                            )}
                          </p>
                          <p className="text-[10px] text-[color:var(--color-fg-subtle)] mt-0.5">
                            {p.candidate.appellationName}
                          </p>

                          <div className="mt-3 flex items-center gap-3 text-[10px] font-mono flex-wrap">
                            {hasStock ? (
                              <span className="badge badge-verified text-[10px] py-0.5">
                                <Wine className="size-2.5" strokeWidth={2.5} />
                                {labels.fromCellar} ×{effectiveQty}
                              </span>
                            ) : (
                              <span className="text-[color:var(--color-fg-subtle)]">
                                {labels.fromRegistry}
                              </span>
                            )}
                            {p.candidate.avgRating !== null && (
                              <span className="text-[color:var(--color-accent)]">
                                {p.candidate.avgRating.toFixed(0)}/100
                              </span>
                            )}
                            {p.candidate.avgPriceEur !== null && (
                              <span className="flex items-center gap-0.5 text-[color:var(--color-champagne-400)] font-semibold">
                                <Euro className="size-2.5" strokeWidth={2.5} />
                                {p.candidate.avgPriceEur.toFixed(0)}
                              </span>
                            )}
                          </div>

                          <ul className="mt-3 space-y-0.5 flex-1">
                            {p.rationale.map((r, j) => (
                              <li
                                key={j}
                                className="text-[10px] text-[color:var(--color-fg-muted)] flex items-center gap-1"
                              >
                                <ChevronRight
                                  className="size-2.5 text-[color:var(--color-champagne-400)] shrink-0"
                                  strokeWidth={2.5}
                                />
                                {r}
                              </li>
                            ))}
                          </ul>

                          {/* ── Consume widget (only for cellar wines) ─────── */}
                          {hasStock && (
                            <div className="mt-3 pt-3 border-t border-[color:var(--color-border)]">
                              {cs.mode === "idle" && (
                                <button
                                  type="button"
                                  onClick={() => patchConsumeState(p.candidate.wineKey, { mode: "confirm", qty: 1, remainingQty: effectiveQty })}
                                  className="flex items-center gap-1.5 text-[10px] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-magenta-400)] transition"
                                >
                                  <MinusCircle className="size-3.5" strokeWidth={2} />
                                  {labels.consumeBtn}
                                </button>
                              )}

                              {cs.mode === "confirm" && (
                                <div className="flex items-center gap-2 flex-wrap">
                                  <input
                                    type="number"
                                    min={1}
                                    max={effectiveQty}
                                    value={cs.qty}
                                    onChange={(e) =>
                                      patchConsumeState(p.candidate.wineKey, {
                                        qty: Math.max(1, Math.min(effectiveQty, Number.parseInt(e.target.value, 10) || 1)),
                                      })
                                    }
                                    className="w-14 px-1.5 py-0.5 rounded bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-xs font-mono text-[color:var(--color-fg)] focus:outline-none focus:border-[color:var(--color-magenta-400)]"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => doConsume(p.candidate.wineKey, cs.qty)}
                                    className="text-[10px] px-2 py-0.5 rounded bg-[color:var(--color-magenta-700)] text-[color:var(--color-ivory-100)] hover:bg-[color:var(--color-magenta-600)] transition"
                                  >
                                    {labels.consumeConfirm}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => patchConsumeState(p.candidate.wineKey, { mode: "idle" })}
                                    className="text-[10px] text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] transition"
                                  >
                                    {labels.consumeCancel}
                                  </button>
                                </div>
                              )}

                              {cs.mode === "loading" && (
                                <Loader2 className="size-3.5 animate-spin text-[color:var(--color-fg-muted)]" />
                              )}

                              {cs.mode === "done" && (
                                <span className="flex items-center gap-1.5 text-[10px] text-[color:var(--color-accent)]">
                                  <CheckCircle2 className="size-3.5" strokeWidth={2.5} />
                                  {labels.consumeSuccess}
                                  {cs.remainingQty > 0 && (
                                    <span className="text-[color:var(--color-fg-muted)] font-mono">
                                      ×{cs.remainingQty} restant{cs.remainingQty > 1 ? "s" : ""}
                                    </span>
                                  )}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
