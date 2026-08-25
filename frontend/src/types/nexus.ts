/**
 * Cortex Nexus — Core Frontend Domain Type Definitions (Program U).
 */

export interface DatasetMeta {
  dataset_id: string;
  name: string;
  row_count: number;
  columns: string[];
  status: "PARSING" | "PROFILING" | "RESOLVING" | "READY" | "ERROR";
  completeness_pct: number;
  ingested_at: string;
}

export interface DataQualityReport {
  dimension: "SCHEMA" | "COMPLETENESS" | "INTEGRITY" | "TEMPORAL" | "RELATIONSHIPS";
  score_pct: number;
  status: "PASS" | "WARN" | "FAIL";
  details: string;
  anomalies_detected: number;
}

export interface CanonicalEntitySummary {
  entity_type: "SELLER" | "ORDER" | "CUSTOMER" | "PRODUCT" | "ROUTE" | "LOCATION";
  count: number;
  spof_count: number;
  primary_keys: string[];
}

export interface GraphNode {
  id: string;
  type: "SELLER" | "ORDER" | "CUSTOMER" | "PRODUCT" | "ROUTE" | "LOCATION";
  attributes: Record<string, any>;
  pagerank: number;
  betweenness?: number;
  degree: number;
  is_spof: boolean;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface GraphEdge {
  edge_id: string;
  source: string;
  target: string;
  relation_type: string;
  weight: number;
}

export interface SubgraphResponse {
  center_node_id?: string;
  max_hops: number;
  nodes_count: number;
  edges_count: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface WorldStateEvent {
  event_id: string;
  version: number;
  event_type: string;
  entity_id: string;
  timestamp: string;
  payload: Record<string, any>;
  state_summary: string;
}

export interface OperationalSignal {
  signal_id: string;
  entity_id: string;
  entity_type: string;
  signal_type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  confidence: number;
  metric_value: number;
  baseline_threshold: number;
  deviation_pct: number;
  detected_at: string;
  evidence: string[];
}

export interface RiskExposureSummary {
  critical_entities_count: number;
  affected_orders_count: number;
  exposed_customers_count: number;
  revenue_at_risk_usd: number;
  seller_concentration_gini: number;
  primary_corridor: string;
}

export interface AgentMessageEnvelope {
  message_id: string;
  sender_role: "SUPERVISOR" | "SHIPMENT_TRACKING" | "LOGISTICS_ROUTING" | "INVENTORY_ALLOCATION" | "BOOKING" | "COMPLIANCE" | "OPTIMIZATION" | "PROCUREMENT" | string;
  sender_name: string;
  sender_version: string;
  content: string;
  evidence_refs: string[];
  phase: "OBSERVATION" | "CRITIQUE" | "PROPOSAL" | "SYNTHESIS" | string;
  timestamp: string;
  context_package?: {
    world_state_version: number;
    subgraph_nodes?: number;
    signals_analyzed?: string[];
    domain?: string;
    [key: string]: any;
  };
}

export interface AgentFleetReplica {
  agent_id: string;
  role: string;
  name: string;
  version: string;
  replica_count: number;
  canary_pct: number;
  status: "HEALTHY" | "DEGRADED" | "QUARANTINED" | "REPLACING";
  latency_p95_ms: number;
  error_rate_pct: number;
  last_heartbeat: string;
}

export interface ScenarioCandidate {
  candidate_id: string;
  name: string;
  action_type: string;
  predicted_delay_days: number;
  sla_breach_pct: number;
  operational_cost_usd: number;
  revenue_protected_usd: number;
  net_economic_value_usd: number;
  is_optimal_choice: boolean;
  confidence_pct: number;
}

export interface DecisionCard {
  decision_id: string;
  title: string;
  target_entity_id: string;
  selected_candidate: string;
  action_summary: string;
  estimated_cost_usd: number;
  net_economic_value_usd: number;
  sla_protection_pct: number;
  governance_status: "APPROVED_FOR_EXECUTION" | "AWAITING_REVIEW" | "INVALIDATED";
  created_at: string;
  world_state_version: number;
  graph_version: string;
  is_valid: boolean;
  invalidation_reason?: string;
  dependency_set?: {
    dependent_entity_ids: string[];
    dependent_signals: string[];
    created_at_world_version: number;
  };
}

export interface EvidenceNode {
  node_id: string;
  node_type: "SOURCE_RECORD" | "CANONICAL_ENTITY" | "OPERATIONAL_SIGNAL" | "ROOT_CAUSE_HYPOTHESIS" | "AGENT_PROPOSAL" | "DIGITAL_TWIN_SIMULATION" | "POLICY_DECISION";
  label: string;
  checksum_sha256: string;
  parent_node_id?: string;
  payload: Record<string, any>;
  verified_at: string;
}

export interface EvidenceCitation {
  citation_id: string;
  source_type: "GRAPH_PATH" | "SIGNAL" | "METRIC" | "RECORD";
  label: string;
  value: string;
  deep_link: string;
}

export interface EvidenceAnswer {
  answer_id: string;
  query_text: string;
  summary_finding: string;
  key_reasons: string[];
  citations: EvidenceCitation[];
  impacted_entities: string[];
  confidence_score: number;
  recommended_action: {
    action_type: string;
    net_economic_value_usd: number;
    candidate?: string;
  };
  checksum_sha256: string;
  answered_at: string;
}

export interface DataAnswerabilityReport {
  query_text: string;
  is_answerable: boolean;
  confidence_score: number;
  data_coverage_pct: number;
  temporal_coverage_days: number;
  relevant_entities_resolved_pct: number;
  missing_prerequisites: string[];
  available_dimensions: string[];
}

export type GraphMode = "WORLD" | "RISK" | "DEPENDENCY" | "INCIDENT" | "SCENARIO" | "EVIDENCE";

export interface EntityLineageInfo {
  entity_id: string;
  entity_type: string;
  source_dataset: string;
  source_row_index: number;
  canonical_key: string;
  ingested_at: string;
  pagerank: number;
  betweenness: number;
  connected_degree: number;
  active_signals: string[];
  affected_decisions: string[];
}

export type EntityLineage = EntityLineageInfo;

export type ProgressiveLevel = "SUMMARY" | "OPERATIONAL" | "SPECIALIST" | "AUDIT" | "RAW" | 1 | 2 | 3 | 4 | 5 | string;

export type IntentType =
  | "INVESTIGATE_ENTITY"
  | "INVESTIGATE_INCIDENT"
  | "EVALUATE_DECISION"
  | "SIMULATE_DISRUPTION"
  | "GENERAL_EXPLORATION";

export interface IntentContext {
  intent_type: IntentType;
  title: string;
  target_id: string;
  secondary_id?: string;
  status: "ACTIVE" | "COMPLETED" | "PAUSED";
  started_at?: string;
  created_at?: string;
  ego_nodes_count?: number;
  active_signals_count?: number;
  recommended_candidate_id?: string;
}

export type DecisionLifecycleState =
  | "DRAFT"
  | "SIMULATING"
  | "REVIEW"
  | "APPROVED_FOR_EXECUTION"
  | "EXECUTING"
  | "MONITORING"
  | "INVALIDATED";

export type AgentLifecycleState =
  | "ACTIVE"
  | "CANARY"
  | "DEGRADED"
  | "SHADOW"
  | "QUARANTINED";

export interface GraphBenchmarkStats {
  node_count: number;
  edge_count: number;
  fps: number;
  layout_time_ms: number;
  render_time_ms: number;
  memory_mb: number;
}

export type WhySubject =
  | "SIGNAL"
  | "AGENT"
  | "SCENARIO"
  | "RECOMMENDATION"
  | "INVALIDATION";

export interface GovernanceComment {
  comment_id: string;
  author: string;
  role: string;
  text: string;
  timestamp: string;
}

export interface OperatorGovernance {
  decision_id: string;
  owner: string;
  reviewer: string;
  status: "DRAFT" | "AWAITING_REVIEW" | "APPROVED" | "REJECTED" | "REANALYSIS_REQUESTED";
  comments: GovernanceComment[];
  audit_hash: string;
}

export interface WorkflowContinuityScope {
  entity: string;
  graph_scope: string;
  signal_scope: string[];
  world_state: number;
  risk_scope: string;
  agents: string[];
  scenario: string;
}

export type DecisionFreshnessState =
  | "VALID"
  | "STALE"
  | "INVALIDATED"
  | "SUPERSEDED"
  | "EXECUTING"
  | "COMPLETED";

export interface EvidenceVersionTuple {
  dataset_version: string;
  graph_version: string;
  world_state_version: number;
  feature_version: string;
  model_version: string;
  agent_version: string;
  policy_version: string;
  simulation_version: string;
  decision_version: string;
}

export interface ReconciliationState {
  last_event_id: string;
  last_world_state_version: number;
  last_graph_version: string;
  is_reconciling: boolean;
  missed_events_count: number;
  resync_status: "SYNCHRONIZED" | "RESYNCING" | "GAP_DETECTED" | "OFFLINE";
  last_sync_timestamp: string;
}

export interface GraphBenchmarkMatrixEntry {
  workload: string;
  node_count: number;
  edge_count: number;
  render_ms: number;
  selection_ms: number;
  fps: number;
  delta_update_ms: number;
  memory_mb: number;
}

/* ------------------------------------------------------------------ */
/* Backend response contracts (verified against FastAPI routers)      */
/* ------------------------------------------------------------------ */

export interface GraphCoverageMetrics {
  total_nodes_created: number;
  total_edges_created: number;
  nodes_by_type: Record<string, number>;
  edges_by_type: Record<string, number>;
  orphan_entities_count: number;
  unresolved_entities_count: number;
  relationship_coverage_pct: number;
  graph_version: string;
  world_state_version: number;
}

export interface GraphAnalyticsSummary {
  graph_version: string;
  world_state_version: number;
  coverage: GraphCoverageMetrics;
  density: number;
  top_critical_sellers: Array<Record<string, unknown>>;
  top_critical_routes: Array<Record<string, unknown>>;
  high_dependency_spofs: string[];
  seller_concentration_gini: number;
  computed_at?: string;
}

export interface WorkspaceStateResponse {
  status: string;
  workspace_id: string;
  organization_id: string;
  entities_resolved: number;
  datasets_loaded: Array<{ name: string; row_count?: number; columns?: string[] }>;
  datasets_ingested: number;
  total_raw_rows: number;
  readiness_reports: unknown[];
  graph_version: string;
  world_state_version: number;
  graph_analytics?: GraphAnalyticsSummary;
  active_signals: OperationalSignal[];
  last_decision: Record<string, unknown> | null;
  is_last_decision_valid: boolean;
  invalidation_reason: string | null;
  created_at: string;
}

export interface SignalListResponse {
  active_signals: OperationalSignal[];
  primary_blast_radius: Record<string, unknown> | null;
}

export interface DecisionValidityResponse {
  decision_id: string;
  is_valid: boolean;
  invalidation_reason: string | null;
  dependency_set?: {
    decision_id: string;
    graph_version_at_creation: string;
    world_state_version_at_creation: number;
    dependent_entity_ids: string[];
    dependent_signal_types: string[];
    is_valid: boolean;
    invalidation_reason: string | null;
    invalidated_at: string | null;
    created_at: string;
  };
}

/** Raw counterfactual shape returned by /workspace/deliberate (counterfactuals[]). */
export interface RawCounterfactual {
  candidate_id: string;
  action_type: string;
  predicted_delay_days: number;
  sla_breach_pct: number;
  operational_cost_usd: number;
  revenue_protected_usd: number;
  net_economic_value_usd: number;
  is_optimal_choice: boolean;
  sla_protection_pct?: number;
  confidence_pct?: number;
  name?: string;
}

export interface DeliberationResult {
  decision_id: string;
  target_entity: string;
  participating_agents: string[];
  message_stream: AgentMessageEnvelope[];
  counterfactuals: RawCounterfactual[];
  decision_card: {
    selected_candidate: string;
    action: string;
    cost_usd: number;
    net_economic_value_usd: number;
    status: string;
    explanation: string;
  };
  evidence_graph: Record<string, unknown>;
  evidence_trail: Array<Record<string, unknown>>;
}

export interface DeliberationResponse {
  status: string;
  deliberation_result: DeliberationResult;
}

export interface CriticalNodesResponse {
  top_critical_sellers: Array<Record<string, unknown>>;
  top_critical_routes: Array<Record<string, unknown>>;
  high_dependency_spofs: string[];
  seller_concentration_gini: number;
}

export interface StreamEventResponse {
  status: string;
  delta: Record<string, unknown>;
}

export interface DemoLoadResponse {
  status: string;
  loaded_tables: Array<{ table: string; rows: number }>;
  workspace_state: WorkspaceStateResponse;
}

export const CANDIDATE_NAME_MAP: Record<string, string> = {
  CANDIDATE_A_DO_NOTHING: "Candidate A: Status Quo",
  CANDIDATE_B_GREEDY_REROUTE: "Candidate B: Dedicated Trucking",
  CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK: "Candidate C: Air Freight + Cross-Docking",
  CANDIDATE_D_STOCK_TRANSFER: "Candidate D: Inter-Hub Stock Transfer",
};

/** Map a raw backend counterfactual to the frontend ScenarioCandidate (presentation only). */
export function mapCounterfactual(raw: RawCounterfactual): ScenarioCandidate {
  return {
    candidate_id: raw.candidate_id,
    name: raw.name ?? CANDIDATE_NAME_MAP[raw.candidate_id] ?? raw.candidate_id,
    action_type: raw.action_type,
    predicted_delay_days: raw.predicted_delay_days,
    sla_breach_pct: raw.sla_breach_pct,
    operational_cost_usd: raw.operational_cost_usd,
    revenue_protected_usd: raw.revenue_protected_usd,
    net_economic_value_usd: raw.net_economic_value_usd,
    is_optimal_choice: raw.is_optimal_choice,
    confidence_pct: raw.confidence_pct ?? 0,
  };
}




