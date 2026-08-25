"use client";

import React from "react";

interface GraphLegendProps {
  className?: string;
}

export const GraphLegend: React.FC<GraphLegendProps> = ({ className = "" }) => {
  const items = [
    { status: "normal", label: "Normal", color: "#3a3a3a" },
    { status: "risk", label: "Risk", color: "#f59e0b" },
    { status: "at-risk", label: "At Risk", color: "#f59e0b" },
    { status: "validated", label: "Validated", color: "#4ade80" },
    { status: "blocked", label: "Blocked", color: "#ef4444" },
  ];

  return (
    <div className={`graph-legend ${className}`} role="img" aria-label="Graph node and edge status legend">
      {items.map((item) => (
        <div key={item.status} className="graph-legend__item">
          <div
            className={`graph-legend__swatch graph-legend__swatch--${item.status}`}
            style={{ backgroundColor: item.status === "normal" ? "#0a0a0a" : "#0a0a0a", borderColor: item.color }}
            aria-hidden="true"
          />
          <span className="graph-legend__label">{item.label}</span>
        </div>
      ))}
    </div>
  );
};