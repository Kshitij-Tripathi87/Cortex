/**
 * Centered card shell for /auth/* pages. Square Nexus geometry, dark tokens.
 */

import React from "react";

export function AuthShell({
  title,
  subtitle,
  children,
  testId,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <div data-testid={testId} className="min-h-screen bg-bg text-ink flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-surface border border-border p-8">
        <div className="mb-6">
          <p className="font-mono text-xs text-accent tracking-widest mb-2">NEXUS</p>
          <h1 className="text-xl font-semibold">{title}</h1>
          <p className="text-sm text-ink-secondary mt-1">{subtitle}</p>
        </div>
        {children}
      </div>
    </div>
  );
}
