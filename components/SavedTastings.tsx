"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { BookmarkCheck, GlassWater, Trash2, Check } from "lucide-react";
import { COLOR_DOT } from "@/components/TastingStudio";

interface SessionWine {
  wineKey: string;
  position: number;
  personalScore: number | null;
  consumedAt: string | null;
  producerName: string;
  cuveeName: string;
  vintage: number | null;
  color: string;
}

interface Session {
  sessionId: number;
  mode: string;
  createdAt: string;
  wines: SessionWine[];
}

/**
 * Saved tastings: rate each wine (/100) and remove the tasted bottles from
 * the cellar in one click. `refreshToken` bumps whenever the studio saves a
 * new session.
 */
export function SavedTastings({ refreshToken }: { refreshToken: number }) {
  const t = useTranslations("tasting");
  const locale = useLocale();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/tasting/sessions");
      if (!r.ok) return;
      const data: { sessions: Session[] } = await r.json();
      setSessions(data.sessions);
    } catch {
      /* section stays hidden */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  async function saveScore(sessionId: number, wineKey: string, score: number | null) {
    setSessions((prev) =>
      prev?.map((s) =>
        s.sessionId === sessionId
          ? {
              ...s,
              wines: s.wines.map((w) =>
                w.wineKey === wineKey ? { ...w, personalScore: score } : w,
              ),
            }
          : s,
      ) ?? null,
    );
    await fetch(`/api/tasting/sessions/${sessionId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ wines: [{ wineKey, personalScore: score }] }),
    }).catch(() => undefined);
  }

  async function removeFromCellar(sessionId: number) {
    setBusy(sessionId);
    try {
      await fetch(`/api/tasting/sessions/${sessionId}/consume`, { method: "POST" });
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function deleteSession(sessionId: number) {
    setBusy(sessionId);
    try {
      await fetch(`/api/tasting/sessions/${sessionId}`, { method: "DELETE" });
      await load();
    } finally {
      setBusy(null);
    }
  }

  if (!sessions || sessions.length === 0) return null;

  return (
    <section>
      <h2 className="flex items-center gap-2 text-xs uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)] mb-3">
        <BookmarkCheck className="size-3.5" strokeWidth={2.5} />
        {t("sessions.title")}
      </h2>
      <div className="space-y-3">
        {sessions.map((s) => {
          const pending = s.wines.filter((w) => w.consumedAt === null).length;
          const date = new Date(s.createdAt).toLocaleDateString(locale, {
            day: "numeric",
            month: "long",
            year: "numeric",
          });
          return (
            <div key={s.sessionId} className="glass-card p-5">
              <div className="flex flex-wrap items-center gap-3 mb-3">
                <span className="font-semibold text-sm text-[color:var(--color-fg)]">
                  {t(`modes.${s.mode}.name`)}
                </span>
                <span className="font-mono text-[11px] text-[color:var(--color-fg-subtle)]">
                  {date}
                </span>
                <span className="flex-1" />
                {pending > 0 && (
                  <button
                    onClick={() => removeFromCellar(s.sessionId)}
                    disabled={busy === s.sessionId}
                    className="btn btn-ghost text-xs"
                  >
                    <GlassWater className="size-3.5" strokeWidth={2.5} />
                    {t("sessions.removeAll")}
                  </button>
                )}
                <button
                  onClick={() => deleteSession(s.sessionId)}
                  disabled={busy === s.sessionId}
                  title={t("sessions.delete")}
                  aria-label={t("sessions.delete")}
                  className="p-1.5 rounded-md text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-primary)] hover:bg-[color:var(--color-primary-tint)] transition"
                >
                  <Trash2 className="size-3.5" strokeWidth={2.5} />
                </button>
              </div>

              <ul className="divide-y divide-[color:var(--color-border)]">
                {s.wines.map((w) => (
                  <li key={w.wineKey} className="flex items-center gap-3 py-2">
                    <span className="font-mono text-[11px] text-[color:var(--color-fg-subtle)] w-4 text-right shrink-0">
                      {w.position}
                    </span>
                    <span
                      className="inline-block size-2 rounded-full shrink-0"
                      style={{ background: COLOR_DOT[w.color] ?? "#FAF7F5" }}
                    />
                    <span className="flex-1 min-w-0 text-sm text-[color:var(--color-fg)] truncate">
                      {w.producerName} — {w.cuveeName}
                      {w.vintage !== null && (
                        <span className="ml-1.5 font-mono text-[color:var(--color-fg-muted)]">
                          {w.vintage}
                        </span>
                      )}
                    </span>
                    {w.consumedAt !== null && (
                      <span
                        className="flex items-center gap-1 font-mono text-[10px] uppercase text-[color:var(--color-accent)] shrink-0"
                        title={t("sessions.removedBadge")}
                      >
                        <Check className="size-3" strokeWidth={2.5} />
                        {t("sessions.removedBadge")}
                      </span>
                    )}
                    <label className="flex items-center gap-1.5 shrink-0">
                      <span className="text-[10px] uppercase tracking-[0.06em] text-[color:var(--color-fg-subtle)]">
                        {t("sessions.yourScore")}
                      </span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={w.personalScore ?? ""}
                        onChange={(e) => {
                          const v = e.target.value;
                          const score = v === "" ? null : Math.max(0, Math.min(100, Number.parseInt(v, 10)));
                          void saveScore(s.sessionId, w.wineKey, Number.isNaN(score as number) ? null : score);
                        }}
                        placeholder="–"
                        className="w-16 px-2 py-1 rounded bg-[color:var(--color-input-bg)] border border-[color:var(--color-border)] text-xs font-mono text-[color:var(--color-fg)] placeholder:text-[color:var(--color-fg-subtle)] focus:outline-none focus:border-[color:var(--color-primary)]"
                      />
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}
