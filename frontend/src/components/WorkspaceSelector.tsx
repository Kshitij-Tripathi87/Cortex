"use client";

/**
 * Workspace selector — dropdown to switch active workspace.
 */

import { useAuth } from "@/lib/auth";

export function WorkspaceSelector() {
  const { workspace } = useAuth();
  const workspaceLabel = workspace?.name ?? workspace?.id ?? "No workspace";

  return (
    <div className="flex items-center px-3 py-1.5 bg-slate-800 text-slate-100 text-sm rounded">
        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
        <span className="font-mono text-xs" title={workspace?.id}>{workspaceLabel}</span>
    </div>
  );
}
