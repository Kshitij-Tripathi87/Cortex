"""Nexus v0.7 — SQLAlchemy persistent models.

Authoritative database representations for everything that matters
operationally. Replaces the in-memory singletons that caused data loss on
restart and made horizontal scaling unsafe.

Tables:
  - nexus_decisions            Decision lifecycle records
  - nexus_approvals            Approval/audit events
  - nexus_executions           Execution records
  - nexus_outcomes             Outcome records
  - nexus_forecasts            Persisted forecasts (for truth loop)
  - nexus_observations         Actual observations (demand, SLA, etc.)
  - nexus_risks                Persisted risk snapshots
  - nexus_scenarios            Scenario definitions + results
  - nexus_evidence             Evidence DAG nodes
  - nexus_vanessa_sessions     Vanessa conversation sessions
  - nexus_vanessa_messages     Vanessa messages (turn-by-turn)
  - nexus_model_registry       ML model registry
  - nexus_recommendations      Decision recommendations
  - nexus_events               Realtime event outbox
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# Decisions
# ─────────────────────────────────────────────────────────────────────────────


class DecisionRecordDB(Base):
    """Persistent decision lifecycle — the authoritative source for a decision's state."""

    __tablename__ = "nexus_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="proposed")

    world_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    world_state_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    proposal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    simulation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_root_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_root_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=list)
    chosen_option: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    situation: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_option_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    recommended_nev: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_sla: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    actual_nev: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_sla: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    financial_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    deterministic_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )

    transitions: Mapped[list[DecisionTransitionDB]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_nexus_decisions_tenant_workspace_phase", "tenant_id", "workspace_id", "phase"),
    )


class DecisionTransitionDB(Base):
    """Append-only transition history for a decision (audit trail)."""

    __tablename__ = "nexus_decision_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transition_id: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: f"TRN-{uuid4().hex[:8]}"
    )
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="CASCADE"), index=True
    )
    from_phase: Mapped[str] = mapped_column(String(40), nullable=False)
    to_phase: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    # NOTE: pass the target class explicitly. With `from __future__ import
    # annotations` the bare annotation string "DecisionRecordDB" would be
    # resolved through the declarative registry BY NAME, which is ambiguous —
    # app.modules.graph.decision_repository also declares a DecisionRecordDB
    # on the same Base. The explicit class reference skips registry lookup.
    decision: Mapped[DecisionRecordDB] = relationship(
        DecisionRecordDB, back_populates="transitions"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Approvals
# ─────────────────────────────────────────────────────────────────────────────


class ApprovalRecordDB(Base):
    __tablename__ = "nexus_approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    approver_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(64), default="operator")
    decision_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_checks: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# ─────────────────────────────────────────────────────────────────────────────
# Executions
# ─────────────────────────────────────────────────────────────────────────────


class ExecutionRecordDB(Base):
    __tablename__ = "nexus_executions"

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(40), default="pending", index=True
    )  # pending|executing|executed|failed|rolled_back
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# ─────────────────────────────────────────────────────────────────────────────
# Outcomes
# ─────────────────────────────────────────────────────────────────────────────


class OutcomeRecordDB(Base):
    __tablename__ = "nexus_outcomes"

    outcome_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("nexus_executions.execution_id", ondelete="SET NULL"), nullable=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)

    # Predicted KPIs (copied from decision)
    predicted_nev: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_sla: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Actual KPIs
    actual_nev: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_sla: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    outcome_status: Mapped[str] = mapped_column(String(40), default="pending")
    financial_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    regret_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# ─────────────────────────────────────────────────────────────────────────────
# Forecasts + Observations (Truth Loop persistence)
# ─────────────────────────────────────────────────────────────────────────────


class ForecastRecordDB(Base):
    __tablename__ = "nexus_forecasts"

    forecast_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    product_family: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str] = mapped_column(String(64), default="baseline-v1")
    world_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=14)

    p10: Mapped[float] = mapped_column(Float)
    p25: Mapped[float] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float)
    p75: Mapped[float] = mapped_column(Float)
    p80: Mapped[float] = mapped_column(Float)
    p90: Mapped[float] = mapped_column(Float)
    p95: Mapped[float] = mapped_column(Float)
    p99: Mapped[float] = mapped_column(Float)

    mean: Mapped[float] = mapped_column(Float)
    std_dev: Mapped[float] = mapped_column(Float)

    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )

    __table_args__ = (
        Index("ix_nexus_forecasts_sku_model_created", "sku", "model_version", "created_at"),
    )


class ObservationRecordDB(Base):
    """Actual outcomes recorded against forecasts — closes the truth loop."""

    __tablename__ = "nexus_observations"

    observation_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: f"OBS-{uuid4().hex[:10]}"
    )
    forecast_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("nexus_forecasts.forecast_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    sku: Mapped[str] = mapped_column(String(128), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    observation_type: Mapped[str] = mapped_column(
        String(40), default="demand"
    )  # demand|sla|eta|cost
    actual_value: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Computed at insert time when forecast_id matches
    predicted_p50: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_p80: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_p95: Mapped[float | None] = mapped_column(Float, nullable=True)
    absolute_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentage_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    bias: Mapped[float | None] = mapped_column(Float, nullable=True)
    within_p80: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    within_p95: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        Index("ix_nexus_observations_sku_type_observed", "sku", "observation_type", "observed_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Risks
# ─────────────────────────────────────────────────────────────────────────────


class RiskRecordDB(Base):
    __tablename__ = "nexus_risks"

    risk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)

    entity_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    entity_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), index=True)  # CRITICAL|HIGH|MEDIUM|LOW|WATCH
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    gnn_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # GNN augmentation
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    blast_radius_count: Mapped[int] = mapped_column(Integer, default=0)
    revenue_exposure: Mapped[float | None] = mapped_column(Float, nullable=True)
    sla_risk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    root_causes: Mapped[list[str]] = mapped_column(JSON, default=list)
    hidden_dependencies: Mapped[list[str]] = mapped_column(JSON, default=list)  # GNN-discovered
    world_state_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(40), default="open", index=True
    )  # open|mitigated|closed|stale
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioRecordDB(Base):
    __tablename__ = "nexus_scenarios"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    decision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="SET NULL"), nullable=True
    )
    parent_scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)

    mutations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    kpi_results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    gnn_insights: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    world_state_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(40), default="pending"
    )  # pending|running|completed|failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# ─────────────────────────────────────────────────────────────────────────────
