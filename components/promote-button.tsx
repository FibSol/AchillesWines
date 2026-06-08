"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

interface PromoteResult {
  promoted: number;
  pending: number;
  totalFactPrice: number;
}

export function PromoteButton() {
  const t = useTranslations("quality");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PromoteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handlePromote = async () => {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await fetch("/api/promote", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PromoteResult = await res.json();
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Promotion failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-4">
      <button
        onClick={handlePromote}
        disabled={loading}
        className="inline-flex items-center gap-2 rounded-lg bg-[color:var(--color-accent)] px-4 py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} strokeWidth={2} />
        {loading ? t("promoteRunning") : t("promoteBtn")}
      </button>
      {result && (
        <p className="text-sm text-[color:var(--color-fg-muted)]">
          <span className="font-semibold text-emerald-400">
            {t("promoteSuccess", { count: result.promoted })}
          </span>{" "}
          ·{" "}
          <span className="font-semibold text-[color:var(--color-fg)]">
            {result.pending.toLocaleString()}
          </span>{" "}
          {t("promotePending")} ·{" "}
          <span className="text-[color:var(--color-fg-subtle)]">
            {result.totalFactPrice.toLocaleString()} {t("promoteTotal")}
          </span>
        </p>
      )}
      {error && (
        <p className="text-sm text-red-400">{error}</p>
      )}
    </div>
  );
}
