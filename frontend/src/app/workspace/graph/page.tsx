"use client";

import React, { useState, useMemo } from "react";
import { GraphNode, GraphEdge, GraphMode } from "@/types/nexus";
import { useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { OperationalGraphAuto } from "@/components/graph/OperationalGraphCanvas";
import { IntentWorkspaceBar } from "@/components/shell/IntentWorkspaceBar";
import { ProgressiveDisclosure } from "@/components/shell/ProgressiveDisclosure";
import { NexusNode, NexusEdge } from "@/components/nexus/nexus-types";

export default function OperationalGraphPage() {
  const {
    nodes: graphNodes,
    edges: graphEdges,
    selectedNode,
    setSelectedNode,
    nodesCount,
    edgesCount,
    relationshipCoveragePct,
    graphMode,
    setGraphMode,
    selectedCandidateId,
    getEntityLineage,
    launchIntent,
    benchmarkScale,
    worldStateVersion,
    graphVersion,
  } = useNexusWorkspace();

  const [searchQuery, setSearchQuery] = useState("");
  const [hops, setHops] = useState<number>(2);

  const lineage = selectedNode ? getEntityLineage(selectedNode.id) : null;

  const filteredNodes = graphNodes.filter((n) =>
    n.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    n.type.toLowerCase().includes(searchQuery.toLowerCase())
  );

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
    <div className="space-y-4 max-w-7xl mx-auto pb-8">
      {/* Intent-Centric Workspace Context Bar */}
      <IntentWorkspaceBar />

      {/* Top Header & Graph Modes */}
      <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
        <div>
          <h1 className="text-base font-bold text-zinc-100 font-mono tracking-tight">
            OPERATIONAL GRAPH TOPOLOGY
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Live operational subgraph from World State v{worldStateVersion} • Graph {graphVersion}
          </p>
        </div>

        {/* 6 Overlay Modes */}
        <div className="flex items-center gap-1 bg-zinc-950 p-1 rounded-lg border border-zinc-800">
          {(["WORLD", "RISK", "DEPENDENCY", "INCIDENT", "SCENARIO", "EVIDENCE"] as GraphMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setGraphMode(mode)}
              className={`px-2.5 py-1 rounded text-xs font-mono transition ${
                graphMode === mode
                  ? "bg-zinc-800 text-zinc-100 font-bold border border-zinc-700"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      {/* Main 3-Column Layout */}
      <div className="grid grid-cols-12 gap-4 items-start">
        {/* Left Filter & Search Column (3 cols) */}
        <div className="col-span-3 border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-4 text-xs font-mono">
          <div className="space-y-1.5">
            <div className="font-bold text-zinc-300 uppercase text-[10px]">SEARCH ENTITY / ID</div>
            <input
              type="text"
              placeholder="Search node..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-200 placeholder-zinc-500 font-mono focus:outline-none focus:border-zinc-500"
            />
          </div>

          {/* Quick Node List */}
          <div className="space-y-1 max-h-48 overflow-y-auto">
            <div className="text-[10px] text-zinc-500 uppercase font-bold">MATCHING NODES ({filteredNodes.length})</div>
            {filteredNodes.map((n) => (
              <button
                key={n.id}
                onClick={() => setSelectedNode(n)}
                className={`w-full p-2 rounded text-left flex items-center justify-between transition ${
                  selectedNode?.id === n.id ? "bg-zinc-800 text-white font-bold" : "bg-zinc-900/40 text-zinc-400 hover:bg-zinc-900"
                }`}
              >
                <span className="truncate">{n.id}</span>
                <span className="text-[9px] text-zinc-500">{n.type}</span>
              </button>
            ))}
          </div>

          <div className="pt-2 border-t border-zinc-800 space-y-1">
            <div className="font-bold text-zinc-400 uppercase text-[10px]">GRAPH SCALE BENCHMARK</div>
            <div className="text-[11px] text-zinc-300">Scale: <strong className="text-emerald-400">{benchmarkScale.toLocaleString()} nodes</strong></div>
            <div className="text-[10px] text-zinc-500">Coverage: {relationshipCoveragePct}% relationships</div>
          </div>
        </div>

        {/* Center Canvas Viewport (6 cols) */}
        <div className="col-span-6 space-y-3">
          <OperationalGraphAuto
            scenario={{
              id: "live-workspace",
              label: "Live Workspace Graph",
              description: `Operational subgraph from World State v${worldStateVersion}`,
              nodes: nexusNodes,
              edges: nexusEdges,
              metrics: {
                exposure: "$0",
                timeToImpact: "N/A",
                ordersAtRisk: 0,
                validatedOptions: 0,
              },
            }}
            stage="validated"
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
            showLegend={true}
          />
        </div>

        {/* Right Entity Inspector with Data Lineage & Actions (3 cols) */}
        <div className="col-span-3 border border-zinc-800 rounded-xl p-4 bg-zinc-950/80 space-y-4 text-xs font-mono">
          <div className="border-b border-zinc-800 pb-3">
            <div className="text-[10px] text-zinc-500 uppercase font-bold">INSPECTED ENTITY</div>
            <h3 className="text-sm font-bold text-zinc-100 mt-1 truncate">{selectedNode?.id || "None Selected"}</h3>
            <div className="flex items-center gap-2 mt-1">
              <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 text-[10px]">
                {selectedNode?.type || "N/A"}
              </span>
              {selectedNode?.is_spof && (
                <span className="px-2 py-0.5 rounded bg-red-950 border border-red-800 text-red-400 text-[10px] font-bold">
                  CRITICAL SPOF
                </span>
              )}
            </div>
          </div>

          <div className="space-y-2 text-[11px]">
            <div className="flex justify-between border-b border-zinc-900 pb-1 text-zinc-400">
              <span>PageRank:</span>
              <span className="font-bold text-zinc-200">{selectedNode?.pagerank || 0.0}</span>
            </div>
            <div className="flex justify-between border-b border-zinc-900 pb-1 text-zinc-400">
              <span>Betweenness:</span>
              <span className="font-bold text-zinc-200">{selectedNode?.betweenness || 0.0}</span>
            </div>
            <div className="flex justify-between border-b border-zinc-900 pb-1 text-zinc-400">
              <span>Connected Degree:</span>
              <span className="font-bold text-zinc-200">{selectedNode?.degree || 0} edges</span>
            </div>
          </div>

          {/* Lineage Box */}
          {lineage && (
            <div className="p-3 bg-zinc-900/60 border border-zinc-800 rounded-lg space-y-1.5 text-[11px]">
              <div className="text-zinc-500 text-[10px] uppercase font-bold">DATA LINEAGE</div>
              <div className="text-zinc-300">Table: <strong className="text-zinc-100">{lineage.source_dataset}</strong></div>
              <div className="text-zinc-400">Row Index: #{lineage.source_row_index}</div>
              <div className="text-zinc-400 truncate">Key: {lineage.canonical_key}</div>
            </div>
          )}

          {/* 1-Click Intent Launch Action */}
          {selectedNode && (
            <div className="pt-2 border-t border-zinc-800 space-y-2">
              <button
                onClick={() => launchIntent("INVESTIGATE_ENTITY", selectedNode.id)}
                className="w-full py-2 rounded bg-zinc-100 hover:bg-white text-zinc-950 font-sans font-bold text-xs transition"
              >
                Investigate in Cockpit →
              </button>
              <a
                href="/workspace/scenarios"
                className="w-full py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-center block transition text-xs"
              >
                Run Counterfactual →
              </a>
            </div>
          )}
        </div>
      </div>

      {/* Progressive Disclosure Section */}
      {selectedNode && (
        <ProgressiveDisclosure entityId={selectedNode.id} />
      )}
    </div>
  );
}