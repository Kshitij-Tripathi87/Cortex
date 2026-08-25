"use client";

import React, { useState } from "react";
import Link from "next/link";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";

export default function AgentConversationsPage() {
  const [selectedConversation, setSelectedConversation] = useState<string>("conv_2026_001");

  const conversations = [
    {
      conversation_id: "conv_2026_001",
      task_id: "TASK_2026_001",
      topic: "Seller 01a00b8e99 Delay Mitigation & Air Freight Tendering",
      message_count: 6,
      created_at: "23:55:01Z",
      participants: ["Supervisor", "Procurement", "Optimization", "Booking", "Compliance"],
      audit_hash: "5a3d7611e980...sha256",
    },
    {
      conversation_id: "conv_2026_002",
      task_id: "TASK_2026_002",
      topic: "Corridor BR-116 Bottleneck Bypass & Cross-Dock Rebalance",
      message_count: 4,
      created_at: "23:58:14Z",
      participants: ["Supervisor", "Optimization", "Booking", "Compliance"],
      audit_hash: "88f921ab4201...sha256",
    },
  ];

  return (
    <div className="space-y-6 max-w-6xl mx-auto font-sans pb-10">
      <IntentWorkspaceBar />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-zinc-100 font-mono">Agent Conversation Transcripts & Audit Store</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Complete cryptographic audit trail of inter-agent deliberation dialogues with correlation tracking.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/workspace/agents/tasks"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            ← Task Graphs
          </Link>
          <Link
            href="/workspace/evidence"
            className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-xs font-mono text-zinc-300 transition"
          >
            Evidence DAG →
          </Link>
        </div>
      </div>

      <div className="space-y-3 font-mono text-xs">
        {conversations.map((c) => (
          <div key={c.conversation_id} className="p-4 bg-zinc-950/90 border border-zinc-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
              <div className="flex items-center gap-3">
                <span className="font-bold text-zinc-100">{c.conversation_id}</span>
                <span className="text-zinc-500">[{c.task_id}]</span>
              </div>
              <span className="text-[10px] text-zinc-400 font-mono">
                SHA-256: <strong className="text-zinc-300">{c.audit_hash}</strong>
              </span>
            </div>

            <p className="text-sm text-zinc-200 font-sans">{c.topic}</p>

            <div className="flex items-center justify-between text-[11px] text-zinc-400 pt-2 border-t border-zinc-800/60">
              <div className="flex items-center gap-1.5">
                <span className="text-zinc-500 font-bold">PARTICIPANTS:</span>
                {c.participants.map((p) => (
                  <span key={p} className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-300 border border-zinc-800 text-[10px]">
                    {p}
                  </span>
                ))}
              </div>
              <span className="text-zinc-500">{c.message_count} messages • {c.created_at}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
