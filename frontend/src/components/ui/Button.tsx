"use client";

import React from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "critical";
type ButtonSize = "sm" | "md";

const BASE =
  "inline-flex items-center justify-center gap-1.5 font-sans font-medium select-none transition-colors outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 disabled:opacity-40 disabled:pointer-events-none";

const SIZES: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-[11px]",
  md: "h-9 px-3 text-xs",
};

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent hover:bg-accent-hover text-white",
  secondary:
    "bg-surface border border-border-strong text-ink hover:bg-surface-2",
  ghost:
    "bg-transparent border border-transparent text-ink-secondary hover:text-ink hover:bg-surface",
  danger:
    "bg-surface border border-border-strong text-ink hover:bg-surface-2",
  critical:
    "bg-critical hover:bg-red-700 text-white",
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`${BASE} ${SIZES[size]} ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
