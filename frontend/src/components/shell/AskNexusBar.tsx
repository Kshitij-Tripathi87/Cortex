"use client";

import React, { useState } from "react";
import Link from "next/link";
import { askNexusQuestion } from "@/lib/api/nexusClient";
import { EvidenceAnswer } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";

export const AskNexusBar: React.FC = () => {
  const { setGraphMode } = useNexusWorkspace();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<EvidenceAnswer | null>(null);

  const handleAsk = async (queryText?: string) => {
    const q = queryText || query;
    if (!q.trim()) return;
    setLoading(true);
    try {
      const res = await askNexusQuestion(q);
      if (res.answer) {
        setAnswer(res.answer);
      }
    } catch (err) {
      console.error(err);
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
          disabled={loading}
          className="px-4 py-2.5 rounded-lg bg-zinc-100 hover:bg-white text-zinc-950 font-semibold text-xs transition disabled:opacity-50 font-sans"
        >
          {loading ? "Reasoning..." : "Execute Reasoning"}
        </button>
      </div>

      {/* Answer Output */}
      {answer && (
        <div className="border border-zinc-800 rounded-xl p-5 bg-zinc-900/40 space-y-4 animate-in fade-in duration-200">
          <div className="flex items-center justify-between border-b border-zinc-800 pb-2.5">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span className="text-xs font-mono font-semibold text-emerald-400">
                ANSWERABLE (Evidence Confidence: {(answer.confidence_score * 100).toFixed(0)}%)
              </span>
            </div>
            <div className="text-[11px] font-mono text-zinc-500">
              SHA-256: {answer.checksum_sha256.substring(0, 10)}...
            </div>
          </div>

          <div>
            <h4 className="text-sm font-bold text-zinc-100">{answer.summary_finding}</h4>
            <ul className="mt-2 space-y-1 text-xs text-zinc-300">
              {answer.key_reasons.map((reason, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="text-zinc-500 font-mono">•</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Citations */}
          <div>
            <div className="text-[10px] font-mono text-zinc-500 uppercase mb-2">GROUNDED EVIDENCE CITATIONS</div>
            <div className="grid grid-cols-3 gap-2.5">
              {answer.citations.map((cit) => (
                <div key={cit.citation_id} className="p-2.5 bg-zinc-950 border border-zinc-800 rounded-lg space-y-0.5">
                  <div className="text-[9px] font-mono text-zinc-500 uppercase">{cit.source_type}</div>
                  <div className="text-xs font-semibold text-zinc-200">{cit.label}</div>
                  <div className="text-[11px] font-mono text-emerald-400">{cit.value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Cross-Feature Action Chips */}
          <div className="pt-2 border-t border-zinc-800 flex items-center justify-between text-xs font-mono">
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
            <span className="text-emerald-400 font-bold">
              NET ECONOMIC ROI: +${answer.recommended_action?.net_economic_value_usd?.toFixed(2)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};
