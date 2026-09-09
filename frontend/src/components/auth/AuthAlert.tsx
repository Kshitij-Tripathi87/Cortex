/**
 * Form-level status banner. `tone=error` for failures, `tone=info` for
 * neutral states (rate limit uses warning copy but this visual).
 */

import React from "react";

export function AuthAlert({
  tone,
  children,
  testId,
}: {
  tone: "error" | "info" | "success";
  children: React.ReactNode;
  testId: string;
}) {
  const classes =
    tone === "error"
      ? "bg-critical-subtle border-critical text-ink"
      : tone === "success"
        ? "bg-accent-subtle border-accent text-ink"
        : "bg-surface-2 border-border-strong text-ink-secondary";
  return (
    <div data-testid={testId} role={tone === "error" ? "alert" : "status"} className={`border px-3 py-2.5 text-sm ${classes}`}>
      {children}
    </div>
  );
}
