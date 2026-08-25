"use client";

import React, { useMemo, useEffect } from "react";
import { NexusScenario, NexusNode } from "@/components/nexus/nexus-types";
import { GraphNode } from "./GraphNode";
import { GraphEdge } from "./GraphEdge";
import { GraphLegend } from "./GraphLegend";
import { GraphDetailPanel } from "./GraphDetailPanel";
import { GraphBackground } from "./GraphBackground";
import { buildEdgePath, getArrowMarkerId, VIEWBOX_WIDTH, VIEWBOX_HEIGHT } from "@/components/nexus/graph-utils";

interface OperationalGraphProps {
  scenario: NexusScenario;
  stage: string;
  selectedNodeId?: string | null;
  onNodeSelect?: (nodeId: string | null) => void;
  reducedMotion?: boolean;
  showBackground?: boolean;
  showLegend?: boolean;
}

export const OperationalGraph: React.FC<OperationalGraphProps> = ({
  scenario,
  stage,
  selectedNodeId = null,
  onNodeSelect,
  reducedMotion = false,
  showBackground = true,
  showLegend = true,
}) => {
  const nodeMap = useMemo(() => new Map(scenario.nodes.map((n) => [n.id, n])), [scenario.nodes]);

  useEffect(() => {
    if (reducedMotion) {
      document.body.classList.add("reduce-motion");
    } else {
      document.body.classList.remove("reduce-motion");
    }
    return () => document.body.classList.remove("reduce-motion");
  }, [reducedMotion]);

  return (
    <div className="relative w-full" style={{ maxWidth: "100%" }}>
      <div
        className="graph-container"
        role="img"
        aria-labelledby="nexus-graph-title"
        aria-describedby="nexus-graph-description"
      >
        <title id="nexus-graph-title">{scenario.label}</title>
        <desc id="nexus-graph-description">{scenario.description}</desc>

        {showBackground && (
          <GraphBackground nodes={scenario.nodes} edges={scenario.edges} />
        )}

        <svg
          className="graph-svg"
          viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
          role="img"
          aria-hidden="true"
        >
          <defs>
            <marker
              id="nexus-arrow-normal"
              markerWidth="8"
              markerHeight="8"
              refX="6"
              refY="4"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 Z" fill="#3a3a3a" />
            </marker>

            <marker
              id="nexus-arrow-risk"
              markerWidth="8"
              markerHeight="8"
              refX="6"
              refY="4"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 Z" fill="#f59e0b" />
            </marker>

            <marker
              id="nexus-arrow-validated"
              markerWidth="8"
              markerHeight="8"
              refX="6"
              refY="4"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 Z" fill="#4ade80" />
            </marker>

            <marker
              id="nexus-arrow-blocked"
              markerWidth="8"
              markerHeight="8"
              refX="6"
              refY="4"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 Z" fill="#ef4444" />
            </marker>
          </defs>

          {scenario.edges.map((edge) => {
            const source = nodeMap.get(edge.source);
            const target = nodeMap.get(edge.target);

            if (!source || !target) return null;

            const path = buildEdgePath(source, target);
            const markerId = getArrowMarkerId(edge.status);

            return (
              <path
                key={edge.id}
                d={path}
                className={`graph-edge graph-edge--${edge.status} ${edge.animated ? "graph-edge--animated" : ""}`}
                markerEnd={`url(#${markerId})`}
                strokeWidth={edge.status === "risk" || edge.status === "validated" ? 2 : 1.5}
              />
            );
          })}
        </svg>

        {scenario.nodes.map((node) => (
          <GraphNode
            key={node.id}
            node={node}
            isSelected={selectedNodeId === node.id}
            onSelect={onNodeSelect ?? (() => {})}
            reducedMotion={reducedMotion}
          />
        ))}

        {selectedNodeId && (
          <GraphDetailPanel
            node={nodeMap.get(selectedNodeId) ?? null}
            onClose={() => onNodeSelect?.(null)}
          />
        )}
      </div>

      {showLegend && <GraphLegend className="mt-4" />}
    </div>
  );
};