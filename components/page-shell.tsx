import { Sparkles } from "lucide-react";

export function PageShell({
  title,
  subtitle,
  badge,
  children,
}: {
  title: string;
  subtitle?: string;
  badge?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        {badge && (
          <p className="badge badge-verified w-fit">
            <Sparkles className="size-3" strokeWidth={2.5} />
            <span>{badge}</span>
          </p>
        )}
        <h1 className="display-xl">
          <span className="text-gradient">{title}</span>
        </h1>
        {subtitle && (
          <p className="text-lg text-[color:var(--color-fg-muted)] max-w-2xl">{subtitle}</p>
        )}
      </header>
      {children}
    </div>
  );
}

export function ComingSoon({ feature, ownerRole }: { feature: string; ownerRole: string }) {
  return (
    <div className="glass-card p-12 flex flex-col items-center justify-center text-center">
      <div className="size-16 rounded-full bg-[rgba(165,56,96,0.1)] flex items-center justify-center mb-6">
        <Sparkles className="size-7 text-[color:var(--color-champagne-400)]" strokeWidth={2} />
      </div>
      <h3 className="text-2xl font-display">Bientôt</h3>
      <p className="mt-3 text-[color:var(--color-fg-muted)] max-w-md">{feature}</p>
      <p className="mt-6 text-xs text-[color:var(--color-fg-subtle)] font-mono">
        owner: {ownerRole}
      </p>
    </div>
  );
}
