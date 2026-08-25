"use client";

import React, { useEffect, useRef } from "react";
import { NexusNode, NexusEdge } from "@/components/nexus/nexus-types";
import { buildEdgePath, getArrowMarkerId, VIEWBOX_WIDTH, VIEWBOX_HEIGHT } from "@/components/nexus/graph-utils";

interface GraphEdgeProps {
  edge: NexusEdge;
  source: NexusNode;
  target: NexusNode;
  reducedMotion?: boolean;
}

export const GraphEdge: React.FC<GraphEdgeProps> = ({
  edge,
  source,
  target,
  reducedMotion = false,
}) => {
  const pathRef = useRef<SVGPathElement>(null);
  const path = buildEdgePath(source, target);
  const markerId = getArrowMarkerId(edge.status);

  useEffect(() => {
    const pathEl = pathRef.current;
    if (!pathEl || reducedMotion || !edge.animated) return;

    const length = pathEl.getTotalLength();
    pathEl.style.strokeDasharray = `${length}`;
    pathEl.style.strokeDashoffset = `${length}`;

    requestAnimationFrame(() => {
      pathEl.style.transition = "stroke-dashoffset 900ms ease";
      pathEl.style.strokeDashoffset = "0";
    });

    if (edge.animated) {
      pathEl.classList.add("graph-edge--animated");
    }

    return () => {
      pathEl.classList.remove("graph-edge--animated");
    };
  }, [edge.animated, edge.id, reducedMotion]);

  return (
    <path
      ref={pathRef}
      key={edge.id}
      d={path}
      className={`graph-edge graph-edge--${edge.status} ${edge.animated ? "graph-edge--animated" : ""}`}
      markerEnd={`url(#${markerId})`}
      strokeWidth={edge.status === "risk" || edge.status === "validated" ? 2 : 1.5}
    />
  );
};