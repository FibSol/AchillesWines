import { ShieldCheck, Eye, AlertCircle } from "lucide-react";

export type Confidence = "verified" | "reviewed" | "needs_review";

export function deriveConfidence(sourceCount: number): Confidence {
  if (sourceCount >= 3) return "verified";
  if (sourceCount >= 1) return "reviewed";
  return "needs_review";
}

export interface ConfidenceLabels {
  verified: string;
  reviewed: string;
  needs_review: string;
}

interface Props {
  confidence: Confidence;
  sourceCount?: number;
  labels: ConfidenceLabels;
  size?: "sm" | "md";
  iconOnly?: boolean;
  className?: string;
}

export function ConfidenceBadge({
  confidence,
  sourceCount,
  labels,
  size = "md",
  iconOnly = false,
  className = "",
}: Props) {
  const Icon = confidence === "verified" ? ShieldCheck : confidence === "reviewed" ? Eye : AlertCircle;
  const cls =
    confidence === "verified"
      ? "badge badge-verified"
      : confidence === "reviewed"
        ? "badge badge-reviewed"
        : "badge badge-needs-review";
  const sizeCls = size === "sm" ? "text-[10px] py-0.5 px-1.5" : "text-xs";
  const iconSize = size === "sm" ? "size-2.5" : "size-3";

  const fullText =
    confidence === "verified"
      ? labels.verified.replace("{count}", String(sourceCount ?? 0))
      : confidence === "reviewed"
        ? labels.reviewed
        : labels.needs_review;

  const title = iconOnly
    ? fullText
    : sourceCount !== undefined && confidence !== "verified"
      ? `${fullText} · ${sourceCount} ${sourceCount === 1 ? "source" : "sources"}`
      : fullText;

  return (
    <span className={`${cls} ${sizeCls} ${className}`} title={title} aria-label={title}>
      <Icon className={iconSize} strokeWidth={2.5} />
      {!iconOnly && <span>{fullText}</span>}
    </span>
  );
}
