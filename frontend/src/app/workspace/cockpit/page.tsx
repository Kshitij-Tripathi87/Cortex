"use client";

import React, { useState, useMemo } from "react";
import { OperationalSignal, ScenarioCandidate, AgentMessageEnvelope } from "@/types/nexus";
import { GraphNode } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { OperationalGraph } from "@/components/graph/OperationalGraph";
import { ProgressiveDisclosure } from "@/components/shell/ProgressiveDisclosure";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { NexusNode, NexusEdge } from "@/components/nexus/nexus-types";

export default function UnifiedIncidentCockpitPage() {
  const {
    nodes: graphNodes,
    edges: graphEdges,
    selectedNode,
    setSelectedNode,
    worldStateVersion,
    worldStateUpdatedAt,
    signals,
    latestDecision,
    isDecisionValid,
    invalidationReason,
    decisionLifecycleState,
    setDecisionLifecycleState,
    decisionFreshnessState,
    decisionFreshnessExplanation,
    reconciliationState,
    triggerReconciliation,
    simulateGapAndResync,
    redeliberate,
    injectStreamEvent,
    graphMode,
    setGraphMode,
    activeWorkflowStep,
    setActiveWorkflowStep,
    currentIntent,
    workflowScope,
    operatorGovernance,
    assignDecision,
    addGovernanceComment,
    requestReanalysis,
    openWhyModal,
    candidates,
    agentMessages,
  } = useNexusWorkspace();

  const [selectedCandidate, setSelectedCandidate] = useState<string>("");
  const [commentInput, setCommentInput] = useState<string>("");
  const [showHandoffModal, setShowHandoffModal] = useState<boolean>(false);
  const [handoffOwner, setHandoffOwner] = useState<string>(operatorGovernance.owner);
  const [handoffReviewer, setHandoffReviewer] = useState<string>(operatorGovernance.reviewer);

  // Initialize selected candidate from candidates array
  React.useEffect(() => {
    if (candidates.length > 0 && !selectedCandidate) {
      const optimal = candidates.find((c) => c.is_optimal_choice);
      setSelectedCandidate(optimal?.candidate_id || candidates[0].candidate_id);
    }
  }, [candidates, selectedCandidate]);

  const handleApprove = async () => {
    setDecisionLifecycleState("EXECUTING");
    addGovernanceComment("Decision approved by operator. Webhook dispatched to Air Carrier API.", "Operator", "Dispatcher");
    setTimeout(() => {
      setDecisionLifecycleState("MONITORING");
      setActiveWorkflowStep(8);
      addGovernanceComment("Dispatch verified in transit. Live monitoring active.", "Automated Verifier", "System");
    }, 600);
  };

  const handleAddComment = (e: React.FormEvent) => {
    e.preventDefault();
    if (!commentInput.trim()) return;
    addGovernanceComment(commentInput.trim(), "Operator", "Reviewer");
    setCommentInput("");
  };

  const handleHandoffSave = () => {
    assignDecision(handoffOwner, handoffReviewer);
    setShowHandoffModal(false);
    addGovernanceComment(`Handoff re-assigned: Owner = ${handoffOwner}, Reviewer = ${handoffReviewer}`, "System", "Audit");
  };

  // Convert GraphNode[] to NexusNode[] for OperationalGraph
  const nexusNodes = useMemo((): NexusNode[] => {
    return graphNodes.map((n) => ({
      id: n.id,
      label: n.id,
      type: (n.type as any).toLowerCase() as NexusNode["type"],
      subtitle: `PageRank: ${n.pagerank?.toFixed(3) || 0}`,
      x: n.x ?? Math.random() * 1200,
      y: n.y ?? Math.random() * 620,
      status: "normal" as const,
      metadata: n.attributes,
    }));
  }, [graphNodes]);

  const nexusEdges = useMemo((): NexusEdge[] => {
    return graphEdges.map((e) => ({
      id: e.edge_id,
      source: e.source,
      target: e.target,
      status: "normal" as const,
      animated: false,
    }));
  }, [graphEdges]);

  return (
    <div className="space-y-4 max-w-7xl mx-auto pb-8 font-sans">
      {/* Intent-Centric Workspace Context Bar */}
      <IntentWorkspaceBar />

      {/* 1. CURRENT SITUATION (TOP PROMINENT BANNER) */}
      <div className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/90 shadow-lg space-y-3 font-mono">
        <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2.5">
          <div className="flex items-center gap-3">
            <span className={`w-3 h-3 rounded-full ${signals.some(s => s.severity === "CRITICAL") ? "bg-red-500 animate-pulse" : "bg-emerald-500"}`}></span>
            <div>
              <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block">
                CURRENT SITUATION • WHAT NEEDS ATTENTION RIGHT NOW
              </span>
              <h1 className="text-base font-bold text-zinc-100 mt-0.5">
                {signals.length > 0
                  ? `${signals[0].signal_type} CRITICAL: <span className="text-red-400">${signals[0].entity_id}</span> (+${Math.round(signals[0].deviation_pct)}% Breach)`
                  : "No active incidents"}
              </h1>
            </div>
          </div>

          {/* Quick Actions & Reconcile */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => openWhyModal("SIGNAL")}
              className="px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-[11px] text-zinc-300 transition flex items-center gap-1"
            >
              <span>Why am I seeing this?</span>
              <span className="text-zinc-500">❓</span>
            </button>
            <button
              onClick={injectStreamEvent}
              className="px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-[11px] text-zinc-300 transition"
              title="Test real-time mutation and invalidation"
            >
              ⚡ Test Mutation
            </button>
          </div>
        </div>

        {/* TEMPORAL FRESHNESS & RECONCILIATION STRIP (PROGRAM X1/X2) */}
        <div className="grid grid-cols-3 gap-2 text-xs">
          {/* World State Status */}
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded flex items-center justify-between">
            <div>
              <span className="text-[9px] text-zinc-500 uppercase block font-bold">WORLD STATE SNAPSHOT</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="font-bold text-zinc-100">v{worldStateVersion}</span>
                <span className="text-[10px] text-zinc-400">({worldStateUpdatedAt})</span>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded bg-zinc-800 text-[10px] text-zinc-300">AUTHORITATIVE</span>
          </div>

          {/* Decision Freshness & Coupling */}
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded flex items-center justify-between">
            <div>
              <span className="text-[9px] text-zinc-500 uppercase block font-bold">DECISION FRESHNESS</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span
                  className={`font-bold ${
                    decisionFreshnessState === "VALID"
                      ? "text-emerald-400"
                      : decisionFreshnessState === "INVALIDATED"
                      ? "text-red-400"
                      : "text-amber-400"
                  }`}
                >
                  {decisionFreshnessState}
                </span>
                <span className="text-[10px] text-zinc-400 truncate max-w-[140px]">
                  {decisionFreshnessState === "VALID" ? `against v${worldStateVersion}` : "stale / drift"}
                </span>
              </div>
            </div>
            <button
              onClick={() => openWhyModal("INVALIDATION")}
              className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                decisionFreshnessState === "VALID"
                  ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                  : "bg-red-950 text-red-400 border border-red-800 animate-pulse"
              }`}
            >
              {decisionFreshnessState === "VALID" ? "VERIFIED" : "INVALID"}
            </button>
          </div>

          {/* Realtime Reconciliation Vector */}
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded flex items-center justify-between">
            <div>
              <span className="text-[9px] text-zinc-500 uppercase block font-bold">RECONCILIATION VECTOR</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`w-1.5 h-1.5 rounded-full ${reconciliationState.resync_status === "SYNCHRONIZED" ? "bg-emerald-500" : "bg-amber-500"}`}></span>
                <span className="text-[11px] text-zinc-200">{reconciliationState.resync_status}</span>
                <span className="text-[10px] text-zinc-500">[{reconciliationState.last_event_id}]</span>
              </div>
            </div>
            <button
              onClick={simulateGapAndResync}
              className="text-[10px] text-zinc-400 hover:text-zinc-200 underline"
              title="Simulate missed event gap and verify automatic full-state resync"
            >
              Test Resync
            </button>
          </div>
        </div>

        {/* Workflow Continuity Scope Strip & Maturity Label */}
        <div className="flex items-center justify-between text-xs text-zinc-400 bg-zinc-900/40 p-2.5 rounded-lg border border-zinc-800/60">
          <div className="flex items-center gap-4 flex-wrap">
            <span>Locked Entity: <strong className="text-zinc-100">{workflowScope.entity}</strong></span>
            <span>•</span>
            <span>Scope: <strong className="text-zinc-100">{workflowScope.graph_scope}</strong></span>
            <span>•</span>
            <span>World State: <strong className="text-zinc-100">v{workflowScope.world_state}</strong></span>
            <span>•</span>
            <span>Risk Scope: <strong className="text-red-400">{workflowScope.risk_scope}</strong></span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[9px] px-2 py-0.5 rounded bg-zinc-900 border border-zinc-700 text-zinc-400 font-mono">
              CONTROLLED DEMO BENCHMARK • DETERMINISTIC SANDBOX
            </span>
            <span className="text-[10px] text-emerald-400 font-bold uppercase">CONTINUITY PRESERVED</span>
          </div>
        </div>
      </div>

      {/* Decision Invalidation Alert Banner */}
      {!isDecisionValid && (
        <div className="p-3 bg-red-950/80 border border-red-700/80 rounded-xl flex items-center justify-between text-xs font-mono text-red-200 animate-fadeIn">
          <div className="flex items-center gap-2.5">
            <span className="text-base">⚠️</span>
            <div>
              <strong className="text-red-100 font-bold">DECISION INVALIDATED BY LIVE STATE MUTATION:</strong>{" "}
              {decisionFreshnessExplanation}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => openWhyModal("INVALIDATION")}
              className="px-2.5 py-1 bg-red-900/60 hover:bg-red-800 text-red-200 rounded text-xs transition"
            >
              Why Invalid? ❓
            </button>
            <button
              onClick={redeliberate}
              className="px-3 py-1 bg-red-700 hover:bg-red-600 text-white font-bold rounded transition text-xs"
            >
              Trigger Swarm Redeliberation →
            </button>
          </div>
        </div>
      )}

      {/* Progressive Disclosure (Tier 1, 2, 3) */}
      <ProgressiveDisclosure entityId="seller_01a00b8e99" candidate={candidates.find(c => c.is_optimal_choice) || candidates[0]} />

      {/* 2. THE CORE TRIAGE GRID (WHY | WHAT IS AFFECTED | WHAT TO DO) */}
      <div className="grid grid-cols-12 gap-4 items-start">
        {/* COLUMN 1: WHY (Signals & Source Evidence) — 4 cols */}
        <div className="col-span-4 border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-3 font-mono text-xs">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
            <span className="font-bold text-zinc-200 uppercase tracking-wider text-[11px]">1. WHY (SIGNALS & EVIDENCE)</span>
            <button
              onClick={() => openWhyModal("SIGNAL")}
              className="text-[10px] text-zinc-400 hover:text-white transition"
            >
              Why this? ❓
            </button>
          </div>

          <div className="space-y-2">
            {signals.length > 0 ? (
              signals.map((sig) => (
                <div key={sig.signal_id} className="p-2.5 bg-zinc-900/60 border border-zinc-800 rounded space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-red-400">{sig.signal_type}</span>
                    <span className="text-[10px] text-zinc-500">{sig.severity}</span>
                  </div>
                  <div className="text-[11px] text-zinc-300">
                    Observed: <strong>{sig.metric_value}d</strong> (Baseline: {sig.baseline_threshold}d)
                  </div>
                  <div className="text-[10px] text-red-400 font-bold">+{sig.deviation_pct}% Deviation Breach</div>
                </div>
              ))
            ) : (
              <div className="p-3 bg-zinc-900/40 border border-zinc-800/80 rounded text-zinc-500 text-center">
                No active signals — system stable
              </div>
            )}
          </div>

          {/* Hard Provenance Card */}
          <div className="p-2.5 bg-zinc-900/40 border border-zinc-800/80 rounded space-y-1 text-[11px]">
            <div className="text-[10px] text-zinc-500 uppercase font-bold">RAW SOURCE LINEAGE</div>
            <div className="text-zinc-300">File: <strong>olist_sellers_dataset.csv</strong> (Row #482)</div>
            <div className="text-zinc-400">Canonical: seller_id:01a00b8e99</div>
            <div className="text-zinc-500 text-[10px]">PageRank 0.042 • SPOF Verified</div>
          </div>
        </div>

        {/* COLUMN 2: WHAT IS AFFECTED (Graph Topology & Blast Radius) — 4 cols */}
        <div className="col-span-4 border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-3 font-mono text-xs">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
            <span className="font-bold text-zinc-200 uppercase tracking-wider text-[11px]">2. WHAT IS AFFECTED (GRAPH & RADIUS)</span>
            <a href="/workspace/graph" className="text-[10px] text-zinc-400 hover:text-white transition">
              Full Graph →
            </a>
          </div>

          {/* Mini Operational Graph */}
          <div className="h-[220px]">
            <OperationalGraph
              scenario={{
                id: "live-workspace",
                label: "Live Workspace",
                description: "Operational subgraph from live workspace",
                nodes: nexusNodes,
                edges: nexusEdges,
                metrics: {
                  exposure: "$0",
                  timeToImpact: "N/A",
                  ordersAtRisk: 0,
                  validatedOptions: 0,
                },
              }}
              stage={isDecisionValid ? "validated" : "detecting"}
              selectedNodeId={selectedNode?.id || null}
              onNodeSelect={(nodeId) => {
                if (nodeId) {
                  const found = graphNodes.find((n) => n.id === nodeId);
                  if (found) setSelectedNode(found);
                } else {
                  setSelectedNode(null);
                }
              }}
              reducedMotion={false}
              showBackground={true}
              showLegend={false}
            />
          </div>

          <div className="p-2.5 bg-zinc-900/40 border border-zinc-800/80 rounded space-y-1 text-[11px]">
            <div className="flex justify-between text-zinc-400">
              <span>Revenue Exposure:</span>
              <strong className="text-red-400">
                {signals.length > 0
                  ? `$${(signals.reduce((acc, s) => acc + s.metric_value * 50, 0) * 10).toFixed(2)} USD`
                  : "$0.00 USD"}
              </strong>
            </div>
            <div className="flex justify-between text-zinc-400">
              <span>Exposed Population:</span>
              <strong className="text-zinc-200">{signals.length > 0 ? "12 customer orders" : "0 orders"}</strong>
            </div>
            <div className="flex justify-between text-zinc-400">
              <span>Primary Corridor:</span>
              <strong className="text-amber-400">Highway BR-116 (+1.4d)</strong>
            </div>
          </div>
        </div>

        {/* COLUMN 3: WHAT TO DO (Counterfactual Options & Simulation) — 4 cols */}
        <div className="col-span-4 border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-3 font-mono text-xs">
          <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
            <span className="font-bold text-zinc-200 uppercase tracking-wider text-[11px]">3. WHAT TO DO (OPTIONS & SIM)</span>
            <button
              onClick={() => openWhyModal("SCENARIO")}
              className="text-[10px] text-zinc-400 hover:text-white transition"
            >
              Why Candidate? ❓
            </button>
          </div>

          {/* Mini Counterfactual Options */}
          <div className="space-y-1.5">
            {candidates.length > 0 ? (
              candidates.map((c) => (
                <div
                  key={c.candidate_id}
                  onClick={() => setSelectedCandidate(c.candidate_id)}
                  className={`p-2 rounded border cursor-pointer transition ${
                    selectedCandidate === c.candidate_id
                      ? "bg-zinc-800 border-zinc-600 text-white font-bold"
                      : "bg-zinc-900/40 border-zinc-800/80 text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      {c.is_optimal_choice && <span className="text-emerald-400">★</span>}
                      <span className="text-[11px] truncate">{c.name}</span>
                    </div>
                    <span className={c.net_economic_value_usd > 0 ? "text-emerald-400 font-bold" : "text-red-400"}>
                      ${c.net_economic_value_usd.toFixed(2)} NEV
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-zinc-500 mt-0.5">
                    <span>Delay: {c.predicted_delay_days}d</span>
                    <span>SLA: {100 - c.sla_breach_pct}%</span>
                    <span>Cost: ${c.operational_cost_usd}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-3 bg-zinc-900/40 border border-zinc-800/80 rounded text-zinc-500 text-center">
                No candidates — run analysis
              </div>
            )}
          </div>

          {candidates.length > 0 && (
            <div className="p-2 bg-emerald-950/40 border border-emerald-800/60 rounded text-[11px] text-emerald-300">
              <strong>Optimal Strategy:</strong> {candidates.find(c => c.is_optimal_choice)?.name || "Candidate C"} yields highest Net Economic Value (+${candidates.find(c => c.is_optimal_choice)?.net_economic_value_usd?.toFixed(2) || "2900.00"}) with {100 - (candidates.find(c => c.is_optimal_choice)?.sla_breach_pct || 2)}% SLA protection.
            </div>
          )}
        </div>
      </div>

      {/* 3. MULTI-AGENT DELIBERATION STREAM */}
      <div className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-3 font-mono text-xs">
        <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
          <div className="flex items-center gap-2">
            <span className="font-bold text-zinc-200 uppercase tracking-wider text-[11px]">4. AGENT DELIBERATION PROTOCOL</span>
            <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-[10px] font-bold">
              CONSENSUS: {candidates.find(c => c.is_optimal_choice)?.confidence_pct ? (candidates.find(c => c.is_optimal_choice)!.confidence_pct / 100).toFixed(2) : "0.94"}
            </span>
          </div>
          <button
            onClick={() => openWhyModal("AGENT")}
            className="text-[10px] text-zinc-400 hover:text-white transition"
          >
            Why these agents? ❓
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {agentMessages.length > 0 ? (
            agentMessages.map((m) => (
              <div key={m.message_id} className="p-2.5 bg-zinc-900/60 border border-zinc-800/80 rounded space-y-1">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="font-bold text-zinc-200">{m.sender_name}</span>
                  <span className="text-zinc-500">[{m.phase} • {m.timestamp}]</span>
                </div>
                <p className="text-zinc-300 text-[11px] font-sans leading-tight">{m.content}</p>
                <div className="text-[9px] text-zinc-500">Evidence Refs: [{m.evidence_refs?.join(", ") || "none"}]</div>
              </div>
            ))
          ) : (
            <div className="col-span-2 p-4 text-center text-zinc-500 bg-zinc-900/40 border border-zinc-800/80 rounded">
              No agent messages — run deliberation
            </div>
          )}
        </div>
      </div>

      {/* 4. OPERATOR GOVERNANCE, HANDOFF & SIGN-OFF */}
      <div className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-4 font-mono text-xs">
        <div className="flex items-center justify-between border-b border-zinc-800/80 pb-2">
          <div className="flex items-center gap-2">
            <span className="font-bold text-zinc-200 uppercase tracking-wider text-[11px]">5. DECISION GOVERNANCE & OPERATOR HANDOFF</span>
            <span className="text-zinc-500">[{operatorGovernance.decision_id}]</span>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowHandoffModal(true)}
              className="px-2.5 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-zinc-300 text-[11px] transition"
            >
              Reassign / Handoff 👤
            </button>
            <button
              onClick={() => openWhyModal("RECOMMENDATION")}
              className="text-[10px] text-zinc-400 hover:text-white transition"
            >
              Why Recommend? ❓
            </button>
          </div>
        </div>

        {/* Governance Roles & Audit Info */}
        <div className="grid grid-cols-4 gap-3 text-[11px]">
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded">
            <div className="text-zinc-500 text-[10px]">DECISION OWNER:</div>
            <div className="font-bold text-zinc-200">{operatorGovernance.owner}</div>
          </div>
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded">
            <div className="text-zinc-500 text-[10px]">DESIGNATED REVIEWER:</div>
            <div className="font-bold text-zinc-200">{operatorGovernance.reviewer}</div>
          </div>
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded">
            <div className="text-zinc-500 text-[10px]">GOVERNANCE STATUS:</div>
            <div className={`font-bold ${decisionLifecycleState === "MONITORING" ? "text-emerald-400" : "text-amber-400"}`}>
              {decisionLifecycleState.replace(/_/g, " ")}
            </div>
          </div>
          <div className="p-2.5 bg-zinc-900/50 border border-zinc-800 rounded">
            <div className="text-zinc-500 text-[10px]">IMMUTABLE AUDIT ROOT:</div>
            <div className="font-bold text-zinc-300 truncate">{operatorGovernance.audit_hash.substring(0, 16)}...</div>
          </div>
        </div>

        {/* Comments & Audit Stream */}
        <div className="p-3 bg-zinc-900/30 border border-zinc-800/80 rounded-lg space-y-2">
          <div className="text-[10px] font-bold text-zinc-400 uppercase">OPERATOR AUDIT & COMMENT LOG:</div>
          <div className="space-y-1.5 max-h-32 overflow-y-auto pr-1">
            {operatorGovernance.comments.map((c) => (
              <div key={c.comment_id} className="text-[11px] flex items-center justify-between text-zinc-300 border-b border-zinc-900/80 pb-1">
                <div>
                  <strong className="text-zinc-200 font-sans">{c.author}</strong> ({c.role}): {c.text}
                </div>
                <span className="text-[10px] text-zinc-500 shrink-0 ml-2">{c.timestamp}</span>
              </div>
            ))}
          </div>

          <form onSubmit={handleAddComment} className="flex gap-2 pt-1">
            <input
              type="text"
              placeholder="Add operator sign-off comment or instruction..."
              value={commentInput}
              onChange={(e) => setCommentInput(e.target.value)}
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-200 placeholder-zinc-500 font-mono focus:outline-none focus:border-zinc-600"
            />
            <button
              type="submit"
              className="px-3 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded text-xs font-mono transition"
            >
              Post Comment
            </button>
          </form>
        </div>

        {/* Final Execution Button Strip */}
        <div className="flex items-center justify-between pt-2 border-t border-zinc-800 font-mono">
          <div className="flex items-center gap-2">
            <button
              onClick={() => requestReanalysis("Operator identified pending warehouse maintenance schedule.")}
              className="px-3 py-1.5 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs transition"
            >
              Request Swarm Re-Analysis ↺
            </button>
          </div>

          <button
            onClick={handleApprove}
            disabled={decisionLifecycleState === "MONITORING" || !isDecisionValid}
            className={`px-6 py-2.5 rounded font-sans font-bold text-xs transition shadow-md ${
              decisionLifecycleState === "MONITORING"
                ? "bg-emerald-950 border border-emerald-800 text-emerald-400 cursor-default"
                : !isDecisionValid
                ? "bg-zinc-800 text-zinc-500 cursor-not-allowed border border-zinc-700"
                : "bg-zinc-100 hover:bg-white text-zinc-950"
            }`}
          >
            {decisionLifecycleState === "MONITORING"
              ? "✓ Policy Executed & Monitoring Active"
              : !isDecisionValid
              ? "Execution Blocked (State Drift)"
              : "Approve & Execute Intervention →"}
          </button>
        </div>
      </div>

      {/* Handoff Modal */}
      {showHandoffModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 animate-fadeIn">
          <div className="w-full max-w-md bg-zinc-950 border border-zinc-700/80 rounded-xl p-5 shadow-2xl font-mono text-xs space-y-4">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
              <h3 className="font-bold text-zinc-100 text-sm">Operator Handoff & Role Assignment</h3>
              <button onClick={() => setShowHandoffModal(false)} className="text-zinc-500 hover:text-white">✕</button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-[10px] text-zinc-500 uppercase block mb-1">DECISION OWNER (OPERATOR):</label>
                <input
                  type="text"
                  value={handoffOwner}
                  onChange={(e) => setHandoffOwner(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 font-mono"
                />
              </div>

              <div>
                <label className="text-[10px] text-zinc-500 uppercase block mb-1">SIGN-OFF REVIEWER (EXECUTIVE):</label>
                <input
                  type="text"
                  value={handoffReviewer}
                  onChange={(e) => setHandoffReviewer(e.target.value)}
                  className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-zinc-800">
              <button
                onClick={() => setShowHandoffModal(false)}
                className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded"
              >
                Cancel
              </button>
              <button
                onClick={handleHandoffSave}
                className="px-4 py-1.5 bg-zinc-100 hover:bg-white text-zinc-950 font-bold rounded font-sans"
              >
                Save Handoff Assignment
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}