"use client";

import React from "react";
import { NexusNode } from "@/components/nexus/nexus-types";

interface GraphNodeProps {
  node: NexusNode;
  isSelected: boolean;
  onSelect: (nodeId: string) => void;
  reducedMotion?: boolean;
}

const statusIconMap: Record<string, string> = {
  normal: "●",
  risk: "▲",
  "at-risk": "◆",
  validated: "✓",
  blocked: "✕",
};

export const GraphNode: React.FC<GraphNodeProps> = ({
  node,
  isSelected,
  onSelect,
  reducedMotion = false,
}) => {
  const positionStyle = {
    left: `${(node.x / 1200) * 100}%`,
    top: `${(node.y / 620) * 100}%`,
  } as React.CSSProperties;

  const statusClass = `graph-node graph-node--${node.status} ${isSelected ? "graph-node--selected" : ""}`;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(node.id);
    }
  };

  return (
    <button
      type="button"
      className={statusClass}
      style={positionStyle}
      aria-label={`${node.label}, ${node.subtitle}`}
      aria-pressed={isSelected}
      onClick={() => onSelect(node.id)}
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <span className="graph-node__ring" aria-hidden="true">
        <span style={{ fontSize: "0.65rem", lineHeight: 1 }}>{statusIconMap[node.status] || "●"}</span>
      </span>
      <span className="graph-node__copy">
        <strong>{node.label}</strong>
        <small>{node.subtitle}</small>
      </span>
    </button>
  );
};