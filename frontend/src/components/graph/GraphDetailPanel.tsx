"use client";

import React from "react";
import { NexusNode } from "@/components/nexus/nexus-types";

interface GraphDetailPanelProps {
  node: NexusNode | null;
  onClose: () => void;
}

const statusClassMap: Record<string, string> = {
  normal: "graph-detail-panel__status--normal",
  risk: "graph-detail-panel__status--risk",
  "at-risk": "graph-detail-panel__status--at-risk",
  validated: "graph-detail-panel__status--validated",
  blocked: "graph-detail-panel__status--blocked",
};

const statusLabelMap: Record<string, string> = {
  normal: "Normal",
  risk: "Risk",
  "at-risk": "At Risk",
  validated: "Validated",
  blocked: "Blocked",
};

export const GraphDetailPanel: React.FC<GraphDetailPanelProps> = ({ node, onClose }) => {
  if (!node) return null;

  return (
    <div
      className="graph-detail-panel"
      role="dialog"
      aria-labelledby="detail-panel-title"
      aria-modal="false"
    >
      <div className="graph-detail-panel__header">
        <h3 id="detail-panel-title" className="graph-detail-panel__title">
          {node.label}
        </h3>
        <button
          className="graph-detail-panel__close"
          onClick={onClose}
          aria-label="Close detail panel"
        >
          ✕
        </button>
      </div>

      <div className="graph-detail-panel__field">
        <div className="graph-detail-panel__label">Status</div>
        <span className={`graph-detail-panel__status ${statusClassMap[node.status]}`}>
          {statusLabelMap[node.status] || node.status}
        </span>
      </div>

      <div className="graph-detail-panel__field">
        <div className="graph-detail-panel__label">Type</div>
        <div className="graph-detail-panel__value">{node.type.toUpperCase()}</div>
      </div>

      {node.metadata && (
        <div className="graph-detail-panel__metadata">
          <div className="graph-detail-panel__metadata-title">Metadata</div>
          {Object.entries(node.metadata).map(([key, value]) => (
            <div key={key} className="graph-detail-panel__metadata-item">
              <span className="graph-detail-panel__metadata-key">
                {key.charAt(0).toUpperCase() + key.slice(1)}
              </span>
              <span className="graph-detail-panel__metadata-value">{value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};