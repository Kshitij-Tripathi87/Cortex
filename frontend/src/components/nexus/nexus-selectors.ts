import { NexusState, NexusScenario } from "./nexus-types";
import { supplierDelayScenario, validatedMitigationScenario } from "./nexus-fixtures";

export function deriveScenario(state: NexusState): NexusScenario {
  const base = supplierDelayScenario;

  if (state.stage === "validated") {
    return applyValidatedMitigation(base, state.response);
  }

  return applyStage(base, state.stage);
}

function applyStage(base: NexusScenario, stage: NexusState["stage"]): NexusScenario {
  if (stage === "baseline") {
    return {
      ...base,
      nodes: base.nodes.map((n) => ({ ...n, status: "normal" as const, subtitle: n.metadata?.leadTime ? `${n.metadata.leadTime} lead time` : "Normal" })),
      edges: base.edges.map((e) => ({ ...e, status: "normal" as const, animated: false })),
    };
  }

  if (stage === "detecting") {
    return {
      ...base,
      nodes: base.nodes.map((n) => {
        if (n.id === "supplier-x") return { ...n, status: "risk" as const, subtitle: "Delay risk" };
        if (n.id === "plant-2") return { ...n, status: "at-risk" as const, subtitle: "Operational" };
        if (n.id === "port-la") return { ...n, status: "risk" as const, subtitle: "Risk propagated" };
        if (n.id === "dc-west") return { ...n, status: "at-risk" as const, subtitle: "At risk" };
        if (n.id === "customer-1") return { ...n, status: "risk" as const, subtitle: "At risk" };
        return { ...n, status: "normal" as const, subtitle: "Normal" };
      }),
      edges: base.edges.map((e) => ({ ...e, status: "risk" as const, animated: true })),
    };
  }

  if (stage === "evaluating") {
    return {
      ...base,
      nodes: base.nodes.map((n) => {
        if (n.id === "supplier-x") return { ...n, status: "risk" as const, subtitle: "Delay risk" };
        if (n.id === "supplier-a") return { ...n, status: "at-risk" as const, subtitle: "Evaluating alt." };
        if (n.id === "plant-2") return { ...n, status: "at-risk" as const, subtitle: "At risk" };
        if (n.id === "port-la") return { ...n, status: "risk" as const, subtitle: "Risk propagated" };
        if (n.id === "dc-west") return { ...n, status: "at-risk" as const, subtitle: "At risk" };
        if (n.id === "customer-1") return { ...n, status: "risk" as const, subtitle: "At risk" };
        return { ...n, status: "normal" as const };
      }),
      edges: base.edges.map((e) => ({ ...e, status: "risk" as const, animated: true })),
    };
  }

  return base;
}

function applyValidatedMitigation(base: NexusScenario, response: string | null): NexusScenario {
  const scenario = validatedMitigationScenario;

  if (response === "alt-supplier-a") {
    return scenario;
  }

  return {
    ...base,
    nodes: base.nodes.map((n) => {
      if (n.id === "supplier-x") return { ...n, status: "blocked" as const, subtitle: "Blocked" };
      if (n.id === "supplier-a") return { ...n, status: "validated" as const, subtitle: "Validated alt." };
      if (["plant-2", "port-la", "dc-west", "customer-1"].includes(n.id)) {
        return { ...n, status: "validated" as const, subtitle: "Protected" };
      }
      return n;
    }),
    edges: base.edges.map((e) => {
      if (e.source === "supplier-x" || e.target === "supplier-x") {
        return { ...e, status: "blocked" as const, animated: false };
      }
      return { ...e, status: "validated" as const, animated: true };
    }),
    metrics: validatedMitigationScenario.metrics,
  };
}