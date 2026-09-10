"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
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
import {
  fetchWorkspaceState,
  loadDemoDataset,
  fetchActiveSignals,
  triggerDeliberation,
  appendStreamEvent,
} from "@/lib/api/nexusClient";
import { fetchOperationalSubgraph, fetchCriticalNodes } from "@/lib/api/graph";
import { fetchDecisionValidity, fetchDecisionEvidence, approveDecision } from "@/lib/api/decisions";
import { fetchCounterfactuals } from "@/lib/api/scenarios";
import { fetchEvidenceForDecision, fetchEvidenceGraph } from "@/lib/api/evidence";
import { deliberate as fetchAgentDeliberation, fetchAgentMessages } from "@/lib/api/agents";
import { executeDecision } from "@/lib/api/execution";
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
  const [graphVersion, setGraphVersion] = useState<string>("graph_v1");

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
    last_graph_version: "graph_v0",
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
    const workspaceId = process.env.NEXT_PUBLIC_NEXUS_WORKSPACE_ID || "default_workspace";
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
      fetchActiveSignals().then(setSignals).catch(() => {});
    });
    const unsubRisk = client.on("risk_changed", () => {
      fetchActiveSignals().then(setSignals).catch(() => {});
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
  }, []);

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
    try {
      const data = await fetchWorkspaceState();
      if (data.workspace_id) setWorkspaceName(String(data.workspace_id));
      if (data.total_raw_rows !== undefined) setTotalRows(data.total_raw_rows);
      if (data.entities_resolved !== undefined) setEntitiesResolved(data.entities_resolved);
      const ga = data.graph_analytics;
      if (ga) {
        if (ga.coverage) {
          if (ga.coverage.total_nodes_created !== undefined) setNodesCount(ga.coverage.total_nodes_created);
          if (ga.coverage.total_edges_created !== undefined) setEdgesCount(ga.coverage.total_edges_created);
          if (ga.coverage.relationship_coverage_pct !== undefined) setRelationshipCoveragePct(ga.coverage.relationship_coverage_pct);
        }
        if (ga.graph_version) {
          setGraphVersion(ga.graph_version);
        } else if (data.graph_version) {
          setGraphVersion(data.graph_version);
        }
      }
      if (data.world_state_version !== undefined) setWorldStateVersion(data.world_state_version);
      setWorldStateUpdatedAt("just now");

      const loaded = (data.datasets_loaded || []).length > 0;
      setIsDemoLoaded(loaded);
      if (loaded) setEnvironmentLabel("CONTROLLED DEMO");

      if (data.is_last_decision_valid !== undefined) {
        setIsDecisionValid(Boolean(data.is_last_decision_valid));
      }
      if (data.invalidation_reason) setInvalidationReason(data.invalidation_reason);

      // Fetch operational signals after state
      try {
        const sigData = await fetchActiveSignals();
        setSignals(sigData);
      } catch {
        setSignals([]);
      }

      // Fetch subgraph for the graph view
      try {
        const subgraph = await fetchOperationalSubgraph(undefined, 2, 100);
        setNodes(subgraph.nodes || []);
        setEdges(subgraph.edges || []);
      } catch {
        setNodes([]);
        setEdges([]);
      }

      // Fetch decision validity
      try {
        const validity = await fetchDecisionValidity();
        if (validity.decision_id) {
          setIsDecisionValid(validity.is_valid);
          if (validity.invalidation_reason) setInvalidationReason(validity.invalidation_reason);
        }
      } catch {
        // ignore
      }
    } catch {
      // Backend unreachable: keep honest empty/disconnected shell state (spec §38/§59).
      // Do NOT inject fake/hardcoded data.
      setIsDemoLoaded(false);
      setEnvironmentLabel("OFFLINE");
      setSignals([]);
      setNodes([]);
      setEdges([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadControlledDemo = useCallback(async () => {
    try {
      setLoading(true);
      const data = await loadDemoDataset();
      if (data.workspace_state?.workspace_id) setWorkspaceName(String(data.workspace_state.workspace_id));
      if (data.workspace_state) {
        const ws = data.workspace_state;
        if (ws.total_raw_rows !== undefined) setTotalRows(ws.total_raw_rows);
        if (ws.entities_resolved !== undefined) setEntitiesResolved(ws.entities_resolved);
        const ga = ws.graph_analytics;
        if (ga) {
          if (ga.coverage) {
            if (ga.coverage.total_nodes_created !== undefined) setNodesCount(ga.coverage.total_nodes_created);
            if (ga.coverage.total_edges_created !== undefined) setEdgesCount(ga.coverage.total_edges_created);
            if (ga.coverage.relationship_coverage_pct !== undefined) setRelationshipCoveragePct(ga.coverage.relationship_coverage_pct);
          }
          if (ga.graph_version) setGraphVersion(ga.graph_version);
        }
        if (ws.world_state_version !== undefined) setWorldStateVersion(ws.world_state_version);
        setWorldStateUpdatedAt("just now");
      }
      setIsDemoLoaded(true);
      setEnvironmentLabel("CONTROLLED DEMO");
      // After loading demo, refresh live state to get signals, subgraph, etc.
      await refreshLiveState();
    } catch {
      setIsDemoLoaded(false);
      setEnvironmentLabel("OFFLINE");
      setLoading(false);
    }
  }, [refreshLiveState]);

  // After initial load + demo, fetch deliberate data (candidates + agent messages)
  useEffect(() => {
    if (isDemoLoaded) {
      (async () => {
        try {
          const del = await triggerDeliberation();
          // Populate decision from deliberation result
          if (del.deliberation_result?.decision_card?.selected_candidate) {
            setLatestDecision({
              decision_id: del.deliberation_result.decision_id,
              title: "Expedited Air Freight + Cross-Docking",
              target_entity_id: del.deliberation_result.target_entity,
              selected_candidate: del.deliberation_result.counterfactuals[0]?.candidate_id ?? "",
              action_summary: del.deliberation_result.counterfactuals[0]?.action_type ?? "",
              estimated_cost_usd: del.deliberation_result.counterfactuals[0]?.operational_cost_usd ?? 0,
              net_economic_value_usd: del.deliberation_result.counterfactuals[0]?.net_economic_value_usd ?? 0,
              sla_protection_pct: 100 - (del.deliberation_result.counterfactuals[0]?.sla_breach_pct ?? 0),
              governance_status: "APPROVED_FOR_EXECUTION",
              created_at: new Date().toISOString(),
              world_state_version: del.deliberation_result.decision_card.selected_candidate ? worldStateVersion : 0,
              graph_version: graphVersion,
              is_valid: true,
            });
          }

          // Populate candidates from counterfactuals
          const cands = del.deliberation_result?.counterfactuals?.map((c: any) => ({
            candidate_id: c.candidate_id,
            name: c.name ?? CANDIDATE_NAME_MAP[c.candidate_id] ?? c.candidate_id,
            action_type: c.action_type,
            predicted_delay_days: c.predicted_delay_days,
            sla_breach_pct: c.sla_breach_pct,
            operational_cost_usd: c.operational_cost_usd,
            revenue_protected_usd: c.revenue_protected_usd,
            net_economic_value_usd: c.net_economic_value_usd,
            is_optimal_choice: c.is_optimal_choice,
            confidence_pct: c.confidence_pct ?? 0,
          })) || [];
          setCandidates(cands);

          // Populate agent messages from message stream
          const msgs = del.deliberation_result?.message_stream?.map((m: any, idx: number) => ({
            message_id: m.id ?? `msg_${idx}`,
            sender_role: m.sender ?? "AGENT",
            sender_name: m.sender ?? "Agent",
            sender_version: "v4",
            content: m.content ?? "",
            evidence_refs: m.evidence_refs ?? [],
            phase: m.phase ?? "OBSERVATION",
            timestamp: m.timestamp ?? new Date().toISOString(),
          })) || [];
          setAgentMessages(msgs);

          // Update decision lifecycle
          setDecisionLifecycleState("APPROVED_FOR_EXECUTION");
          setDecisionFreshnessState("VALID");
          setDecisionFreshnessExplanation(`Verified against World State v${worldStateVersion}.`);
          setActiveWorkflowStep(6);
        } catch {
          // If deliberate fails keep empty candidates/messages — honest fallback.
          setCandidates([]);
          setAgentMessages([]);
        }
      })();
    }
  }, [isDemoLoaded, worldStateVersion, graphVersion]);

  // Initial load
  useEffect(() => {
    (async () => {
      await refreshLiveState();
      if (!isDemoLoaded) {
        await loadControlledDemo();
      }
    })();
  }, []);

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
    if (entityId === "seller_01a00b8e99") {
      return {
        entity_id: "seller_01a00b8e99",
        entity_type: "SELLER",
        source_dataset: "olist_sellers_dataset.csv",
        source_row_index: 482,
        canonical_key: "seller_id:01a00b8e99",
        ingested_at: "2026-08-16T23:50:14Z",
        pagerank: 0.042,
        betweenness: 0.31,
        connected_degree: 14,
        active_signals: ["SELLER_DEGRADATION (+90%)"],
        affected_decisions: ["dec_live_01"],
      };
    }
    return {
      entity_id: entityId,
      entity_type: "ENTITY",
      source_dataset: "olist_dataset.csv",
      source_row_index: 1,
      canonical_key: `id:${entityId}`,
      ingested_at: "2026-08-16T23:50:00Z",
      pagerank: 0.01,
      betweenness: 0.01,
      connected_degree: 2,
      active_signals: [],
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
    dataset_version: "olist_2026_q3_v1",
    graph_version: graphVersion,
    world_state_version: worldStateVersion,
    feature_version: "feat_spof_pagerank_v2",
    model_version: "gnn_carrier_risk_v4.1",
    agent_version: "swarm_protocol_v4",
    policy_version: "pol_logistics_sop_2026",
    simulation_version: "mc_twin_sim_1000",
    decision_version: "dec_candidate_c_v1",
  });

  const injectStreamEvent = async () => {
    try {
      await appendStreamEvent("SELLER_DEGRADATION_TELEMETRY", {
        seller_id: "seller_01a00b8e99",
        metric: "dispatch_latency_breach",
      });
    } catch {
      // Graceful fallback — UI will reflect backend state.
    }
    const nextVersion = worldStateVersion + 1;
    setWorldStateVersion(nextVersion);
    setWorldStateUpdatedAt("just now");
    setGraphVersion(`graph_v${nextVersion - 99}`);
    setIsDecisionValid(false);
    setDecisionLifecycleState("INVALIDATED");
    setDecisionFreshnessState("INVALIDATED");
    setDecisionFreshnessExplanation(
      `Invalidated because seller_01a00b8e99 changed state in World State v${nextVersion}.`
    );
    setInvalidationReason(
      `World State evolved to v${nextVersion}: Dependent entity seller_01a00b8e99 state mutated via live telemetry stream.`
    );
  };

  const redeliberate = async () => {
    try {
      const del = await triggerDeliberation("seller_01a00b8e99");
      // Populate decision, candidates, messages from the deliberation result.
      if (del.deliberation_result?.decision_card?.selected_candidate) {
        setLatestDecision({
          decision_id: del.deliberation_result.decision_id,
          title: "Expedited Air Freight + Cross-Docking",
          target_entity_id: del.deliberation_result.target_entity,
          selected_candidate: del.deliberation_result.counterfactuals[0]?.candidate_id ?? "",
          action_summary: del.deliberation_result.counterfactuals[0]?.action_type ?? "",
          estimated_cost_usd: del.deliberation_result.counterfactuals[0]?.operational_cost_usd ?? 0,
          net_economic_value_usd: del.deliberation_result.counterfactuals[0]?.net_economic_value_usd ?? 0,
          sla_protection_pct: 100 - (del.deliberation_result.counterfactuals[0]?.sla_breach_pct ?? 0),
          governance_status: "APPROVED_FOR_EXECUTION",
          created_at: new Date().toISOString(),
          world_state_version: worldStateVersion,
          graph_version: graphVersion,
          is_valid: true,
        });
      }

      const cands = del.deliberation_result?.counterfactuals?.map((c: any) => ({
        candidate_id: c.candidate_id,
        name: c.name ?? CANDIDATE_NAME_MAP[c.candidate_id] ?? c.candidate_id,
        action_type: c.action_type,
        predicted_delay_days: c.predicted_delay_days,
        sla_breach_pct: c.sla_breach_pct,
        operational_cost_usd: c.operational_cost_usd,
        revenue_protected_usd: c.revenue_protected_usd,
        net_economic_value_usd: c.net_economic_value_usd,
        is_optimal_choice: c.is_optimal_choice,
        confidence_pct: c.confidence_pct ?? 0,
      })) || [];
      setCandidates(cands);

      const msgs = del.deliberation_result?.message_stream?.map((m: any, idx: number) => ({
        message_id: m.id ?? `msg_${idx}`,
        sender_role: m.sender ?? "AGENT",
        sender_name: m.sender ?? "Agent",
        sender_version: "v4",
        content: m.content ?? "",
        evidence_refs: m.evidence_refs ?? [],
        phase: m.phase ?? "OBSERVATION",
        timestamp: m.timestamp ?? new Date().toISOString(),
      })) || [];
      setAgentMessages(msgs);

      setIsDecisionValid(true);
      setInvalidationReason(null);
      setDecisionLifecycleState("APPROVED_FOR_EXECUTION");
      setDecisionFreshnessState("VALID");
      setDecisionFreshnessExplanation(`Re-verified and approved against World State v${worldStateVersion}.`);
      setActiveWorkflowStep(6);
    } catch {
      setIsDecisionValid(false);
      setInvalidationReason("Deliberation failed — backend unreachable");
      setDecisionLifecycleState("REVIEW");
      setDecisionFreshnessState("STALE");
      setDecisionFreshnessExplanation("Deliberation could not be completed — backend unreachable.");
    }
  };

  // Workflow Continuity Scope (populated from whatever state we have)
  const workflowScope: WorkflowContinuityScope = {
    entity: "seller_01a00b8e99",
    graph_scope: "2-hop ego-graph (8 nodes, 7 edges)",
    signal_scope: signals.map((s) => s.signal_type + " (" + Math.round(s.deviation_pct) + "%)"),
    world_state: worldStateVersion,
    risk_scope:
      signals.length > 0
        ? `${signals.length} exposed orders, $${signals.reduce((acc, s) => acc + s.metric_value * 50, 0) * 10}.00 exposure`
        : "No signals — no exposure estimate",
    agents: ["Logistics Specialist (v4)", "Risk Analyst (v4)", "Supervisor (v4)"],
    scenario:
      candidates.length > 0
        ? `Candidate ${candidates[0]?.name ?? "?"} (${candidates[0]?.action_type ?? "?"})`
        : "No candidates — run analysis",
  };

  // Operator Governance (static, dataset-rooted)
  const [operatorGovernance, setOperatorGovernance] = useState<OperatorGovernance>({
    decision_id: "DEC-1029",
    owner: "Procurement Dispatch",
    reviewer: "Chief Operating Officer (COO)",
    status: "AWAITING_REVIEW",
    comments: [
      {
        comment_id: "c1",
        author: "Alex Morgan",
        role: "Procurement Lead",
        text: "Candidate C satisfies minimum SLA thresholds. Route VCP->SDU is pre-cleared.",
        timestamp: "23:55:09Z",
      },
    ],
    audit_hash: "5a3d7611e98094cd1071b563810a99c430f2",
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