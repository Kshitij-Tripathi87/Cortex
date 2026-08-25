import React from "react";

interface PanelProps {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}

export function Panel({
  title,
  actions,
  className = "",
  bodyClassName = "",
  children,
}: PanelProps) {
  return (
    <section
      className={`border border-border bg-surface ${className}`}
    >
      {title && (
        <header className="flex items-center justify-between border-b border-border px-4 h-10">
          <h2 className="font-sans text-[11px] font-bold uppercase tracking-wider text-ink-secondary">
            {title}
          </h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`p-4 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
