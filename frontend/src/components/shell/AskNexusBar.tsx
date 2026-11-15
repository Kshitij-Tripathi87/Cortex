"use client";

import React, { useState } from "react";
import Link from "next/link";
import { askVanessa, VanessaResponse } from "@/lib/api/nexusClient";
import { useAuth } from "@/lib/auth";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export const AskNexusBar: React.FC = () => {
  const { setGraphMode } = useNexusWorkspace();
  const { workspace } = useAuth();
  const workspaceId = workspace?.id ?? "";

  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<VanessaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAsk = async (queryText?: string) => {
    const q = queryText || query;
    if (!q.trim() || !workspaceId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await askVanessa(workspaceId, q);
      setAnswer(res);
      // A denied tool is a real, user-visible outcome — surface it rather
      // than rendering an empty answer.
      if (res.permission_denied) {
        setError(`Permission denied: ${res.permission_denied}`);
      }
    } catch (err) {
      setAnswer(null);
      setError(err instanceof Error ? err.message : "The request failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full space-y-4">
      {/* Input Bar */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask Nexus anything about your operational world..."
            className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-4 py-2.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500 font-mono"
            onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          />
        </div>
        <button
          onClick={() => handleAsk()}
          disabled={loading || !workspaceId}
          className="px-4 py-2.5 rounded-lg bg-zinc-100 hover:bg-white text-zinc-950 font-semibold text-xs transition disabled:opacity-50 font-sans"
        >
          {loading ? "Reasoning..." : "Execute Reasoning"}
        </button>
      </div>

      {/* Failure state — an API failure must never look like success */}
      {error && (
        <div
          role="alert"
          className="border border-red-900/60 bg-red-950/30 rounded-xl px-4 py-3 text-xs text-red-300 font-mono"
        >
          {error}
        </div>
      )}

      {/* Canonical answer */}
      {answer && (
        <div className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/40 space-y-4 animate-in fade-in duration-200">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-2.5">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span className="text-xs font-mono font-semibold text-emerald-400">
                {answer.intent.toUpperCase()}
              </span>
            </div>
            <div className="text-[11px] font-mono text-zinc-500">
              {answer.world_state_version != null
                ? `WORLD STATE v${answer.world_state_version}`
                : "WORLD STATE v—"}
            </div>
          </div>

          <div>
            <p className="text-sm text-zinc-100 leading-relaxed whitespace-pre-wrap">
              {answer.response}
            </p>
          </div>

          {/* Tools that actually ran */}
          {answer.actions_taken.length > 0 && (
            <div>
              <div className="text-[10px] font-mono text-zinc-500 uppercase mb-2">
                TOOLS EXECUTED
              </div>
              <div className="flex flex-wrap gap-2">
                {answer.actions_taken.map((action, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-1 bg-zinc-950 border border-zinc-800 rounded text-[10px] font-mono text-zinc-300"
                  >
                    {action}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Grounded evidence — rendered from the server's records, not synthesised */}
          {answer.evidence.length > 0 && (
            <div>
              <div className="text-[10px] font-mono text-zinc-500 uppercase mb-2">
                GROUNDED EVIDENCE ({answer.evidence.length})
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                {answer.evidence.map((item, idx) => {
                  const tool = typeof item.tool === "string" ? item.tool : `evidence_${idx + 1}`;
                  const data = item.data;
                  const summary =
                    data && typeof data === "object"
                      ? Object.entries(data as Record<string, unknown>)
                          .slice(0, 4)
                          .map(
                            ([key, value]) =>
                              `${key}: ${
                                value && typeof value === "object"
                                  ? JSON.stringify(value)
                                  : String(value)
                              }`,
                          )
                          .join(" · ")
                      : String(data ?? "");
                  return (
                    <div
                      key={idx}
                      className="p-2.5 bg-zinc-950 border border-zinc-800 rounded-lg space-y-1"
                    >
                      <div className="text-[9px] font-mono text-zinc-500 uppercase">{tool}</div>
                      <div className="text-[11px] font-mono text-zinc-300 break-words">
                        {summary || "—"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Trace reference + navigation */}
          <div className="pt-2 border-t border-zinc-800 flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
            <div className="flex items-center gap-2">
              <Link
                href="/workspace/graph"
                onClick={() => setGraphMode("EVIDENCE")}
                className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-[11px] transition"
              >
                [View in Graph]
              </Link>
              <Link
                href="/workspace/evidence"
                className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-[11px] transition"
              >
                [Trace Evidence Lineage]
              </Link>
              <Link
                href="/workspace/scenarios"
                className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-[11px] transition"
              >
                [Run Counterfactual Simulation]
              </Link>
            </div>
            {answer.trace_id && (
              <span className="text-[10px] text-zinc-500">
                TRACE {answer.trace_id.slice(0, 18)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
