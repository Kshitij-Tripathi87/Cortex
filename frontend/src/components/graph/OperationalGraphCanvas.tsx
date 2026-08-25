"use client";

import React, { useRef, useEffect, useMemo, useCallback, useState } from "react";
import { NexusScenario, NexusNode, NexusEdge } from "@/components/nexus/nexus-types";
import { GraphDetailPanel } from "./GraphDetailPanel";
import { GraphLegend } from "./GraphLegend";
import { buildEdgePath, getArrowMarkerId, VIEWBOX_WIDTH, VIEWBOX_HEIGHT } from "@/components/nexus/graph-utils";

interface OperationalGraphCanvasProps {
  scenario: NexusScenario;
  stage: string;
  selectedNodeId?: string | null;
  onNodeSelect?: (nodeId: string | null) => void;
  reducedMotion?: boolean;
  showBackground?: boolean;
  showLegend?: boolean;
  onMetrics?: (metrics: { fps: number; nodeCount: number; edgeCount: number; renderTime: number }) => void;
}

const NODE_RADIUS = 12;
const NODE_RADIUS_SMALL = 8;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 5;
const PAN_SPEED = 1.2;
const ZOOM_SPEED = 0.001;

export const OperationalGraphCanvas: React.FC<OperationalGraphCanvasProps> = ({
  scenario,
  stage,
  selectedNodeId = null,
  onNodeSelect,
  reducedMotion = false,
  showBackground = true,
  showLegend = true,
  onMetrics,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animationRef = useRef<number | null>(null);
  const lastFrameTime = useRef<number>(0);
  const frameCount = useRef<number>(0);
  const fps = useRef<number>(0);

  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState<{ x: number; y: number } | null>(null);

  const nodeMap = useMemo(() => new Map(scenario.nodes.map((n) => [n.id, n])), [scenario.nodes]);
  const edgeMap = useMemo(() => new Map(scenario.edges.map((e) => [e.id, e])), [scenario.edges]);

  const viewportWidth = containerRef.current?.clientWidth ?? VIEWBOX_WIDTH;
  const viewportHeight = containerRef.current?.clientHeight ?? VIEWBOX_HEIGHT;

  const getVisibleNodes = useCallback(() => {
    if (!canvasRef.current) return [];
    const { x, y, scale } = transform;
    const canvas = canvasRef.current;
    const left = -x / scale;
    const top = -y / scale;
    const right = (canvas.width - x) / scale;
    const bottom = (canvas.height - y) / scale;

    return scenario.nodes.filter((node) => {
      const nodeX = node.x ?? 0;
      const nodeY = node.y ?? 0;
      const r = NODE_RADIUS / scale + 20;
      return nodeX + r > left && nodeX - r < right && nodeY + r > top && nodeY - r < bottom;
    });
  }, [transform, scenario.nodes]);

  const getVisibleEdges = useCallback(() => {
    const visibleNodeIds = new Set(getVisibleNodes().map((n) => n.id));
    return scenario.edges.filter((e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target));
  }, [getVisibleNodes, scenario.edges]);

  const screenToWorld = useCallback((screenX: number, screenY: number) => {
    return {
      x: (screenX - transform.x) / transform.scale,
      y: (screenY - transform.y) / transform.scale,
    };
  }, [transform]);

  const worldToScreen = useCallback((worldX: number, worldY: number) => {
    return {
      x: worldX * transform.scale + transform.x,
      y: worldY * transform.scale + transform.y,
    };
  }, [transform]);

  const findNodeAt = useCallback((screenX: number, screenY: number) => {
    const { x, y } = screenToWorld(screenX, screenY);
    const nodes = getVisibleNodes();
    const threshold = NODE_RADIUS / transform.scale + 5;

    for (const node of nodes) {
      const nodeX = node.x ?? 0;
      const nodeY = node.y ?? 0;
      const dx = nodeX - x;
      const dy = nodeY - y;
      if (dx * dx + dy * dy <= threshold * threshold) {
        return node;
      }
    }
    return null;
  }, [screenToWorld, transform.scale, getVisibleNodes]);

  const renderFrame = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d", { alpha: true, desynchronized: true });
    if (!ctx) return;

    const startTime = performance.now();

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.scale(dpr, dpr);

    const { x, y, scale } = transform;
    const visibleNodes = getVisibleNodes();
    const visibleEdges = getVisibleEdges();

    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scale, scale);

    if (showBackground) {
      ctx.fillStyle = "#030712";
      ctx.fillRect(-x / scale, -y / scale, canvas.clientWidth / scale, canvas.clientHeight / scale);

      ctx.strokeStyle = "rgba(58, 58, 58, 0.3)";
      ctx.lineWidth = 0.5;
      const gridSize = 50;
      for (let gx = -x / scale; gx < (canvas.clientWidth - x) / scale; gx += gridSize) {
        ctx.beginPath();
        ctx.moveTo(gx, -y / scale);
        ctx.lineTo(gx, (canvas.clientHeight - y) / scale);
        ctx.stroke();
      }
      for (let gy = -y / scale; gy < (canvas.clientHeight - y) / scale; gy += gridSize) {
        ctx.beginPath();
        ctx.moveTo(-x / scale, gy);
        ctx.lineTo((canvas.clientWidth - x) / scale, gy);
        ctx.stroke();
      }
    }

    visibleEdges.forEach((edge) => {
      const source = nodeMap.get(edge.source);
      const target = nodeMap.get(edge.target);
      if (!source || !target) return;

      const sx = source.x ?? 0;
      const sy = source.y ?? 0;
      const tx = target.x ?? 0;
      const ty = target.y ?? 0;

      const dx = tx - sx;
      const dy = ty - sy;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist === 0) return;

      const ux = dx / dist;
      const uy = dy / dist;
      const perpX = -uy;
      const perpY = ux;
      const curvature = 30;

      const mx = (sx + tx) / 2 + perpX * curvature;
      const my = (sy + ty) / 2 + perpY * curvature;

      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.quadraticCurveTo(mx, my, tx, ty);

      const statusColors: Record<string, string> = {
        risk: "#f59e0b",
        validated: "#4ade80",
        blocked: "#ef4444",
        default: "#3a3a3a",
      };
      ctx.strokeStyle = statusColors[edge.status] || statusColors.default;
      ctx.lineWidth = (edge.status === "risk" || edge.status === "validated") ? 2 / scale : 1.5 / scale;

      if (edge.animated && !reducedMotion) {
        const dashOffset = (performance.now() / 50) % 20;
        ctx.setLineDash([8 / scale, 12 / scale]);
        ctx.lineDashOffset = dashOffset;
      } else {
        ctx.setLineDash([]);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      const arrowSize = 8 / scale;
      const angle = Math.atan2(ty - my, tx - mx);
      ctx.save();
      ctx.translate(tx - ux * NODE_RADIUS, ty - uy * NODE_RADIUS);
      ctx.rotate(angle);
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(-arrowSize, -arrowSize / 2);
      ctx.lineTo(-arrowSize, arrowSize / 2);
      ctx.closePath();
      ctx.fillStyle = statusColors[edge.status] || statusColors.default;
      ctx.fill();
      ctx.restore();
    });

    visibleNodes.forEach((node) => {
      const nx = node.x ?? 0;
      const ny = node.y ?? 0;
      const isSelected = selectedNodeId === node.id;
      const isHovered = hoveredNodeId === node.id;
      const radius = isSelected || isHovered ? NODE_RADIUS : NODE_RADIUS_SMALL;

      const nodeColors: Record<string, { fill: string; stroke: string }> = {
        source: { fill: "#06b6d4", stroke: "#22d3ee" },
        transit: { fill: "#8b5cf6", stroke: "#a78bfa" },
        target: { fill: "#f59e0b", stroke: "#fbbf24" },
        sink: { fill: "#ef4444", stroke: "#f87171" },
        default: { fill: "#3f3f46", stroke: "#52525b" },
      };
      const colors = nodeColors[node.type] || nodeColors.default;

      ctx.beginPath();
      ctx.arc(nx, ny, radius / scale, 0, Math.PI * 2);

      ctx.fillStyle = isSelected ? "#4ade80" : isHovered ? colors.stroke : colors.fill;
      ctx.fill();

      ctx.strokeStyle = isSelected ? "#22c55e" : isHovered ? colors.stroke : "#52525b";
      ctx.lineWidth = (isSelected || isHovered ? 2 : 1.5) / scale;
      ctx.stroke();

      const riskScore = (node.metadata as any)?.riskScore;
      if (riskScore && riskScore > 0.7) {
        ctx.beginPath();
        ctx.arc(nx, ny, (radius + 4) / scale, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(239, 68, 68, ${riskScore})`;
        ctx.lineWidth = 2 / scale;
        ctx.setLineDash([4 / scale, 4 / scale]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (scenario.nodes.length <= 200) {
        ctx.font = `${Math.max(10 / scale, 8)}px ui-monospace, monospace`;
        ctx.fillStyle = "#e4e4e7";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(node.label || node.id, nx, ny + radius / scale + 4 / scale);
      }
    });

    ctx.restore();

    const renderTime = performance.now() - startTime;
    frameCount.current++;
    const now = performance.now();
    if (now - lastFrameTime.current >= 1000) {
      fps.current = frameCount.current;
      frameCount.current = 0;
      lastFrameTime.current = now;
    }

    onMetrics?.({
      fps: fps.current,
      nodeCount: visibleNodes.length,
      edgeCount: visibleEdges.length,
      renderTime,
    });

    animationRef.current = requestAnimationFrame(renderFrame);
  }, [
    transform,
    scenario.nodes,
    scenario.edges,
    nodeMap,
    selectedNodeId,
    hoveredNodeId,
    reducedMotion,
    showBackground,
    onMetrics,
    getVisibleNodes,
    getVisibleEdges,
  ]);

  useEffect(() => {
    renderFrame();
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
    };
  }, [renderFrame]);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const screenX = e.clientX - rect.left;
    const screenY = e.clientY - rect.top;

    const worldBefore = screenToWorld(screenX, screenY);

    const delta = e.deltaY > 0 ? -ZOOM_SPEED : ZOOM_SPEED;
    const newScale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, transform.scale * (1 + delta)));
    const scaleFactor = newScale / transform.scale;

    setTransform((prev) => ({
      x: screenX - (worldBefore.x * newScale),
      y: screenY - (worldBefore.y * newScale),
      scale: newScale,
    }));
  }, [transform, screenToWorld]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const node = findNodeAt(e.nativeEvent.offsetX, e.nativeEvent.offsetY);
    if (node) {
      onNodeSelect?.(node.id);
      return;
    }
    setIsPanning(true);
    setPanStart({ x: e.clientX, y: e.clientY });
  }, [findNodeAt, onNodeSelect]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning && panStart) {
      const dx = e.clientX - panStart.x;
      const dy = e.clientY - panStart.y;
      setTransform((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }));
      setPanStart({ x: e.clientX, y: e.clientY });
    } else {
      const node = findNodeAt(e.nativeEvent.offsetX, e.nativeEvent.offsetY);
      setHoveredNodeId(node?.id ?? null);
    }
  }, [isPanning, panStart, findNodeAt]);

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
    setPanStart(null);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsPanning(false);
    setPanStart(null);
    setHoveredNodeId(null);
  }, []);

  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    const node = findNodeAt(e.nativeEvent.offsetX, e.nativeEvent.offsetY);
    if (node) {
      onNodeSelect?.(node.id);
    }
  }, [findNodeAt, onNodeSelect]);

  const resetView = useCallback(() => {
    setTransform({ x: viewportWidth / 2, y: viewportHeight / 2, scale: 1 });
  }, [viewportWidth, viewportHeight]);

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full graph-canvas-container"
      style={{ maxWidth: "100%", height: "600px" }}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      onDoubleClick={handleDoubleClick}
      onContextMenu={(e) => e.preventDefault()}
    >
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ width: "100%", height: "100%", display: "block" }}
        tabIndex={0}
        role="img"
        aria-label={`Operational graph with ${scenario.nodes.length} nodes and ${scenario.edges.length} edges`}
      />
      <div className="absolute bottom-4 right-4 flex gap-2 p-2 bg-zinc-950/90 backdrop-blur rounded-lg border border-zinc-800">
        <button
          onClick={resetView}
          className="px-3 py-1 text-xs font-mono bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded transition"
          aria-label="Reset view"
        >
          Reset View
        </button>
        <div className="px-3 py-1 text-xs font-mono text-zinc-400 flex items-center gap-2">
          <span>FPS: {fps.current}</span>
          <span>|</span>
          <span>Zoom: {(transform.scale * 100).toFixed(0)}%</span>
        </div>
      </div>
      {showLegend && <GraphLegend className="mt-4" />}
      {selectedNodeId && (
        <GraphDetailPanel
          node={nodeMap.get(selectedNodeId) ?? null}
          onClose={() => onNodeSelect?.(null)}
        />
      )}
    </div>
  );
};

export const OperationalGraphAuto: React.FC<OperationalGraphCanvasProps> = (props) => {
  const nodeCount = props.scenario.nodes.length;
  const useCanvas = nodeCount > 1000;

  if (useCanvas) {
    return <OperationalGraphCanvas {...props} />;
  }

  const { OperationalGraph: SVGGraph } = require("./OperationalGraph");
  return <SVGGraph {...props} />;
};