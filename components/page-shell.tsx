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
    <div className="space-y-10">
      <header className="space-y-3">
        {badge && <p className="micro-label">{badge}</p>}
        <h1 className="display-xl">{title}</h1>
        {subtitle && (
          <p className="text-base text-[color:var(--color-fg-muted)] max-w-2xl">{subtitle}</p>
        )}
      </header>
      {children}
    </div>
  );
}

export function ComingSoon({ feature, ownerRole }: { feature: string; ownerRole: string }) {
  return (
    <div className="glass-card p-12 flex flex-col items-center justify-center text-center">
      <h3 className="text-2xl">Bientôt</h3>
      <p className="mt-3 text-[color:var(--color-fg-muted)] max-w-md">{feature}</p>
      <p className="mt-6 text-xs text-[color:var(--color-fg-subtle)] font-mono">
        owner: {ownerRole}
      </p>
    </div>
  );
}
