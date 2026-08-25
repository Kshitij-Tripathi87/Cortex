"use client";

import React from "react";
import { NexusNode, NexusEdge } from "@/components/nexus/nexus-types";
import { buildEdgePath, getArrowMarkerId } from "@/components/nexus/graph-utils";

interface GraphBackgroundProps {
  nodes: NexusNode[];
  edges: NexusEdge[];
  className?: string;
}

export const GraphBackground: React.FC<GraphBackgroundProps> = ({
  nodes,
  edges,
  className = "",
}) => {
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  return (
    <section className={`graph-background ${className}`} aria-hidden="true">
      <svg viewBox="0 0 1200 620" className="graph-svg" role="img" aria-hidden="true">
        <defs>
          <marker
            id="bg-arrow-normal"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <path d="M0,0 L6,3 L0,6 Z" fill="#3a3a3a" />
          </marker>
          <marker
            id="bg-arrow-risk"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <path d="M0,0 L6,3 L0,6 Z" fill="#f59e0b" />
          </marker>
        </defs>

        {edges.map((edge) => {
          const source = nodeMap.get(edge.source);
          const target = nodeMap.get(edge.target);

          if (!source || !target) return null;

          const path = buildEdgePath(source, target);
          const markerId = edge.status === "risk" ? "bg-arrow-risk" : "bg-arrow-normal";

          return (
            <path
              key={edge.id}
              d={path}
              className={`graph-edge graph-edge--${edge.status}`}
              markerEnd={`url(#${markerId})`}
              strokeWidth={1}
              style={{ opacity: 0.5 }}
            />
          );
        })}
      </svg>
    </section>
  );
};