# Evidence DAG
# ─────────────────────────────────────────────────────────────────────────────


class EvidenceNodeDB(Base):
    __tablename__ = "nexus_evidence_nodes"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    node_type: Mapped[str] = mapped_column(
        String(40)
    )  # observation|signal|forecast|risk|scenario|decision|approval|execution|outcome|claim
    label: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    outgoing: Mapped[list[EvidenceEdgeDB]] = relationship(
        "EvidenceEdgeDB", foreign_keys="EvidenceEdgeDB.from_node_id", cascade="all, delete-orphan"
    )


class EvidenceEdgeDB(Base):
    __tablename__ = "nexus_evidence_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_evidence_nodes.node_id", ondelete="CASCADE"), index=True
    )
    to_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_evidence_nodes.node_id", ondelete="CASCADE"), index=True
    )
    relation: Mapped[str] = mapped_column(
        String(64)
    )  # supports|causes|informs|contradicts|proves|derived_from
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    __table_args__ = (
        UniqueConstraint("from_node_id", "to_node_id", "relation", name="uq_evidence_edge"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Vanessa Sessions
# ─────────────────────────────────────────────────────────────────────────────


class VanessaSessionDB(Base):
    """Per-user per-workspace Vanessa conversation session with operational context."""

    __tablename__ = "nexus_vanessa_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)

    # Context
    current_world_state_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    selected_entity_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selected_risk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Session state
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_bag: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )

    messages: Mapped[list[VanessaMessageDB]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="VanessaMessageDB.turn_number",
    )


class VanessaMessageDB(Base):
    __tablename__ = "nexus_vanessa_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: f"VMSG-{uuid4().hex[:10]}"
    )
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_vanessa_sessions.session_id", ondelete="CASCADE"), index=True
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(20))  # user|assistant|system|tool
    content: Mapped[str] = mapped_column(Text)
    response_blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )  # TEXT|METRIC|TABLE|GRAPH|TIME_SERIES|RISK_CARD|SCENARIO_MATRIX|DECISION_CARD|EVIDENCE_CHAIN|TIMELINE
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    session: Mapped[VanessaSessionDB] = relationship(back_populates="messages")


# ─────────────────────────────────────────────────────────────────────────────
# Model Registry
# ─────────────────────────────────────────────────────────────────────────────


class ModelRegistryEntryDB(Base):
    __tablename__ = "nexus_model_registry"

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # forecast|gnn|rl|risk|eta|sla
    description: Mapped[str] = mapped_column(Text, default="")

    training_dataset: Mapped[str | None] = mapped_column(String(256), nullable=True)
    feature_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    world_state_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_data_range: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Metrics
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )  # MAE, RMSE, WAPE, MAPE, etc.
    calibration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # P50/P80/P95 coverage
    gnn_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # GNN-specific config
    rl_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # RL-specific config

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(40), default="training", index=True
    )  # training|evaluating|shadow|calibrating|approved|deployed|monitoring|rolled_back|archived
    approval_status: Mapped[str] = mapped_column(
        String(40), default="pending", index=True
    )  # pending|approved|rejected

    # Shadow metrics
    shadow_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[str] = mapped_column(String(128), default="system")
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)


# ─────────────────────────────────────────────────────────────────────────────
# Recommendations
# ─────────────────────────────────────────────────────────────────────────────


class RecommendationRecordDB(Base):
    __tablename__ = "nexus_recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nexus_decisions.decision_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)

    recommended_action: Mapped[str] = mapped_column(Text)
    alternative_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Predicted KPIs
    predicted_nev: Mapped[float] = mapped_column(Float)
    predicted_sla: Mapped[float] = mapped_column(Float)
    predicted_cost: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rl_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    gnn_features: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Actual KPIs (filled post-outcome)
    actual_nev: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_sla: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)  # success|failure|mixed

    # Evaluation metrics
    recommendation_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation_regret: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulation_error: Mapped[float | None] = mapped_column(Float, nullable=True)

    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_root_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─────────────────────────────────────────────────────────────────────────────
# Realtime Event Outbox
# ─────────────────────────────────────────────────────────────────────────────


class EventRecordDB(Base):
    """Outbox pattern for realtime events. Every state change writes here;
    the SSE fan-out reads from this table (or subscribes via NOTIFY)."""

    __tablename__ = "nexus_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: f"EVT-{uuid4().hex[:10]}"
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    world_state_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, index=True
    )


__all__ = [
    "DecisionRecordDB",
    "DecisionTransitionDB",
    "ApprovalRecordDB",
    "ExecutionRecordDB",
    "OutcomeRecordDB",
    "ForecastRecordDB",
    "ObservationRecordDB",
    "RiskRecordDB",
    "ScenarioRecordDB",
    "EvidenceNodeDB",
    "EvidenceEdgeDB",
    "VanessaSessionDB",
    "VanessaMessageDB",
    "ModelRegistryEntryDB",
    "RecommendationRecordDB",
    "EventRecordDB",
]
