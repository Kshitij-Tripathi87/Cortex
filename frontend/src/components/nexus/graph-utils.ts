import { NexusNode } from "./nexus-types";

export function buildEdgePath(source: NexusNode, target: NexusNode): string {
  const midpoint = source.x + (target.x - source.x) * 0.5;

  return [
    `M ${source.x} ${source.y}`,
    `L ${midpoint} ${source.y}`,
    `L ${midpoint} ${target.y}`,
    `L ${target.x} ${target.y}`,
  ].join(" ");
}

export function buildSmoothPath(source: NexusNode, target: NexusNode): string {
  const dx = (target.x - source.x) * 0.5;

  return [
    `M ${source.x} ${source.y}`,
    `C ${source.x + dx} ${source.y},`,
    `${target.x - dx} ${target.y},`,
    `${target.x} ${target.y}`,
  ].join(" ");
}

export function getArrowMarkerId(status: string): string {
  if (status === "risk") return "nexus-arrow-risk";
  if (status === "validated") return "nexus-arrow-validated";
  if (status === "blocked") return "nexus-arrow-blocked";
  return "nexus-arrow-normal";
}

export const VIEWBOX_WIDTH = 1200;
export const VIEWBOX_HEIGHT = 620;

export function getNodePosition(node: NexusNode): { left: string; top: string } {
  return {
    left: `${(node.x / VIEWBOX_WIDTH) * 100}%`,
    top: `${(node.y / VIEWBOX_HEIGHT) * 100}%`,
  };
}