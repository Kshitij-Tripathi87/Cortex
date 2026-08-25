export type NexusNodeType =
  | "supplier"
  | "plant"
  | "port"
  | "warehouse"
  | "customer";

export type NexusNodeStatus =
  | "normal"
  | "risk"
  | "at-risk"
  | "validated"
  | "blocked";

export type NexusEdgeStatus =
  | "normal"
  | "risk"
  | "validated"
  | "blocked";

export interface NexusNodeMetadata {
  location?: string;
  leadTime?: string;
  capacity?: string;
}

export interface NexusNode {
  id: string;
  label: string;
  type: NexusNodeType;
  subtitle: string;
  x: number;
  y: number;
  status: NexusNodeStatus;
  metadata?: NexusNodeMetadata;
}

export interface NexusEdge {
  id: string;
  source: string;
  target: string;
  status: NexusEdgeStatus;
  animated?: boolean;
}

export interface NexusMetrics {
  exposure: string;
  timeToImpact: string;
  ordersAtRisk: number;
  validatedOptions: number;
}

export interface NexusScenario {
  id: string;
  label: string;
  description: string;
  nodes: NexusNode[];
  edges: NexusEdge[];
  metrics: NexusMetrics;
}

export type NexusStage =
  | "baseline"
  | "detecting"
  | "evaluating"
  | "validated";

export type NexusAction =
  | { type: "START_DISRUPTION"; disruption: string }
  | { type: "SET_RESPONSE"; response: string }
  | { type: "SET_STAGE"; stage: NexusStage }
  | { type: "SELECT_NODE"; nodeId: string | null }
  | { type: "RESET" };

export interface NexusState {
  stage: NexusStage;
  disruption: string | null;
  response: string | null;
  selectedNodeId: string | null;
}

export const initialNexusState: NexusState = {
  stage: "baseline",
  disruption: null,
  response: null,
  selectedNodeId: null,
};

export function nexusReducer(state: NexusState, action: NexusAction): NexusState {
  switch (action.type) {
    case "START_DISRUPTION":
      return {
        ...state,
        stage: "detecting",
        disruption: action.disruption,
        response: null,
        selectedNodeId: null,
      };
    case "SET_RESPONSE":
      return {
        ...state,
        stage: "evaluating",
        response: action.response,
      };
    case "SET_STAGE":
      return {
        ...state,
        stage: action.stage,
      };
    case "SELECT_NODE":
      return {
        ...state,
        selectedNodeId: action.nodeId,
      };
    case "RESET":
      return initialNexusState;
    default:
      return state;
  }
}