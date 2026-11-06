"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import {
  GraphNode,
  GraphEdge,
  GraphMode,
  OperationalSignal,
  DecisionCard,
  EntityLineage,
  IntentContext,
  IntentType,
  ProgressiveLevel,
  WhySubject,
  OperatorGovernance,
  GovernanceComment,
  WorkflowContinuityScope,
  AgentLifecycleState,
  DecisionLifecycleState,
  DecisionFreshnessState,
  ReconciliationState,
  EvidenceVersionTuple,
} from "@/types/nexus";
import { CANDIDATE_NAME_MAP, mapCounterfactual } from "@/types/nexus";
import { fetchActiveSignals } from "@/lib/api/signals";
import { fetchOperationalSubgraph } from "@/lib/api/graph";
import { RealtimeClient } from "@/lib/realtime/client";
import { getAuthToken } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export type RealtimeStatus = "LIVE" | "RECONNECTING" | "SYNCING" | "OFFLINE";

interface WorkspaceContextValue {
  // Proportional Operational World State
  totalRows: number;
  entitiesResolved: number;
  nodesCount: number;
  edgesCount: number;
  graphVersion: string;
  worldStateVersion: number;
  worldStateUpdatedAt: string;
  relationshipCoveragePct: number;

  // Shell identity / connection (spec §6 / §58)
  workspaceName: string;
  environmentLabel: string;
  isDemoLoaded: boolean;
  realtimeStatus: RealtimeStatus;
  loading: boolean;
  wsConnected: boolean;

  // Graph State
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNode: GraphNode | null;
  setSelectedNode: (node: GraphNode | null) => void;
  graphMode: GraphMode;
  setGraphMode: (mode: GraphMode) => void;
  selectedCandidateId: string;
  setSelectedCandidateId: (id: string) => void;
  setHistoricalVersion: (version: number) => void;

  // Signals & Financial Blast Radius
  signals: OperationalSignal[];
  latestDecision: DecisionCard | null;
  isDecisionValid: boolean;
  invalidationReason: string | null;

  // Decoupled State Machines (Program X1)
  agentLifecycleState: AgentLifecycleState;
  decisionLifecycleState: DecisionLifecycleState;
  setDecisionLifecycleState: (state: DecisionLifecycleState) => void;
  decisionFreshnessState: DecisionFreshnessState;
  decisionFreshnessExplanation: string;

  // Real-Time Reconciliation Manager (Program X2)
  reconciliationState: ReconciliationState;
  triggerReconciliation: () => void;
  simulateGapAndResync: () => void;

  // Cryptographic Evidence Lineage
  getEntityLineage: (entityId: string) => EntityLineage;
  getEvidenceVersionTuple: () => EvidenceVersionTuple;

  // Intent-Centric Orchestration (Program W1)
  currentIntent: IntentContext | null;
  launchIntent: (type: IntentType, targetId: string, secondaryId?: string) => void;
  clearIntent: () => void;

  // Continuous Workflow Scope (Program W2/X)
  workflowScope: WorkflowContinuityScope;

  // Operator Handoff & Governance (Program X)
  operatorGovernance: OperatorGovernance;
  assignDecision: (owner: string, reviewer: string) => void;
  addGovernanceComment: (text: string, author: string, role: string) => void;
  requestReanalysis: (reason: string) => void;

  // Why Explainer Modal ("Why am I seeing this?")
  whyModalOpen: boolean;
  whySubject: WhySubject | null;
  openWhyModal: (subject: WhySubject) => void;
  closeWhyModal: () => void;

  // Progressive Disclosure Level (L1, L2, L3)
  progressiveLevel: ProgressiveLevel;
  setProgressiveLevel: (level: ProgressiveLevel) => void;

  // Operational Command Palette (Cmd+K)
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;

  // Operational Workflow Progression (Steps 1 to 8)
  activeWorkflowStep: number;
  setActiveWorkflowStep: (step: number) => void;

  // Graph Performance & Benchmark Scaling (10, 1k, 10k, 100k)
  benchmarkScale: 10 | 1000 | 10000 | 100000;
  setBenchmarkScale: (scale: 10 | 1000 | 10000 | 100000) => void;

