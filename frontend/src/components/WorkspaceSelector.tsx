"use client";

/**
 * Workspace selector — dropdown to switch active workspace.
 */

import { useState } from "react";
import { useWorkspace } from "@/lib/useWorkspace";

export function WorkspaceSelector() {
  const [workspaceId, setWorkspaceId] = useWorkspace();
  const [open, setOpen] = useState(false);
  const [customWs, setCustomWs] = useState("");

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center px-3 py-1.5 bg-slate-800 text-slate-100 text-sm rounded hover:bg-slate-700"
      >
        <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
        <span className="font-mono text-xs">{workspaceId}</span>
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 mt-2 w-64 bg-white rounded-lg shadow-lg border border-gray-200 z-20">
            <div className="p-3 border-b border-gray-100">
              <p className="text-xs text-gray-500 mb-2">Switch Workspace</p>
              <input
                type="text"
                value={customWs}
                onChange={(e) => setCustomWs(e.target.value)}
                placeholder="Enter workspace ID"
                className="w-full px-3 py-1.5 text-sm border rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button
                onClick={() => {
                  if (customWs.trim()) {
                    setWorkspaceId(customWs.trim());
                    setCustomWs("");
                    setOpen(false);
                  }
                }}
                className="mt-2 w-full px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
              >
                Set Workspace
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
