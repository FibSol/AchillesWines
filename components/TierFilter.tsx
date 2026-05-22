"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { TIER_DEFS, DEFAULT_TIERS } from "@/lib/map-tiers";

export { TIER_DEFS, DEFAULT_TIERS };

type Props = { selected: string[] };

export function TierFilter({ selected }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const toggle = (key: string) => {
    const next = new Set(selected);
    next.has(key) ? next.delete(key) : next.add(key);
    const params = new URLSearchParams(searchParams.toString());
    const value = Array.from(next).join(",");
    if (value) {
      params.set("tiers", value);
    } else {
      params.delete("tiers");
    }
    router.push(`${pathname}?${params.toString()}`);
  };

  const selectAll = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tiers", TIER_DEFS.map((t) => t.key).join(","));
    router.push(`${pathname}?${params.toString()}`);
  };

  const reset = () => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tiers", DEFAULT_TIERS.join(","));
    router.push(`${pathname}?${params.toString()}`);
  };

  const isAll = TIER_DEFS.every((t) => selected.includes(t.key));
  const isDefault =
    selected.length === DEFAULT_TIERS.length &&
    DEFAULT_TIERS.every((t) => selected.includes(t));

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-[color:var(--color-fg-subtle)] font-mono uppercase tracking-wider shrink-0">
        Tier
      </span>
      {TIER_DEFS.map(({ key, label, color, desc }) => {
        const active = selected.includes(key);
        return (
          <button
            key={key}
            onClick={() => toggle(key)}
            title={desc}
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold transition-all border"
            style={{
              borderColor: color,
              color: active ? color : "var(--color-fg-subtle)",
              background: active ? `${color}18` : "transparent",
              opacity: active ? 1 : 0.45,
            }}
          >
            <span
              className="inline-block size-1.5 rounded-full shrink-0"
              style={{ background: color }}
            />
            {label}
          </button>
        );
      })}
      <div className="w-px h-4 bg-[color:var(--color-border)] mx-1" />
      {!isAll && (
        <button
          onClick={selectAll}
          className="text-xs text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg)] transition-colors font-mono"
        >
          all
        </button>
      )}
      {!isDefault && (
        <button
          onClick={reset}
          className="text-xs text-[color:var(--color-fg-subtle)] hover:text-[color:var(--color-fg)] transition-colors font-mono"
        >
          reset
        </button>
      )}
    </div>
  );
}