  // Live Swarm & Mutation Actions
  redeliberate: () => Promise<void>;
  injectStreamEvent: () => Promise<void>;
  refreshLiveState: () => Promise<void>;

  // Candidates & Agent Messages (from deliberate)
  candidates: any[];
  agentMessages: any[];
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

export const WorkspaceProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const { workspace } = useAuth();
  const workspaceId = workspace?.id ?? "";
  // Shell identity / connection (spec §6 / §58). Starts disconnected; populated from backend.
  const [workspaceName, setWorkspaceName] = useState<string>("Default Workspace");
  const [environmentLabel, setEnvironmentLabel] = useState<string>(
    process.env.NODE_ENV === "production" ? "PRODUCTION" : "DEVELOPMENT"
  );
  const [isDemoLoaded, setIsDemoLoaded] = useState<boolean>(false);
  const [realtimeStatus, setRealtimeStatus] = useState<RealtimeStatus>("OFFLINE");
  const [loading, setLoading] = useState<boolean>(true);

  // Operational counts (from backend / demo)
  const [totalRows, setTotalRows] = useState(0);
  const [entitiesResolved, setEntitiesResolved] = useState(0);
  const [nodesCount, setNodesCount] = useState(0);
  const [edgesCount, setEdgesCount] = useState(0);
  const [worldStateVersion, setWorldStateVersion] = useState(0);
  const [worldStateUpdatedAt, setWorldStateUpdatedAt] = useState("never");
  const [relationshipCoveragePct, setRelationshipCoveragePct] = useState(0);

  // Graph Overlay Mode
  const [graphMode, setGraphMode] = useState<GraphMode>("WORLD");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>("");
  const [graphVersion, setGraphVersion] = useState<string>("unknown");

  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // Signals populated from backend; starts empty until /workspace/signals resolves.
  const [signals, setSignals] = useState<OperationalSignal[]>([]);

  const [latestDecision, setLatestDecision] = useState<DecisionCard | null>(null);

  const [isDecisionValid, setIsDecisionValid] = useState<boolean>(true);
  const [invalidationReason, setInvalidationReason] = useState<string | null>(null);

  const [decisionLifecycleState, setDecisionLifecycleState] = useState<
    DecisionLifecycleState
  >("REVIEW");
  const [agentLifecycleState] = useState<AgentLifecycleState>("ACTIVE");
  const [decisionFreshnessState, setDecisionFreshnessState] = useState<
    DecisionFreshnessState
  >("VALID");
  const [decisionFreshnessExplanation, setDecisionFreshnessExplanation] = useState<
    string
  >("");

  // Real-Time Reconciliation Manager (Program X2)
  const [reconciliationState, setReconciliationState] = useState<ReconciliationState>({
    last_event_id: "evt_0",
    last_world_state_version: 0,
    last_graph_version: "unknown",
    is_reconciling: false,
    missed_events_count: 0,
    resync_status: "OFFLINE",
    last_sync_timestamp: "never",
  });

  // Intent-Centric State (Program W1)
  const [currentIntent, setCurrentIntent] = useState<IntentContext | null>(null);

  const [progressiveLevel, setProgressiveLevel] = useState<ProgressiveLevel>("OPERATIONAL");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [activeWorkflowStep, setActiveWorkflowStep] = useState<number>(1);
  const [benchmarkScale, setBenchmarkScale] = useState<10 | 1000 | 10000 | 100000>(10);

  // Why Explainer Modal
  const [whyModalOpen, setWhyModalOpen] = useState<boolean>(false);
  const [whySubject, setWhySubject] = useState<WhySubject | null>(null);

  // Candidates & Agent Messages (from deliberate)
  const [candidates, setCandidates] = useState<any[]>([]);
  const [agentMessages, setAgentMessages] = useState<any[]>([]);

  // Realtime WebSocket Connection
  const [wsConnected, setWsConnected] = useState(false);

