import React from "react";

interface SectionHeaderProps {
  index?: number | string;
  title: React.ReactNode;
  hint?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

export function SectionHeader({
  index,
  title,
  hint,
  actions,
  className = "",
}: SectionHeaderProps) {
  return (
    <div
      className={`flex items-center justify-between border-b border-border pb-2 ${className}`}
    >
      <div className="flex items-center gap-2">
        {index !== undefined && (
          <span className="font-mono text-[10px] text-ink-muted">
            {index}.
          </span>
        )}
        <h3 className="font-sans text-[11px] font-bold uppercase tracking-wider text-ink">
          {title}
        </h3>
        {hint && <span className="font-mono text-[10px] text-ink-muted">{hint}</span>}
      </div>
      <div className="flex items-center gap-2">
        {actions}
      </div>
    </div>
  );
}
