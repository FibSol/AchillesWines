"use client";

import { useState } from "react";
import { ShoppingBag, Check } from "lucide-react";

interface Props {
  prompt: string;
}

export function ShopButton({ prompt }: Props) {
  const [copied, setCopied] = useState(false);

  const handleClick = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
    } catch {
      // clipboard unavailable — user can still use Claude manually
    }
    window.open("https://claude.ai/new", "_blank", "noopener,noreferrer");
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      title="Copie le prompt caviste et ouvre Claude"
      className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-all duration-200 whitespace-nowrap ${
        copied
          ? "border-[color:var(--color-success)] text-[color:var(--color-success)] bg-[rgba(34,197,94,0.08)]"
          : "border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] hover:border-[color:var(--color-magenta-400)] hover:text-[color:var(--color-magenta-400)]"
      }`}
    >
      {copied ? (
        <Check className="size-3 shrink-0" strokeWidth={2.5} />
      ) : (
        <ShoppingBag className="size-3 shrink-0" strokeWidth={2} />
      )}
      {copied ? "Copié !" : "Shop"}
    </button>
  );
}