  // B4 centralized realtime: sequence-gated SSE with cursor resume.
  // Wire types are the canonical outbox types (decision_created,
  // risk_changed, forecast_updated, …); reactions mirror the legacy
  // handlers (refetch authoritative state, flip decision validity).
  useEffect(() => {
    if (!workspaceId) {
      setRealtimeStatus("OFFLINE");
      return;
    }
    const cursorKey = `cortex:realtime_seq:${workspaceId}`;
    let initialSeq = 0;
    try {
      initialSeq = Number(window.localStorage.getItem(cursorKey) || 0) || 0;
    } catch {
      initialSeq = 0;
    }
    const devUserId = process.env.NEXT_PUBLIC_DEV_USER_ID;
    const client = new RealtimeClient({
      workspaceId,
      baseUrl: API_BASE.replace(/\/api\/v1\/?$/, ""),
      initialSeq,
      getToken: () => getAuthToken(),
      // Dev (`header` identity) carries X-User-* headers; prod (`jwt`
      // identity) falls back to the stored bearer token automatically.
      authHeaders: () => {
        const headers: Record<string, string> = {};
        if (devUserId) {
          headers["X-User-Id"] = devUserId;
          headers["X-User-Workspaces"] =
            process.env.NEXT_PUBLIC_DEV_WORKSPACES || workspaceId;
          headers["X-User-Roles"] = process.env.NEXT_PUBLIC_DEV_ROLES || "operator";
        }
        return headers;
      },
      // Unpageable gap: refetch the authoritative snapshot, then resume.
      onResyncRequired: () => {
        refreshLiveState();
      },
    });

    const unsubscribeState = client.onStatus((state) => {
      setWsConnected(state === "live");
      if (state === "live") setRealtimeStatus("LIVE");
      else if (state === "syncing") setRealtimeStatus("SYNCING");
      else if (state === "reconnecting" || state === "connecting")
        setRealtimeStatus("RECONNECTING");
      else setRealtimeStatus("OFFLINE");
    });

    // Persist the cursor: a browser refresh resumes, never replays all.
    const persistCursor = client.onAny((event) => {
      try {
        window.localStorage.setItem(cursorKey, String(event.seq));
      } catch {
        // Private mode: resume-from-zero still converges via replay.
      }
      if (typeof event.world_state_version === "number") {
        setWorldStateVersion((prev) => Math.max(prev, event.world_state_version as number));
        setWorldStateUpdatedAt("just now");
      }
    });

    const unsubSignal = client.on("risk.inferred", () => {
      fetchActiveSignals(workspaceId).then(setSignals).catch(() => setRealtimeStatus("OFFLINE"));
    });
    const unsubRisk = client.on("risk_changed", () => {
      fetchActiveSignals(workspaceId).then(setSignals).catch(() => setRealtimeStatus("OFFLINE"));
    });
    const unsubDecisionInvalidated = client.on("decision_invalidated", (event) => {
      const reason =
        (event.payload?.reason as string | undefined) ||
        "Decision invalidated by world state drift";
      setIsDecisionValid(false);
      setInvalidationReason(reason);
      setDecisionLifecycleState("INVALIDATED");
      setDecisionFreshnessState("INVALIDATED");
      setDecisionFreshnessExplanation(reason);
    });
    const unsubDecisionCreated = client.on("decision_created", () => {
      refreshLiveState();
    });
    const unsubForecast = client.on("forecast_updated", () => {
      refreshLiveState();
    });
    const unsubObservation = client.on("observation.recorded", () => {
      refreshLiveState();
    });
    const unsubScenario = client.on("scenario_completed", () => {
      refreshLiveState();
    });
    const unsubForecastGen = client.on("forecast.generated", () => {
      refreshLiveState();
    });

    client.connect();

    return () => {
      persistCursor();
      unsubSignal();
      unsubRisk();
      unsubDecisionInvalidated();
      unsubDecisionCreated();
      unsubForecast();
      unsubForecastGen();
      unsubObservation();
      unsubScenario();
      unsubscribeState();
      client.disconnect();
    };
  // refreshLiveState is declared below this effect; it is intentionally read
  // from the effect closure after render rather than evaluated here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  const openWhyModal = (subject: WhySubject) => {
    setWhySubject(subject);
    setWhyModalOpen(true);
  };

  const closeWhyModal = () => {
    setWhyModalOpen(false);
    setWhySubject(null);
  };

  // ---- Live Backend Integration (spec §37/§38/§59) ----

  const refreshLiveState = useCallback(async () => {
    setLoading(true);
    if (!workspaceId) {
      setLoading(false);
      return;
    }
    try {
      const [sigData, subgraph] = await Promise.all([
        fetchActiveSignals(workspaceId),
        fetchOperationalSubgraph(workspaceId, undefined, 2, 100),
      ]);
      setWorkspaceName(workspace?.name ?? workspaceId);
      setEnvironmentLabel("LIVE");
      setIsDemoLoaded(false);
      setSignals(sigData);
      setNodes(subgraph.nodes || []);
      setEdges(subgraph.edges || []);
      setNodesCount(subgraph.nodes_count);
      setEdgesCount(subgraph.edges_count);
      setTotalRows(subgraph.nodes_count + subgraph.edges_count);
      setEntitiesResolved(subgraph.nodes_count);
      setWorldStateUpdatedAt("just now");
    } catch {
      // Backend unreachable: keep honest empty/disconnected shell state.
      setIsDemoLoaded(false);
      setEnvironmentLabel("OFFLINE");
      setSignals([]);
      setNodes([]);
      setEdges([]);
    } finally {
      setLoading(false);
    }
  }, [workspace?.name, workspaceId]);

  // Initial load
  useEffect(() => {
    void refreshLiveState();
  }, [refreshLiveState]);

  const launchIntent = useCallback((type: IntentType, targetId: string, secondaryId?: string) => {
    setCurrentIntent({
      intent_type: type,
      title: `${type.replace(/_/g, " ")}: ${targetId}`,
      target_id: targetId,
      secondary_id: secondaryId,
      created_at: new Date().toLocaleTimeString(),
      status: "ACTIVE",
    });
    const found = nodes.find((n) => n.id === targetId);
    if (found) setSelectedNode(found);
  }, [nodes]);

  const clearIntent = () => setCurrentIntent(null);

  const setHistoricalVersion = (version: number) => {
    setWorldStateVersion(version);
    setWorldStateUpdatedAt(`Snapshot v${version}`);
    if (version < 101) {
      setSignals([]);
    }
  };

  const getEntityLineage = (entityId: string): EntityLineage => {
    const node = nodes.find((candidate) => candidate.id === entityId);
    return {
      entity_id: entityId,
      entity_type: node?.type ?? "ENTITY",
      source_dataset: "",
      source_row_index: 0,
      canonical_key: `id:${entityId}`,
      ingested_at: "",
      pagerank: node?.pagerank ?? 0,
      betweenness: node?.betweenness ?? 0,
      connected_degree: node?.degree ?? 0,
      active_signals: signals.filter((signal) => signal.entity_id === entityId).map((signal) => signal.signal_type),
      affected_decisions: [],
    };
  };

  const triggerReconciliation = () => {
    setReconciliationState((prev) => ({
      ...prev,
      is_reconciling: true,
      resync_status: "RESYNCING",
    }));
    setTimeout(() => {
      setReconciliationState({
        last_event_id: `evt_${worldStateVersion}_sync`,
        last_world_state_version: worldStateVersion,
        last_graph_version: graphVersion,
        is_reconciling: false,
        missed_events_count: 0,
        resync_status: "SYNCHRONIZED",
        last_sync_timestamp: new Date().toLocaleTimeString(),
      });
    }, 400);
  };

  const simulateGapAndResync = () => {
    setReconciliationState((prev) => ({
      ...prev,
      is_reconciling: true,
      resync_status: "GAP_DETECTED",
      missed_events_count: 3,
    }));
    setTimeout(() => {
      triggerReconciliation();
    }, 800);
  };

  const getEvidenceVersionTuple = (): EvidenceVersionTuple => ({
    dataset_version: "unknown",
    graph_version: graphVersion,
    world_state_version: worldStateVersion,
    feature_version: "unknown",
    model_version: "unknown",
    agent_version: "unknown",
    policy_version: "unknown",
    simulation_version: "unknown",
    decision_version: "unknown",
  });

  const injectStreamEvent = async () => {
    await refreshLiveState();
  };

  const redeliberate = async () => {
    await refreshLiveState();
  };

  // Workflow Continuity Scope (populated from whatever state we have)
  const workflowScope: WorkflowContinuityScope = {
    entity: signals[0]?.entity_id ?? nodes[0]?.id ?? "No active entity",
    graph_scope: `${nodes.length} nodes, ${edges.length} edges`,
    signal_scope: signals.map((s) => s.signal_type + " (" + Math.round(s.deviation_pct) + "%)"),
    world_state: worldStateVersion,
    risk_scope:
      signals.length > 0
        ? `${signals.length} active signals`
        : "No active signals",
    agents: [],
    scenario:
      candidates.length > 0
        ? `Candidate ${candidates[0]?.name ?? "?"} (${candidates[0]?.action_type ?? "?"})`
        : "No candidates — run analysis",
  };

  // Operator Governance is populated by the canonical decision lifecycle.
  const [operatorGovernance, setOperatorGovernance] = useState<OperatorGovernance>({
    decision_id: "",
    owner: "",
    reviewer: "",
    status: "DRAFT",
    comments: [],
    audit_hash: "",
  });

  const assignDecision = (owner: string, reviewer: string) => {
    setOperatorGovernance((prev) => ({
      ...prev,
      owner,
      reviewer,
    }));
  };

  const addGovernanceComment = (text: string, author: string, role: string) => {
    const newComment: GovernanceComment = {
      comment_id: `c_${Date.now()}`,
      author,
      role,
      text,
      timestamp: new Date().toLocaleTimeString(),
    };
    setOperatorGovernance((prev) => ({
      ...prev,
      comments: [...prev.comments, newComment],
    }));
  };

  const requestReanalysis = (reason: string) => {
    setOperatorGovernance((prev) => ({
      ...prev,
      status: "REANALYSIS_REQUESTED",
    }));
    addGovernanceComment(`Requested re-analysis: ${reason}`, "Operations Reviewer", "Reviewer");
    setDecisionLifecycleState("REVIEW");
    setDecisionFreshnessState("STALE");
    setDecisionFreshnessExplanation(`Re-analysis requested: ${reason}`);
    setActiveWorkflowStep(4);
  };

  // ── Return Provider ──

  return (
    <WorkspaceContext.Provider
      value={{
        totalRows,
        entitiesResolved,
        nodesCount,
        edgesCount,
        graphVersion,
        worldStateVersion,
        worldStateUpdatedAt,
        relationshipCoveragePct,
        workspaceName,
        environmentLabel,
        isDemoLoaded,
        realtimeStatus,
        loading,
        wsConnected,
        nodes,
        edges,
        selectedNode,
        setSelectedNode,
        graphMode,
        setGraphMode,
        selectedCandidateId,
        setSelectedCandidateId,
        setHistoricalVersion,
        signals,
        latestDecision,
        isDecisionValid,
        invalidationReason,
        agentLifecycleState,
        decisionLifecycleState,
        setDecisionLifecycleState,
        decisionFreshnessState,
        decisionFreshnessExplanation,
        reconciliationState,
        triggerReconciliation,
        simulateGapAndResync,
        getEntityLineage,
        getEvidenceVersionTuple,
        currentIntent,
        launchIntent,
        clearIntent,
        workflowScope,
        operatorGovernance,
        assignDecision,
        addGovernanceComment,
        requestReanalysis,
        whyModalOpen,
        whySubject,
        openWhyModal,
        closeWhyModal,
        progressiveLevel,
        setProgressiveLevel,
        commandPaletteOpen,
        setCommandPaletteOpen,
        activeWorkflowStep,
        setActiveWorkflowStep,
        benchmarkScale,
        setBenchmarkScale,
        redeliberate,
        injectStreamEvent,
        refreshLiveState,
        candidates,
        agentMessages,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
};

export const useNexusWorkspace = () => {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useNexusWorkspace must be used within a WorkspaceProvider");
  }
  return ctx;
};

export { mapCounterfactual, CANDIDATE_NAME_MAP };
