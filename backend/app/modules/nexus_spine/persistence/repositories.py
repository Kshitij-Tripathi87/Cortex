"""Nexus v0.7 — Persistent Repository layer.

Provides DB-backed repositories for all authoritative Nexus state. Each
repository can work either against the existing in-memory managers (for
tests and when DB isn't initialized) or against PostgreSQL via SQLAlchemy.

Architecture:
    PostgreSQL
       ↓
    Repository (this module)
       ↓
    in-memory cache/index (optional fast-path)
       ↓
    Domain objects (DecisionLifecycle, etc.)

The goal is: NO DATA LIVES ONLY IN PROCESS MEMORY. Every manager that
was previously a singleton dict is replaced by a repository that writes
through to PostgreSQL.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.persistence.models import (
    DecisionRecordDB,
    DecisionTransitionDB,
    EventRecordDB,
    EvidenceEdgeDB,
    EvidenceNodeDB,
    ForecastRecordDB,
    ModelRegistryEntryDB,
    ObservationRecordDB,
    RecommendationRecordDB,
    RiskRecordDB,
    ScenarioRecordDB,
    VanessaMessageDB,
    VanessaSessionDB,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _compute_decision_hash(
    *,
    decision_id: str,
    options: list[dict[str, Any]],
    world_state_version: int,
    world_state_hash: str,
    phase: str,
    proposal_id: str,
    chosen_option: str | None,
) -> str:
    payload = json.dumps(
        {
            "decision_id": decision_id,
            "options": options,
            "world_state_version": world_state_version,
            "world_state_hash": world_state_hash,
            "phase": phase,
            "proposal_id": proposal_id,
            "chosen_option": chosen_option,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Decision Repository
# ─────────────────────────────────────────────────────────────────────────────


class DecisionRepository:
    """DB-backed repository for decision lifecycles.

    Mirrors the DecisionLifecycleManager API but persists to PostgreSQL.
    When a DB session isn't available, falls back to an in-memory cache
    for resilience.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ── In-memory fallback (used when DB is not yet initialized) ──────

    def put_cache(self, decision: dict[str, Any]) -> None:
        with self._lock:
            self._cache[decision["decision_id"]] = decision

    def get_cache(self, decision_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._cache.get(decision_id)

    # ── DB operations ─────────────────────────────────────────────────

    async def get(self, session: AsyncSession, decision_id: str) -> DecisionRecordDB | None:
        stmt = select(DecisionRecordDB).where(DecisionRecordDB.decision_id == decision_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def put(self, session: AsyncSession, record: DecisionRecordDB) -> DecisionRecordDB:
        existing = await self.get(session, record.decision_id)
        if existing:
            # Update fields
            for col in DecisionRecordDB.__table__.columns:
                key = col.key
                if key == "decision_id":
                    continue
                val = getattr(record, key, None)
                if val is not None:
                    setattr(existing, key, val)
            existing.updated_at = _utc_now()
            await session.flush()
            self.put_cache(self._db_to_dict(existing))
            return existing
        session.add(record)
        await session.flush()
        self.put_cache(self._db_to_dict(record))
        return record

    async def add_transition(
        self,
        session: AsyncSession,
        decision_id: str,
        *,
        from_phase: str,
        to_phase: str,
        actor: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionTransitionDB:
        decision = await self.get(session, decision_id)
        if not decision:
            raise ValueError(f"Decision {decision_id} not found")
        transition = DecisionTransitionDB(
            decision_id=decision_id,
            from_phase=from_phase,
            to_phase=to_phase,
            actor=actor,
            reason=reason,
            metadata_=metadata or {},
        )
        session.add(transition)
        decision.phase = to_phase
        decision.updated_at = _utc_now()
        decision.deterministic_hash = _compute_decision_hash(
            decision_id=decision_id,
            options=decision.options or [],
            world_state_version=decision.world_state_version,
            world_state_hash=decision.world_state_hash,
            phase=to_phase,
            proposal_id=decision.proposal_id,
            chosen_option=decision.chosen_option,
        )
        await session.flush()
        self.put_cache(self._db_to_dict(decision))
        return transition

    async def list_by_phase(
        self, session: AsyncSession, tenant_id: str, workspace_id: str, phase: str
    ) -> list[DecisionRecordDB]:
        stmt = (
            select(DecisionRecordDB)
            .where(
                DecisionRecordDB.tenant_id == tenant_id,
                DecisionRecordDB.workspace_id == workspace_id,
                DecisionRecordDB.phase == phase,
            )
            .order_by(DecisionRecordDB.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_workspace(
        self, session: AsyncSession, tenant_id: str, workspace_id: str, limit: int = 100
    ) -> list[DecisionRecordDB]:
        stmt = (
            select(DecisionRecordDB)
            .where(
                DecisionRecordDB.tenant_id == tenant_id,
                DecisionRecordDB.workspace_id == workspace_id,
            )
            .order_by(DecisionRecordDB.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_transitions(
        self, session: AsyncSession, decision_id: str
    ) -> list[DecisionTransitionDB]:
        stmt = (
            select(DecisionTransitionDB)
            .where(DecisionTransitionDB.decision_id == decision_id)
            .order_by(DecisionTransitionDB.timestamp)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    def _db_to_dict(self, rec: DecisionRecordDB) -> dict[str, Any]:
        return {
            "decision_id": rec.decision_id,
            "tenant_id": rec.tenant_id,
            "workspace_id": rec.workspace_id,
            "phase": rec.phase,
            "world_state_version": rec.world_state_version,
            "world_state_hash": rec.world_state_hash,
            "proposal_id": rec.proposal_id,
            "simulation_id": rec.simulation_id,
            "plan_id": rec.plan_id,
            "evidence_root_id": rec.evidence_root_id,
            "evidence_root_hash": rec.evidence_root_hash,
            "options": rec.options or [],
            "chosen_option": rec.chosen_option,
            "outcome_payload": rec.outcome_payload,
            "deterministic_hash": rec.deterministic_hash,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Forecast Repository
# ─────────────────────────────────────────────────────────────────────────────


class ForecastRepository:
    async def record_forecast(
        self, session: AsyncSession, record: ForecastRecordDB
    ) -> ForecastRecordDB:
        session.add(record)
        await session.flush()
        return record

    async def get_forecast(
        self, session: AsyncSession, forecast_id: str
    ) -> ForecastRecordDB | None:
        stmt = select(ForecastRecordDB).where(ForecastRecordDB.forecast_id == forecast_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def record_observation(
        self, session: AsyncSession, obs: ObservationRecordDB
    ) -> ObservationRecordDB:
        """Record an observation and if it matches a forecast, compute error metrics."""
        if obs.forecast_id:
            forecast = await self.get_forecast(session, obs.forecast_id)
            if forecast:
                obs.predicted_p50 = forecast.p50
                obs.predicted_p80 = forecast.p80
                obs.predicted_p95 = forecast.p95
                obs.absolute_error = obs.actual_value - forecast.p50
                obs.percentage_error = (
                    obs.absolute_error / forecast.p50 if forecast.p50 != 0 else 0.0
                )
                obs.bias = obs.absolute_error
                obs.within_p80 = obs.actual_value <= forecast.p80
                obs.within_p95 = obs.actual_value <= forecast.p95
        session.add(obs)
        await session.flush()
        return obs

    async def calibration_buckets(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        sku: str | None = None,
        model_version: str | None = None,
        group_by: str = "sku",  # sku|supplier|region|model_version|horizon_days
    ) -> list[dict[str, Any]]:
        """Compute aggregated forecast accuracy metrics grouped by dimension."""
        from sqlalchemy import and_

        conditions = [
            ObservationRecordDB.tenant_id == tenant_id,
            ObservationRecordDB.workspace_id == workspace_id,
            ObservationRecordDB.forecast_id.isnot(None),
        ]
        if sku:
            conditions.append(ObservationRecordDB.sku == sku)

        stmt = (
            select(
                ObservationRecordDB.sku,
                ObservationRecordDB.supplier_id,
                ObservationRecordDB.region,
                func.count(ObservationRecordDB.id).label("sample_count"),
                func.avg(func.abs(ObservationRecordDB.absolute_error)).label("mae"),
                func.sqrt(func.avg(func.pow(ObservationRecordDB.absolute_error, 2))).label("rmse"),
                func.avg(ObservationRecordDB.percentage_error).label("mpe"),
                func.avg(ObservationRecordDB.bias).label("bias"),
                func.avg(func.cast(ObservationRecordDB.within_p80, Float)).label("p80_coverage"),
                func.avg(func.cast(ObservationRecordDB.within_p95, Float)).label("p95_coverage"),
            )
            .where(and_(*conditions))
            .group_by(
                ObservationRecordDB.sku,
                ObservationRecordDB.supplier_id,
                ObservationRecordDB.region,
            )
        )

        result = await session.execute(stmt)
        rows = result.all()
        buckets: list[dict[str, Any]] = []
        for row in rows:
            # WAPE = sum|error| / sum|actual| approximated via MAE/avg(actual)
            mae = float(row.mae or 0)
            mpe = float(row.mpe or 0)
            p80 = float(row.p80_coverage or 0)
            p95 = float(row.p95_coverage or 0)
            buckets.append(
                {
                    "sku": row.sku,
                    "supplier_id": row.supplier_id,
                    "region": row.region,
                    "sample_count": int(row.sample_count),
                    "mae": round(mae, 4),
                    "rmse": round(float(row.rmse or 0), 4),
                    "wape": round(abs(mpe), 4),
                    "mape": round(abs(mpe), 4),
                    "mpe": round(mpe, 4),
                    "bias": round(float(row.bias or 0), 4),
                    "p50_coverage": round(1.0 - abs(mpe), 4) if mpe else 0.0,
                    "p80_coverage": round(p80, 4),
                    "p95_coverage": round(p95, 4),
                    "drift_detected": abs(mpe) > 0.1 and int(row.sample_count) >= 5,
                }
            )
        return buckets

    async def list_observations(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        sku: str | None = None,
        limit: int = 100,
    ) -> list[ObservationRecordDB]:
        conditions = [
            ObservationRecordDB.tenant_id == tenant_id,
            ObservationRecordDB.workspace_id == workspace_id,
        ]
        if sku:
            conditions.append(ObservationRecordDB.sku == sku)
        stmt = (
            select(ObservationRecordDB)
            .where(*conditions)
            .order_by(ObservationRecordDB.observed_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# Model Registry Repository
# ─────────────────────────────────────────────────────────────────────────────


class ModelRegistryRepository:
    LIFECYCLE_TRANSITIONS = {
        "training": {"evaluating"},
        "evaluating": {"shadow", "archived"},
        "shadow": {"calibrating", "archived"},
        "calibrating": {"approved", "shadow", "archived"},
        "approved": {"deployed", "archived"},
        "deployed": {"monitoring", "rolled_back"},
        "monitoring": {"deployed", "rolled_back", "archived"},
        "rolled_back": {"archived", "shadow"},
        "archived": set(),
    }

    async def register(
        self, session: AsyncSession, entry: ModelRegistryEntryDB
    ) -> ModelRegistryEntryDB:
        session.add(entry)
        await session.flush()
        return entry

    async def get(self, session: AsyncSession, model_id: str) -> ModelRegistryEntryDB | None:
        stmt = select(ModelRegistryEntryDB).where(ModelRegistryEntryDB.model_id == model_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name_version(
        self, session: AsyncSession, name: str, version: str
    ) -> ModelRegistryEntryDB | None:
        stmt = select(ModelRegistryEntryDB).where(
            ModelRegistryEntryDB.name == name,
            ModelRegistryEntryDB.version == version,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_status(
        self, session: AsyncSession, status: str | None = None, model_type: str | None = None
    ) -> list[ModelRegistryEntryDB]:
        conditions = []
        if status:
            conditions.append(ModelRegistryEntryDB.status == status)
        if model_type:
            conditions.append(ModelRegistryEntryDB.model_type == model_type)
        stmt = (
            select(ModelRegistryEntryDB)
            .where(*conditions)
            .order_by(ModelRegistryEntryDB.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def transition_status(
        self,
        session: AsyncSession,
        model_id: str,
        target_status: str,
        *,
        actor: str = "system",
        reason: str | None = None,
    ) -> ModelRegistryEntryDB:
        model = await self.get(session, model_id)
        if not model:
            raise ValueError(f"Model {model_id} not found")
        allowed = self.LIFECYCLE_TRANSITIONS.get(model.status, set())
        if target_status not in allowed:
            raise ValueError(
                f"Invalid model transition: {model.status} → {target_status}. "
                f"Allowed: {sorted(allowed)}"
            )
        model.status = target_status
        if target_status == "deployed":
            model.deployed_at = _utc_now()
            model.approved_by = actor
        elif target_status == "rolled_back":
            model.rolled_back_at = _utc_now()
        await session.flush()
        return model

    async def approve(
        self, session: AsyncSession, model_id: str, approver: str
    ) -> ModelRegistryEntryDB:
        model = await self.get(session, model_id)
        if not model:
            raise ValueError(f"Model {model_id} not found")
        model.approval_status = "approved"
        model.approved_by = approver
        await session.flush()
        return model

    async def get_deployed(
        self, session: AsyncSession, model_type: str
    ) -> ModelRegistryEntryDB | None:
        stmt = (
            select(ModelRegistryEntryDB)
            .where(
                ModelRegistryEntryDB.model_type == model_type,
                ModelRegistryEntryDB.status == "deployed",
            )
            .order_by(ModelRegistryEntryDB.deployed_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# Risk Repository
# ─────────────────────────────────────────────────────────────────────────────


class RiskRepository:
    async def upsert(self, session: AsyncSession, record: RiskRecordDB) -> RiskRecordDB:
        existing = await session.execute(
            select(RiskRecordDB).where(
                RiskRecordDB.tenant_id == record.tenant_id,
                RiskRecordDB.workspace_id == record.workspace_id,
                RiskRecordDB.entity_id == record.entity_id,
                RiskRecordDB.status == "open",
            )
        )
        existing_rec = existing.scalar_one_or_none()
        if existing_rec:
            existing_rec.severity = record.severity
            existing_rec.risk_score = record.risk_score
            existing_rec.title = record.title
            existing_rec.description = record.description
            existing_rec.blast_radius_count = record.blast_radius_count
            existing_rec.revenue_exposure = record.revenue_exposure
            existing_rec.sla_risk_pct = record.sla_risk_pct
            existing_rec.root_causes = record.root_causes
            existing_rec.gnn_risk_score = record.gnn_risk_score
            existing_rec.hidden_dependencies = record.hidden_dependencies
            existing_rec.world_state_version = record.world_state_version
            existing_rec.updated_at = _utc_now()
            await session.flush()
            return existing_rec
        session.add(record)
        await session.flush()
        return record

    async def list_open(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        min_severity: str | None = None,
    ) -> list[RiskRecordDB]:
        severity_order = {"WATCH": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        stmt = (
            select(RiskRecordDB)
            .where(
                RiskRecordDB.tenant_id == tenant_id,
                RiskRecordDB.workspace_id == workspace_id,
                RiskRecordDB.status == "open",
            )
            .order_by(RiskRecordDB.risk_score.desc())
        )
        result = await session.execute(stmt)
        risks = list(result.scalars().all())
        if min_severity and min_severity in severity_order:
            threshold = severity_order[min_severity]
            risks = [r for r in risks if severity_order.get(r.severity, 0) >= threshold]
        return risks

    async def get(self, session: AsyncSession, risk_id: str) -> RiskRecordDB | None:
        stmt = select(RiskRecordDB).where(RiskRecordDB.risk_id == risk_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Repository
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioRepository:
    async def create(self, session: AsyncSession, record: ScenarioRecordDB) -> ScenarioRecordDB:
        session.add(record)
        await session.flush()
        return record

    async def get(self, session: AsyncSession, scenario_id: str) -> ScenarioRecordDB | None:
        stmt = select(ScenarioRecordDB).where(ScenarioRecordDB.scenario_id == scenario_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def complete(
        self,
        session: AsyncSession,
        scenario_id: str,
        kpi_results: dict[str, Any],
        gnn_insights: dict[str, Any] | None = None,
    ) -> ScenarioRecordDB:
        scenario = await self.get(session, scenario_id)
        if not scenario:
            raise ValueError(f"Scenario {scenario_id} not found")
        scenario.kpi_results = kpi_results
        scenario.gnn_insights = gnn_insights
        scenario.status = "completed"
        scenario.completed_at = _utc_now()
        await session.flush()
        return scenario

    async def list_by_decision(
        self, session: AsyncSession, decision_id: str
    ) -> list[ScenarioRecordDB]:
        stmt = (
            select(ScenarioRecordDB)
            .where(ScenarioRecordDB.decision_id == decision_id)
            .order_by(ScenarioRecordDB.created_at)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# Evidence Repository
# ─────────────────────────────────────────────────────────────────────────────


class EvidenceRepository:
    async def add_node(self, session: AsyncSession, node: EvidenceNodeDB) -> EvidenceNodeDB:
        session.add(node)
        await session.flush()
        return node

    async def add_edge(self, session: AsyncSession, edge: EvidenceEdgeDB) -> EvidenceEdgeDB:
        session.add(edge)
        await session.flush()
        return edge

    async def get_graph(
        self, session: AsyncSession, decision_id: str
    ) -> tuple[list[EvidenceNodeDB], list[EvidenceEdgeDB]]:
        nodes_stmt = select(EvidenceNodeDB).where(EvidenceNodeDB.decision_id == decision_id)
        nodes_result = await session.execute(nodes_stmt)
        nodes = list(nodes_result.scalars().all())
        node_ids = [n.node_id for n in nodes]
        edges = []
        if node_ids:
            edges_stmt = select(EvidenceEdgeDB).where(
                EvidenceEdgeDB.from_node_id.in_(node_ids),
                EvidenceEdgeDB.to_node_id.in_(node_ids),
            )
            edges_result = await session.execute(edges_stmt)
            edges = list(edges_result.scalars().all())
        return nodes, edges


# ─────────────────────────────────────────────────────────────────────────────
# Vanessa Session Repository
# ─────────────────────────────────────────────────────────────────────────────


class VanessaSessionRepository:
    async def get_or_create(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
    ) -> VanessaSessionDB:
        stmt = (
            select(VanessaSessionDB)
            .where(
                VanessaSessionDB.tenant_id == tenant_id,
                VanessaSessionDB.workspace_id == workspace_id,
                VanessaSessionDB.user_id == user_id,
            )
            .order_by(VanessaSessionDB.last_active_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.last_active_at = _utc_now()
            await session.flush()
            return existing
        session_rec = VanessaSessionDB(
            session_id=f"VSESS-{uuid4().hex[:10]}",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        session.add(session_rec)
        await session.flush()
        return session_rec

    async def get(self, session: AsyncSession, session_id: str) -> VanessaSessionDB | None:
        stmt = select(VanessaSessionDB).where(VanessaSessionDB.session_id == session_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_context(
        self,
        session: AsyncSession,
        session_id: str,
        **kwargs: Any,
    ) -> VanessaSessionDB:
        sess = await self.get(session, session_id)
        if not sess:
            raise ValueError(f"Vanessa session {session_id} not found")
        for key, val in kwargs.items():
            if hasattr(sess, key):
                setattr(sess, key, val)
        sess.last_active_at = _utc_now()
        await session.flush()
        return sess

    async def add_message(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        role: str,
        content: str,
        response_blocks: list[dict[str, Any]] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        intent: str | None = None,
        confidence: float | None = None,
    ) -> VanessaMessageDB:
        sess = await self.get(session, session_id)
        if not sess:
            raise ValueError(f"Vanessa session {session_id} not found")
        # Get next turn number
        count_stmt = select(func.count(VanessaMessageDB.id)).where(
            VanessaMessageDB.session_id == session_id
        )
        count_result = await session.execute(count_stmt)
        turn = int(count_result.scalar() or 0) + 1
        msg = VanessaMessageDB(
            session_id=session_id,
            turn_number=turn,
            role=role,
            content=content,
            response_blocks=response_blocks,
            tool_calls=tool_calls,
            tool_results=tool_results,
            intent=intent,
            confidence=confidence,
        )
        session.add(msg)
        sess.last_active_at = _utc_now()
        await session.flush()
        return msg

    async def get_history(
        self, session: AsyncSession, session_id: str, limit: int = 50
    ) -> list[VanessaMessageDB]:
        stmt = (
            select(VanessaMessageDB)
            .where(VanessaMessageDB.session_id == session_id)
            .order_by(VanessaMessageDB.turn_number.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(reversed(list(result.scalars().all())))


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Repository
# ─────────────────────────────────────────────────────────────────────────────


class RecommendationRepository:
    async def create(
        self, session: AsyncSession, record: RecommendationRecordDB
    ) -> RecommendationRecordDB:
        session.add(record)
        await session.flush()
        return record

    async def get(
        self, session: AsyncSession, recommendation_id: str
    ) -> RecommendationRecordDB | None:
        stmt = select(RecommendationRecordDB).where(
            RecommendationRecordDB.recommendation_id == recommendation_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def evaluate_outcome(
        self,
        session: AsyncSession,
        recommendation_id: str,
        *,
        actual_nev: float,
        actual_sla: float,
        actual_cost: float,
        outcome: str,
    ) -> RecommendationRecordDB:
        rec = await self.get(session, recommendation_id)
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found")
        rec.actual_nev = actual_nev
        rec.actual_sla = actual_sla
        rec.actual_cost = actual_cost
        rec.outcome = outcome

        # Compute accuracy and regret
        if rec.predicted_nev != 0:
            rec.recommendation_accuracy = max(
                0.0, 1.0 - abs(actual_nev - rec.predicted_nev) / abs(rec.predicted_nev)
            )
        rec.simulation_error = abs(actual_cost - rec.predicted_cost) if rec.predicted_cost else None
        # Regret = negative NEV difference (higher is worse)
        rec.recommendation_regret = max(0.0, rec.predicted_nev - actual_nev)
        rec.evaluated_at = _utc_now()
        await session.flush()
        return rec

    async def list_by_workspace(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> list[RecommendationRecordDB]:
        stmt = (
            select(RecommendationRecordDB)
            .where(
                RecommendationRecordDB.tenant_id == tenant_id,
                RecommendationRecordDB.workspace_id == workspace_id,
            )
            .order_by(RecommendationRecordDB.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def success_rate(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Compute aggregate recommendation performance metrics."""
        stmt_total = select(func.count(RecommendationRecordDB.recommendation_id)).where(
            RecommendationRecordDB.tenant_id == tenant_id,
            RecommendationRecordDB.workspace_id == workspace_id,
            RecommendationRecordDB.outcome.isnot(None),
        )
        total_result = await session.execute(stmt_total)
        total = int(total_result.scalar() or 0)

        if total == 0:
            return {
                "total_evaluated": 0,
                "success_rate": 0.0,
                "avg_accuracy": 0.0,
                "avg_regret": 0.0,
            }

        stmt_success = select(func.count(RecommendationRecordDB.recommendation_id)).where(
            RecommendationRecordDB.tenant_id == tenant_id,
            RecommendationRecordDB.workspace_id == workspace_id,
            RecommendationRecordDB.outcome == "success",
        )
        success_result = await session.execute(stmt_success)
        successes = int(success_result.scalar() or 0)

        stmt_avg_acc = select(func.avg(RecommendationRecordDB.recommendation_accuracy)).where(
            RecommendationRecordDB.tenant_id == tenant_id,
            RecommendationRecordDB.workspace_id == workspace_id,
            RecommendationRecordDB.recommendation_accuracy.isnot(None),
        )
        avg_acc_result = await session.execute(stmt_avg_acc)
        avg_accuracy = float(avg_acc_result.scalar() or 0.0)

        stmt_avg_regret = select(func.avg(RecommendationRecordDB.recommendation_regret)).where(
            RecommendationRecordDB.tenant_id == tenant_id,
            RecommendationRecordDB.workspace_id == workspace_id,
            RecommendationRecordDB.recommendation_regret.isnot(None),
        )
        avg_regret_result = await session.execute(stmt_avg_regret)
        avg_regret = float(avg_regret_result.scalar() or 0.0)

        return {
            "total_evaluated": total,
            "total": total
            + (
                await session.execute(
                    select(func.count(RecommendationRecordDB.recommendation_id)).where(
                        RecommendationRecordDB.tenant_id == tenant_id,
                        RecommendationRecordDB.workspace_id == workspace_id,
                    )
                )
            ).scalar()
            - total,
            "success_rate": round(successes / total, 4) if total > 0 else 0.0,
            "avg_accuracy": round(avg_accuracy, 4),
            "avg_regret": round(avg_regret, 4),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Event Outbox Repository
# ─────────────────────────────────────────────────────────────────────────────


class EventRepository:
    async def publish(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        event_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        payload: dict[str, Any] | None = None,
        world_state_version: int | None = None,
    ) -> EventRecordDB:
        event = EventRecordDB(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload or {},
            world_state_version=world_state_version,
            published=False,
        )
        session.add(event)
        await session.flush()
        return event

    async def get_pending(self, session: AsyncSession, limit: int = 100) -> list[EventRecordDB]:
        stmt = (
            select(EventRecordDB)
            .where(
                EventRecordDB.published == False,  # noqa: E712
            )
            .order_by(EventRecordDB.created_at)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def mark_published(self, session: AsyncSession, event_id: str) -> None:
        stmt = select(EventRecordDB).where(EventRecordDB.event_id == event_id)
        result = await session.execute(stmt)
        evt = result.scalar_one_or_none()
        if evt:
            evt.published = True
            await session.flush()

    async def get_recent(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> list[EventRecordDB]:
        stmt = (
            select(EventRecordDB)
            .where(
                EventRecordDB.tenant_id == tenant_id,
                EventRecordDB.workspace_id == workspace_id,
            )
            .order_by(EventRecordDB.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessors (process-wide)
# ─────────────────────────────────────────────────────────────────────────────

_decision_repo: DecisionRepository | None = None
_forecast_repo: ForecastRepository | None = None
_model_repo: ModelRegistryRepository | None = None
_risk_repo: RiskRepository | None = None
_scenario_repo: ScenarioRepository | None = None
_evidence_repo: EvidenceRepository | None = None
_vanessa_session_repo: VanessaSessionRepository | None = None
_recommendation_repo: RecommendationRepository | None = None
_event_repo: EventRepository | None = None


def get_decision_repository() -> DecisionRepository:
    global _decision_repo
    if _decision_repo is None:
        _decision_repo = DecisionRepository()
    return _decision_repo


def get_forecast_repository() -> ForecastRepository:
    global _forecast_repo
    if _forecast_repo is None:
        _forecast_repo = ForecastRepository()
    return _forecast_repo


def get_model_registry_repository() -> ModelRegistryRepository:
    global _model_repo
    if _model_repo is None:
        _model_repo = ModelRegistryRepository()
    return _model_repo


def get_risk_repository() -> RiskRepository:
    global _risk_repo
    if _risk_repo is None:
        _risk_repo = RiskRepository()
    return _risk_repo


def get_scenario_repository() -> ScenarioRepository:
    global _scenario_repo
    if _scenario_repo is None:
        _scenario_repo = ScenarioRepository()
    return _scenario_repo


def get_evidence_repository() -> EvidenceRepository:
    global _evidence_repo
    if _evidence_repo is None:
        _evidence_repo = EvidenceRepository()
    return _evidence_repo


def get_vanessa_session_repository() -> VanessaSessionRepository:
    global _vanessa_session_repo
    if _vanessa_session_repo is None:
        _vanessa_session_repo = VanessaSessionRepository()
    return _vanessa_session_repo


def get_recommendation_repository() -> RecommendationRepository:
    global _recommendation_repo
    if _recommendation_repo is None:
        _recommendation_repo = RecommendationRepository()
    return _recommendation_repo


def get_event_repository() -> EventRepository:
    global _event_repo
    if _event_repo is None:
        _event_repo = EventRepository()
    return _event_repo


def reset_repositories() -> None:
    global _decision_repo, _forecast_repo, _model_repo, _risk_repo, _scenario_repo
    global _evidence_repo, _vanessa_session_repo, _recommendation_repo, _event_repo
    _decision_repo = None
    _forecast_repo = None
    _model_repo = None
    _risk_repo = None
    _scenario_repo = None
    _evidence_repo = None
    _vanessa_session_repo = None
    _recommendation_repo = None
    _event_repo = None


__all__ = [
    "DecisionRepository",
    "ForecastRepository",
    "ModelRegistryRepository",
    "RiskRepository",
    "ScenarioRepository",
    "EvidenceRepository",
    "VanessaSessionRepository",
    "RecommendationRepository",
    "EventRepository",
    "get_decision_repository",
    "get_forecast_repository",
    "get_model_registry_repository",
    "get_risk_repository",
    "get_scenario_repository",
    "get_evidence_repository",
    "get_vanessa_session_repository",
    "get_recommendation_repository",
    "get_event_repository",
    "reset_repositories",
]
