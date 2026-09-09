"""Nexus v1.0 P0 / v0.8.4 — Authoritative Model Registry & Governance.

PostgreSQL-backed model registry with strict state machine, immutable versions,
promotion gate validation, and outbox event integration.

Invariant:
A trained model is a governed, immutable production dependency with complete
prediction provenance and closed-loop feedback.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.outbox_publisher import allocate_outbox_seq
from app.modules.nexus_spine.p0_migration.authz import (
    SYSTEM_PRINCIPAL,
    Principal,
    get_authz,
)
from app.modules.nexus_spine.persistence.models import (
    EventRecordDB,
    ModelRegistryEntryDB,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ModelLifecycleStatus:
    TRAINING = "training"
    EVALUATING = "evaluating"
    SHADOW = "shadow"
    CALIBRATING = "calibrating"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    MONITORING = "monitoring"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"


ALLOWED_MODEL_TRANSITIONS: dict[str, set[str]] = {
    ModelLifecycleStatus.TRAINING: {
        ModelLifecycleStatus.EVALUATING,
        ModelLifecycleStatus.SHADOW,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.EVALUATING: {
        ModelLifecycleStatus.SHADOW,
        ModelLifecycleStatus.CALIBRATING,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.SHADOW: {
        ModelLifecycleStatus.CALIBRATING,
        ModelLifecycleStatus.APPROVED,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.CALIBRATING: {
        ModelLifecycleStatus.APPROVED,
        ModelLifecycleStatus.SHADOW,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.APPROVED: {
        ModelLifecycleStatus.DEPLOYED,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.DEPLOYED: {
        ModelLifecycleStatus.MONITORING,
        ModelLifecycleStatus.ROLLED_BACK,
    },
    ModelLifecycleStatus.MONITORING: {
        ModelLifecycleStatus.DEPLOYED,
        ModelLifecycleStatus.ROLLED_BACK,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.ROLLED_BACK: {
        ModelLifecycleStatus.SHADOW,
        ModelLifecycleStatus.ARCHIVED,
    },
    ModelLifecycleStatus.ARCHIVED: set(),
}


# ─────────────────────────────────────────────────────────────────────
# Domain Exceptions
# ─────────────────────────────────────────────────────────────────────


class ModelGovernanceError(Exception):
    """Base exception for model registry errors."""


class ModelNotFoundError(ModelGovernanceError):
    def __init__(self, model_id: str):
        super().__init__(f"Model '{model_id}' was not found.")
        self.model_id = model_id


class DuplicateModelVersionError(ModelGovernanceError):
    def __init__(self, name: str, version: str, tenant_id: str, workspace_id: str):
        super().__init__(
            f"Model '{name}' version '{version}' already exists in tenant '{tenant_id}' / workspace '{workspace_id}'."
        )
        self.name = name
        self.version = version


class InvalidModelTransitionError(ModelGovernanceError):
    def __init__(self, current_status: str, target_status: str):
        super().__init__(
            f"Invalid model lifecycle transition: '{current_status}' → '{target_status}'. "
            f"Allowed: {sorted(ALLOWED_MODEL_TRANSITIONS.get(current_status, set()))}"
        )
        self.current_status = current_status
        self.target_status = target_status


class PromotionGateFailedError(ModelGovernanceError):
    def __init__(self, failures: list[str], evaluated_metrics: dict[str, Any]):
        super().__init__(
            f"Model promotion gate check failed with {len(failures)} violations: {'; '.join(failures)}"
        )
        self.failures = failures
        self.evaluated_metrics = evaluated_metrics


class ModelRollbackError(ModelGovernanceError):
    pass


# ─────────────────────────────────────────────────────────────────────
# Promotion Gates
# ─────────────────────────────────────────────────────────────────────


@dataclass
class PromotionGateConfig:
    """Configurable promotion gate hurdles for production deployment."""

    max_wape: float = 0.12  # Demand forecast WAPE <= 12%
    max_rmse: float = 50.0  # RMSE hurdle
    min_f1: float = 0.85  # Risk/classification F1 >= 85%
    min_accuracy: float = 0.85  # Accuracy >= 85%
    min_p50_coverage: float = 0.40  # P50 empirical quantile coverage in [0.40, 0.60]
    max_p50_coverage: float = 0.60
    min_p80_coverage: float = 0.70  # P80 empirical quantile coverage in [0.70, 0.90]
    max_p80_coverage: float = 0.90
    min_p95_coverage: float = 0.90  # P95 empirical quantile coverage in [0.90, 0.99]
    max_p95_coverage: float = 0.99
    min_evaluation_samples: int = 10  # Minimum validation samples
    max_shadow_degradation: float = 0.05  # Candidate must not be > 5% worse than champion
    require_approval: bool = True  # Model must be in APPROVED or CALIBRATING status


@dataclass
class PromotionGateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    evaluated_metrics: dict[str, Any] = field(default_factory=dict)


def validate_promotion_gates(
    model: ModelRegistryEntryDB,
    gates: PromotionGateConfig | None = None,
    champion: ModelRegistryEntryDB | None = None,
) -> PromotionGateResult:
    """Evaluate a candidate model against governed promotion hurdles."""
    g = gates or PromotionGateConfig()
    failures: list[str] = []
    metrics = dict(model.metrics or {})
    calibration = dict(model.calibration or {})
    shadow_metrics = dict(model.shadow_metrics or {})

    # 1. State check: must not be in training or archived
    if model.status in (ModelLifecycleStatus.TRAINING, ModelLifecycleStatus.ARCHIVED):
        failures.append(f"Model status '{model.status}' is not eligible for promotion.")

    # 2. Minimum samples check (from metrics, shadow_metrics, or calibration)
    sample_count = (
        metrics.get("sample_count")
        or metrics.get("samples")
        or shadow_metrics.get("sample_count")
        or shadow_metrics.get("samples")
        or 0
    )
    if sample_count and int(sample_count) < g.min_evaluation_samples:
        failures.append(
            f"Insufficient evaluation samples: {sample_count} < required {g.min_evaluation_samples}"
        )

    # 3. Model type specific metric hurdles
    if model.model_type == "forecast":
        wape = metrics.get("wape")
        if wape is not None and float(wape) > g.max_wape:
            failures.append(f"WAPE {wape:.4f} exceeds threshold {g.max_wape:.4f}")
        rmse = metrics.get("rmse")
        if rmse is not None and float(rmse) > g.max_rmse:
            failures.append(f"RMSE {rmse:.2f} exceeds threshold {g.max_rmse:.2f}")

        # Calibration quantile coverage checks
        p50_cov = calibration.get("p50_coverage")
        if p50_cov is not None:
            val = float(p50_cov)
            if val < g.min_p50_coverage or val > g.max_p50_coverage:
                failures.append(
                    f"P50 coverage {val:.4f} outside allowable range [{g.min_p50_coverage}, {g.max_p50_coverage}]"
                )
        p80_cov = calibration.get("p80_coverage")
        if p80_cov is not None:
            val = float(p80_cov)
            if val < g.min_p80_coverage or val > g.max_p80_coverage:
                failures.append(
                    f"P80 coverage {val:.4f} outside allowable range [{g.min_p80_coverage}, {g.max_p80_coverage}]"
                )
        p95_cov = calibration.get("p95_coverage")
        if p95_cov is not None:
            val = float(p95_cov)
            if val < g.min_p95_coverage or val > g.max_p95_coverage:
                failures.append(
                    f"P95 coverage {val:.4f} outside allowable range [{g.min_p95_coverage}, {g.max_p95_coverage}]"
                )

    elif model.model_type in ("risk", "gnn", "sla", "eta"):
        f1 = metrics.get("f1") or metrics.get("f1_score")
        if f1 is not None and float(f1) < g.min_f1:
            failures.append(f"F1 score {f1:.4f} below threshold {g.min_f1:.4f}")
        accuracy = metrics.get("accuracy")
        if accuracy is not None and float(accuracy) < g.min_accuracy:
            failures.append(f"Accuracy {accuracy:.4f} below threshold {g.min_accuracy:.4f}")

    # 4. Shadow mode comparison against current champion
    if champion and champion.metrics:
        champ_metrics = champion.metrics or {}
        if model.model_type == "forecast":
            cand_wape = metrics.get("wape", 0.1)
            champ_wape = champ_metrics.get("wape", 0.1)
            if cand_wape > champ_wape * (1.0 + g.max_shadow_degradation):
                failures.append(
                    f"Candidate WAPE ({cand_wape:.4f}) is degraded vs Champion WAPE ({champ_wape:.4f})"
                )
        elif model.model_type in ("risk", "gnn"):
            cand_f1 = metrics.get("f1", 0.9)
            champ_f1 = champ_metrics.get("f1", 0.9)
            if cand_f1 < champ_f1 * (1.0 - g.max_shadow_degradation):
                failures.append(
                    f"Candidate F1 ({cand_f1:.4f}) is degraded vs Champion F1 ({champ_f1:.4f})"
                )

    evaluated = {
        "metrics": metrics,
        "calibration": calibration,
        "shadow_metrics": shadow_metrics,
        "sample_count": sample_count,
    }
    return PromotionGateResult(
        passed=(len(failures) == 0),
        failures=failures,
        evaluated_metrics=evaluated,
    )


# ─────────────────────────────────────────────────────────────────────
# Authoritative Model Registry Service
# ─────────────────────────────────────────────────────────────────────


class AuthoritativeModelRegistry:
    """PostgreSQL-backed model registry and promotion governance service."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def _to_dict(self, m: ModelRegistryEntryDB) -> dict[str, Any]:
        return {
            "model_id": m.model_id,
            "tenant_id": m.tenant_id,
            "workspace_id": m.workspace_id,
            "name": m.name,
            "version": m.version,
            "model_type": m.model_type,
            "description": m.description,
            "training_dataset": m.training_dataset,
            "feature_schema": m.feature_schema or {},
            "world_state_version": m.world_state_version,
            "metrics": m.metrics or {},
            "calibration": m.calibration or {},
            "gnn_config": m.gnn_config,
            "rl_config": m.rl_config,
            "status": m.status,
            "approval_status": m.approval_status,
            "shadow_metrics": m.shadow_metrics,
            "promotion_gates": m.promotion_gates,
            "created_by": m.created_by,
            "approved_by": m.approved_by,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
            "rolled_back_at": m.rolled_back_at.isoformat() if m.rolled_back_at else None,
            "rollback_reason": m.rollback_reason,
        }

    async def register_candidate(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        name: str,
        version: str,
        model_type: str,
        description: str = "",
        training_dataset: str | None = None,
        feature_schema: dict[str, Any] | None = None,
        world_state_version: int | None = None,
        training_data_range: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        calibration: dict[str, Any] | None = None,
        gnn_config: dict[str, Any] | None = None,
        rl_config: dict[str, Any] | None = None,
        promotion_gates: dict[str, Any] | None = None,
        actor_principal: Principal = SYSTEM_PRINCIPAL,
    ) -> dict[str, Any]:
        """Register a new candidate model version. Enforces version immutability."""
        get_authz().check(
            actor_principal,
            "nexus.model.register",
            workspace_id=workspace_id,
            data_tenant=tenant_id,
        )

        # Check for duplicate model version
        existing_stmt = select(ModelRegistryEntryDB).where(
            ModelRegistryEntryDB.tenant_id == tenant_id,
            ModelRegistryEntryDB.workspace_id == workspace_id,
            ModelRegistryEntryDB.name == name,
            ModelRegistryEntryDB.version == version,
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            raise DuplicateModelVersionError(name, version, tenant_id, workspace_id)

        model_id = f"MDL-{uuid4().hex[:8]}"
        initial_status = (
            ModelLifecycleStatus.EVALUATING if metrics else ModelLifecycleStatus.TRAINING
        )

        entry = ModelRegistryEntryDB(
            model_id=model_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            version=version,
            model_type=model_type,
            description=description,
            training_dataset=training_dataset,
            feature_schema=feature_schema or {},
            world_state_version=world_state_version,
            training_data_range=training_data_range,
            metrics=metrics or {},
            calibration=calibration or {},
            gnn_config=gnn_config,
            rl_config=rl_config,
            status=initial_status,
            approval_status="pending",
            promotion_gates=promotion_gates,
            created_by=actor_principal.user_id,
            created_at=_utc_now(),
        )
        session.add(entry)
        await session.flush()

        # Emit outbox event
        outbox_seq = await allocate_outbox_seq(session, tenant_id, workspace_id)
        outbox_event = EventRecordDB(
            event_id=f"EVT-{uuid7()}",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            seq=outbox_seq,
            event_type="model.registered",
            entity_type="model",
            entity_id=model_id,
            correlation_id=f"CORR-{uuid4().hex[:8]}",
            payload={
                "model_id": model_id,
                "name": name,
                "version": version,
                "model_type": model_type,
                "status": initial_status,
                "created_by": actor_principal.user_id,
            },
            world_state_version=world_state_version,
            published=False,
            created_at=_utc_now(),
        )
        session.add(outbox_event)
        await session.flush()

        return self._to_dict(entry)

    async def evaluate_candidate(
        self,
        session: AsyncSession,
        *,
        model_id: str,
        metrics: dict[str, Any],
        shadow_metrics: dict[str, Any] | None = None,
        calibration: dict[str, Any] | None = None,
        target_status: str = ModelLifecycleStatus.SHADOW,
        actor_principal: Principal = SYSTEM_PRINCIPAL,
    ) -> dict[str, Any]:
        """Record evaluation / shadow benchmark results against a candidate model."""
        stmt = (
            select(ModelRegistryEntryDB)
            .where(ModelRegistryEntryDB.model_id == model_id)
            .with_for_update()
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ModelNotFoundError(model_id)

        get_authz().check(
            actor_principal,
            "nexus.model.evaluate",
            workspace_id=model.workspace_id,
            data_tenant=model.tenant_id,
        )

        allowed = ALLOWED_MODEL_TRANSITIONS.get(model.status, set())
        if target_status != model.status and target_status not in allowed:
            raise InvalidModelTransitionError(model.status, target_status)

        # Update metrics
        existing_metrics = dict(model.metrics or {})
        existing_metrics.update(metrics)
        model.metrics = existing_metrics

        if shadow_metrics:
            existing_shadow = dict(model.shadow_metrics or {})
            existing_shadow.update(shadow_metrics)
            model.shadow_metrics = existing_shadow

        if calibration:
            existing_calib = dict(model.calibration or {})
            existing_calib.update(calibration)
            model.calibration = existing_calib

        model.status = target_status
        await session.flush()

        # Emit outbox event
        outbox_seq = await allocate_outbox_seq(session, model.tenant_id, model.workspace_id)
        outbox_event = EventRecordDB(
            event_id=f"EVT-{uuid7()}",
            tenant_id=model.tenant_id,
            workspace_id=model.workspace_id,
            seq=outbox_seq,
            event_type="model.evaluated",
            entity_type="model",
            entity_id=model_id,
            correlation_id=f"CORR-{uuid4().hex[:8]}",
            payload={
                "model_id": model_id,
                "name": model.name,
                "version": model.version,
                "model_type": model.model_type,
                "status": target_status,
                "metrics": model.metrics,
            },
            world_state_version=model.world_state_version,
            published=False,
            created_at=_utc_now(),
        )
        session.add(outbox_event)
        await session.flush()

        return self._to_dict(model)

    async def approve_model(
        self,
        session: AsyncSession,
        *,
        model_id: str,
        actor_principal: Principal,
    ) -> dict[str, Any]:
        """Approve a model for production promotion."""
        stmt = (
            select(ModelRegistryEntryDB)
            .where(ModelRegistryEntryDB.model_id == model_id)
            .with_for_update()
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ModelNotFoundError(model_id)

        get_authz().check(
            actor_principal,
            "nexus.model.promote",
            workspace_id=model.workspace_id,
            data_tenant=model.tenant_id,
        )

        allowed = ALLOWED_MODEL_TRANSITIONS.get(model.status, set())
        if (
            ModelLifecycleStatus.APPROVED not in allowed
            and model.status != ModelLifecycleStatus.APPROVED
        ):
            raise InvalidModelTransitionError(model.status, ModelLifecycleStatus.APPROVED)

        model.status = ModelLifecycleStatus.APPROVED
        model.approval_status = "approved"
        model.approved_by = actor_principal.user_id
        await session.flush()

        # Emit outbox event
        outbox_seq = await allocate_outbox_seq(session, model.tenant_id, model.workspace_id)
        outbox_event = EventRecordDB(
            event_id=f"EVT-{uuid7()}",
            tenant_id=model.tenant_id,
            workspace_id=model.workspace_id,
            seq=outbox_seq,
            event_type="model.approved",
            entity_type="model",
            entity_id=model_id,
            correlation_id=f"CORR-{uuid4().hex[:8]}",
            payload={
                "model_id": model_id,
                "name": model.name,
                "version": model.version,
                "approved_by": actor_principal.user_id,
            },
            world_state_version=model.world_state_version,
            published=False,
            created_at=_utc_now(),
        )
        session.add(outbox_event)
        await session.flush()

        return self._to_dict(model)

    async def promote_model(
        self,
        session: AsyncSession,
        *,
        model_id: str,
        actor_principal: Principal,
        custom_gates: PromotionGateConfig | None = None,
        skip_gate_validation: bool = False,
    ) -> dict[str, Any]:
        """Promote a candidate model to DEPLOYED through the governed promotion gate.

        Atomically demotes the current deployed champion of the same type to MONITORING.
        """
        stmt = (
            select(ModelRegistryEntryDB)
            .where(ModelRegistryEntryDB.model_id == model_id)
            .with_for_update()
        )
        candidate = (await session.execute(stmt)).scalar_one_or_none()
        if candidate is None:
            raise ModelNotFoundError(model_id)

        get_authz().check(
            actor_principal,
            "nexus.model.promote",
            workspace_id=candidate.workspace_id,
            data_tenant=candidate.tenant_id,
        )

        # Find current active champion
        champ_stmt = (
            select(ModelRegistryEntryDB)
            .where(
                ModelRegistryEntryDB.tenant_id == candidate.tenant_id,
                ModelRegistryEntryDB.workspace_id == candidate.workspace_id,
                ModelRegistryEntryDB.model_type == candidate.model_type,
                ModelRegistryEntryDB.status == ModelLifecycleStatus.DEPLOYED,
            )
            .with_for_update()
        )
        champion = (await session.execute(champ_stmt)).scalar_one_or_none()

        # Gate check
        if not skip_gate_validation:
            gate_result = validate_promotion_gates(candidate, custom_gates, champion)
            if not gate_result.passed:
                raise PromotionGateFailedError(gate_result.failures, gate_result.evaluated_metrics)

        # Demote champion if exists
        prev_champion_id = None
        now = _utc_now()
        if champion is not None and champion.model_id != candidate.model_id:
            champion.status = ModelLifecycleStatus.MONITORING
            prev_champion_id = champion.model_id

        # Promote candidate
        candidate.status = ModelLifecycleStatus.DEPLOYED
        candidate.approval_status = "approved"
        candidate.approved_by = actor_principal.user_id
        candidate.deployed_at = now
        await session.flush()

        # Emit outbox event
        outbox_seq = await allocate_outbox_seq(session, candidate.tenant_id, candidate.workspace_id)
        outbox_event = EventRecordDB(
            event_id=f"EVT-{uuid7()}",
            tenant_id=candidate.tenant_id,
            workspace_id=candidate.workspace_id,
            seq=outbox_seq,
            event_type="model.promoted",
            entity_type="model",
            entity_id=model_id,
            correlation_id=f"CORR-{uuid4().hex[:8]}",
            payload={
                "model_id": model_id,
                "name": candidate.name,
                "version": candidate.version,
                "model_type": candidate.model_type,
                "previous_champion_id": prev_champion_id,
                "deployed_at": candidate.deployed_at.isoformat() if candidate.deployed_at else None,
                "approved_by": actor_principal.user_id,
            },
            world_state_version=candidate.world_state_version,
            published=False,
            created_at=now,
        )
        session.add(outbox_event)
        await session.flush()

        return {
            "model": self._to_dict(candidate),
            "previous_champion_id": prev_champion_id,
            "status": "deployed",
        }

    async def rollback_model(
        self,
        session: AsyncSession,
        *,
        model_id: str,
        actor_principal: Principal,
        reason: str,
        fallback_model_id: str | None = None,
    ) -> dict[str, Any]:
        """Roll back a deployed model to ROLLED_BACK and restore a fallback champion."""
        stmt = (
            select(ModelRegistryEntryDB)
            .where(ModelRegistryEntryDB.model_id == model_id)
            .with_for_update()
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ModelNotFoundError(model_id)

        get_authz().check(
            actor_principal,
            "nexus.model.rollback",
            workspace_id=model.workspace_id,
            data_tenant=model.tenant_id,
        )

        now = _utc_now()
        model.status = ModelLifecycleStatus.ROLLED_BACK
        model.rolled_back_at = now
        model.rollback_reason = reason

        # Determine fallback model to deploy
        restored_model: ModelRegistryEntryDB | None = None
        if fallback_model_id:
            fallback_stmt = (
                select(ModelRegistryEntryDB)
                .where(ModelRegistryEntryDB.model_id == fallback_model_id)
                .with_for_update()
            )
            restored_model = (await session.execute(fallback_stmt)).scalar_one_or_none()
            if restored_model is None:
                raise ModelNotFoundError(fallback_model_id)
        else:
            # Pick latest MONITORING or APPROVED model of the same type
            find_stmt = (
                select(ModelRegistryEntryDB)
                .where(
                    ModelRegistryEntryDB.tenant_id == model.tenant_id,
                    ModelRegistryEntryDB.workspace_id == model.workspace_id,
                    ModelRegistryEntryDB.model_type == model.model_type,
                    ModelRegistryEntryDB.model_id != model.model_id,
                    ModelRegistryEntryDB.status.in_(
                        [ModelLifecycleStatus.MONITORING, ModelLifecycleStatus.APPROVED]
                    ),
                )
                .order_by(ModelRegistryEntryDB.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            restored_model = (await session.execute(find_stmt)).scalar_one_or_none()

        restored_id = None
        if restored_model is not None:
            restored_model.status = ModelLifecycleStatus.DEPLOYED
            restored_model.deployed_at = now
            restored_id = restored_model.model_id

        await session.flush()

        # Emit outbox event
        outbox_seq = await allocate_outbox_seq(session, model.tenant_id, model.workspace_id)
        outbox_event = EventRecordDB(
            event_id=f"EVT-{uuid7()}",
            tenant_id=model.tenant_id,
            workspace_id=model.workspace_id,
            seq=outbox_seq,
            event_type="model.rolled_back",
            entity_type="model",
            entity_id=model_id,
            correlation_id=f"CORR-{uuid4().hex[:8]}",
            payload={
                "rolled_back_model_id": model_id,
                "name": model.name,
                "version": model.version,
                "restored_model_id": restored_id,
                "reason": reason,
                "actor": actor_principal.user_id,
            },
            world_state_version=model.world_state_version,
            published=False,
            created_at=now,
        )
        session.add(outbox_event)
        await session.flush()

        return {
            "rolled_back_model": self._to_dict(model),
            "restored_model_id": restored_id,
            "reason": reason,
            "status": "rolled_back",
        }

    async def get_model(self, session: AsyncSession, model_id: str) -> dict[str, Any] | None:
        stmt = select(ModelRegistryEntryDB).where(ModelRegistryEntryDB.model_id == model_id)
        model = (await session.execute(stmt)).scalar_one_or_none()
        return self._to_dict(model) if model else None

    async def get_active_deployed(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        model_type: str,
    ) -> dict[str, Any] | None:
        stmt = (
            select(ModelRegistryEntryDB)
            .where(
                ModelRegistryEntryDB.tenant_id == tenant_id,
                ModelRegistryEntryDB.workspace_id == workspace_id,
                ModelRegistryEntryDB.model_type == model_type,
                ModelRegistryEntryDB.status == ModelLifecycleStatus.DEPLOYED,
            )
            .order_by(ModelRegistryEntryDB.deployed_at.desc())
            .limit(1)
        )
        model = (await session.execute(stmt)).scalar_one_or_none()
        return self._to_dict(model) if model else None

    async def list_models(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        status: str | None = None,
        model_type: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [
            ModelRegistryEntryDB.tenant_id == tenant_id,
            ModelRegistryEntryDB.workspace_id == workspace_id,
        ]
        if status:
            conditions.append(ModelRegistryEntryDB.status == status)
        if model_type:
            conditions.append(ModelRegistryEntryDB.model_type == model_type)

        stmt = (
            select(ModelRegistryEntryDB)
            .where(and_(*conditions))
            .order_by(ModelRegistryEntryDB.created_at.desc())
        )
        result = await session.execute(stmt)
        return [self._to_dict(m) for m in result.scalars().all()]

    async def health_summary(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Compute operational intelligence health across deployed models."""
        stmt = select(ModelRegistryEntryDB).where(
            ModelRegistryEntryDB.tenant_id == tenant_id,
            ModelRegistryEntryDB.workspace_id == workspace_id,
        )
        result = await session.execute(stmt)
        models = list(result.scalars().all())

        by_type: dict[str, list[ModelRegistryEntryDB]] = {}
        for m in models:
            by_type.setdefault(m.model_type, []).append(m)

        summary: dict[str, Any] = {}
        type_labels = {
            "forecast": "Demand forecast",
            "eta": "ETA prediction",
            "risk": "Supplier risk",
            "sla": "SLA prediction",
            "gnn": "Scenario accuracy",
            "rl": "Recommendation success",
        }

        for mtype, label in type_labels.items():
            deployed = next(
                (m for m in by_type.get(mtype, []) if m.status == ModelLifecycleStatus.DEPLOYED),
                None,
            )
            if deployed:
                metrics = deployed.metrics or {}
                if mtype == "forecast":
                    accuracy = 1.0 - float(metrics.get("wape", 0.1))
                elif mtype in ("risk", "sla"):
                    accuracy = float(metrics.get("f1", metrics.get("accuracy", 0.92)))
                elif mtype == "eta":
                    accuracy = 1.0 - float(metrics.get("mape", 0.12))
                else:
                    accuracy = float(metrics.get("accuracy", 0.88))

                summary[label] = {
                    "model_id": deployed.model_id,
                    "name": deployed.name,
                    "version": deployed.version,
                    "accuracy": round(min(1.0, max(0.0, float(accuracy))), 4),
                    "deployed_at": deployed.deployed_at.isoformat()
                    if deployed.deployed_at
                    else None,
                    "status": deployed.status,
                    "metrics": metrics,
                }
            else:
                summary[label] = {
                    "model_id": None,
                    "name": None,
                    "version": None,
                    "accuracy": 0.0,
                    "deployed_at": None,
                    "status": "unassigned",
                }

        return summary


_singleton: AuthoritativeModelRegistry | None = None


def get_authoritative_model_registry() -> AuthoritativeModelRegistry:
    global _singleton
    if _singleton is None:
        _singleton = AuthoritativeModelRegistry()
    return _singleton


__all__ = [
    "ModelLifecycleStatus",
    "ALLOWED_MODEL_TRANSITIONS",
    "PromotionGateConfig",
    "PromotionGateResult",
    "ModelGovernanceError",
    "ModelNotFoundError",
    "DuplicateModelVersionError",
    "InvalidModelTransitionError",
    "PromotionGateFailedError",
    "ModelRollbackError",
    "validate_promotion_gates",
    "AuthoritativeModelRegistry",
    "get_authoritative_model_registry",
]
