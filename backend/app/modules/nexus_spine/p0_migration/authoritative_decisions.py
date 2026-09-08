"""Nexus v1.0 P0 — Authoritative Decision Service.

Replaces the in-memory `DecisionLifecycleManager` singleton with a
PostgreSQL-backed service that satisfies the scaling invariant:

    A process restart, worker replacement, or horizontal scale-out
    must not change operational truth.

Write path (all mutating operations):
    1. Open transaction
    2. SELECT ... FOR UPDATE the decision row (pessimistic lock)
    3. Validate the transition against ALLOWED_TRANSITIONS
    4. Verify world_state_version/hash (optimistic concurrency)
    5. Update phase, recompute deterministic hash
    6. INSERT an append-only DecisionTransitionDB record
    7. INSERT an outbox event record
    8. COMMIT
    9. Invalidate local cache key; publish to Redis for peer invalidation

Read path:
    1. Check in-memory projection cache (lock-free read)
    2. On miss, SELECT from PostgreSQL
    3. Populate cache
    4. Return domain object

The API layer stays stateless — any worker can serve any request.
Cache incoherence from multi-worker writes is bounded by:
    - Outbox events published in the same transaction
    - Redis Pub/Sub peer invalidation on commit
    - TTL (30s) as a safety net for missed invalidations
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.governance.lifecycle import (
    ALLOWED_TRANSITIONS,
    DecisionPhase,
)
from app.modules.nexus_spine.persistence.models import (
    DecisionRecordDB,
    DecisionTransitionDB,
    EventRecordDB,
)
from app.modules.nexus_spine.realtime_events import NexusEventType


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _compute_hash(
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


CACHE_TTL_SECONDS = 30


@dataclass
class CachedDecision:
    decision: dict[str, Any]
    transitions: list[dict[str, Any]]
    cached_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return (time.time() - self.cached_at) > CACHE_TTL_SECONDS


class StaleWorldStateError(Exception):
    """Raised when a decision's captured world state no longer matches current."""


class InvalidTransitionError(Exception):
    """Raised when a state-machine transition is not allowed."""


class AuthoritativeDecisionService:
    """PostgreSQL-backed decision lifecycle with in-memory projection cache.

    Safe to instantiate once per process (singleton). Cache is
    per-process; peer workers invalidate each other over Redis.
    """

    def __init__(self) -> None:
        self._cache: dict[str, CachedDecision] = {}
        self._lock = threading.RLock()

    # ── Read path ──────────────────────────────────────────────────────

    async def get(self, session: AsyncSession, decision_id: str) -> dict[str, Any] | None:
        """Get a decision by ID. Uses cache if fresh, falls back to DB."""
        with self._lock:
            cached = self._cache.get(decision_id)
            if cached and not cached.expired:
                return cached.decision

        # DB lookup
        result = await session.execute(
            select(DecisionRecordDB).where(DecisionRecordDB.decision_id == decision_id)
        )
        rec = result.scalar_one_or_none()
        if rec is None:
            return None
        transitions_result = await session.execute(
            select(DecisionTransitionDB)
            .where(DecisionTransitionDB.decision_id == decision_id)
            .order_by(DecisionTransitionDB.timestamp)
        )
        transitions = [
            {
                "transition_id": t.transition_id,
                "from_phase": t.from_phase,
                "to_phase": t.to_phase,
                "actor": t.actor,
                "reason": t.reason,
                "metadata": t.metadata_,
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            }
            for t in transitions_result.scalars().all()
        ]
        decision_dict = self._rec_to_dict(rec)
        decision_dict["transitions"] = transitions

        with self._lock:
            self._cache[decision_id] = CachedDecision(
                decision=decision_dict, transitions=transitions
            )
        return decision_dict

    async def list_by_phase(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        phase: str,
    ) -> list[dict[str, Any]]:
        result = await session.execute(
            select(DecisionRecordDB)
            .where(
                DecisionRecordDB.tenant_id == tenant_id,
                DecisionRecordDB.workspace_id == workspace_id,
                DecisionRecordDB.phase == phase,
            )
            .order_by(DecisionRecordDB.created_at.desc())
        )
        recs = result.scalars().all()
        return [self._rec_to_dict(r) for r in recs]

    async def list_by_workspace(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        result = await session.execute(
            select(DecisionRecordDB)
            .where(
                DecisionRecordDB.tenant_id == tenant_id,
                DecisionRecordDB.workspace_id == workspace_id,
            )
            .order_by(DecisionRecordDB.created_at.desc())
            .limit(limit)
        )
        return [self._rec_to_dict(r) for r in result.scalars().all()]

    # ── Write path ─────────────────────────────────────────────────────

    async def create(
        self,
        session: AsyncSession,
        *,
        decision_id: str,
        tenant_id: str,
        workspace_id: str,
        proposal_id: str,
        world_state_version: int,
        world_state_hash: str,
        options: list[dict[str, Any]] | None = None,
        chosen_option: str | None = None,
        situation: str | None = None,
        recommended_option_id: str | None = None,
        policy_id: str | None = None,
        recommended_nev: float | None = None,
        recommended_sla: float | None = None,
        recommended_cost: float | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        """Create a new decision in PROPOSED phase. Transactional."""
        opts = list(options or [])
        det_hash = _compute_hash(
            decision_id=decision_id,
            options=opts,
            world_state_version=world_state_version,
            world_state_hash=world_state_hash,
            phase=DecisionPhase.PROPOSED.value,
            proposal_id=proposal_id,
            chosen_option=chosen_option,
        )
        rec = DecisionRecordDB(
            decision_id=decision_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            phase=DecisionPhase.PROPOSED.value,
            world_state_version=world_state_version,
            world_state_hash=world_state_hash,
            proposal_id=proposal_id,
            options=opts,
            chosen_option=chosen_option,
            situation=situation,
            recommended_option_id=recommended_option_id,
            policy_id=policy_id,
            recommended_nev=recommended_nev,
            recommended_sla=recommended_sla,
            recommended_cost=recommended_cost,
            confidence=confidence,
            deterministic_hash=det_hash,
        )
        session.add(rec)
        # Record initial transition
        session.add(
            DecisionTransitionDB(
                decision_id=decision_id,
                from_phase="",
                to_phase=DecisionPhase.PROPOSED.value,
                actor="system",
                reason="decision_created",
            )
        )
        # Outbox event
        session.add(
            EventRecordDB(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                event_type=NexusEventType.DECISION_CREATED.value,
                entity_type="decision",
                entity_id=decision_id,
                payload={"phase": DecisionPhase.PROPOSED.value},
                world_state_version=world_state_version,
            )
        )
        await session.flush()
        result = self._rec_to_dict(rec)
        with self._lock:
            self._cache[decision_id] = CachedDecision(decision=result, transitions=[])
        return result

    async def advance(
        self,
        session: AsyncSession,
        decision_id: str,
        target_phase: DecisionPhase,
        *,
        actor: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        current_world_state_version: int | None = None,
        current_world_state_hash: str | None = None,
    ) -> dict[str, Any]:
        """Advance a decision through its lifecycle.

        This is the ONLY valid way to change a decision's phase.
        Validates:
          - Transition is in ALLOWED_TRANSITIONS
          - If staleness check provided, world state hasn't drifted
          - Record is SELECTed FOR UPDATE (implicit via flush ordering)
        """
        # Load with row lock (FOR UPDATE)
        # SQLAlchemy's with_for_update() on the select
        stmt = (
            select(DecisionRecordDB)
            .where(DecisionRecordDB.decision_id == decision_id)
            .with_for_update()
        )
        result = await session.execute(stmt)
        rec = result.scalar_one_or_none()
        if rec is None:
            raise ValueError(f"Decision {decision_id} not found")

        current_phase = DecisionPhase(rec.phase)
        if target_phase not in ALLOWED_TRANSITIONS.get(current_phase, set()):
            raise InvalidTransitionError(
                f"Invalid transition: {current_phase.value} → {target_phase.value}. "
                f"Allowed: {sorted(t.value for t in ALLOWED_TRANSITIONS[current_phase])}"
            )

        # Staleness check — optional but must pass when provided
        if (
            current_world_state_version is not None
            and current_world_state_hash is not None
            and target_phase
            in {DecisionPhase.APPROVED, DecisionPhase.AUTHORIZED, DecisionPhase.EXECUTING}
            and (
                rec.world_state_version != current_world_state_version
                or rec.world_state_hash != current_world_state_hash
            )
        ):
            # Auto-mark stale
            rec.phase = DecisionPhase.STALE.value
            session.add(
                DecisionTransitionDB(
                    decision_id=decision_id,
                    from_phase=current_phase.value,
                    to_phase=DecisionPhase.STALE.value,
                    actor="system",
                    reason="world_state_drift_detected_on_advance",
                )
            )
            session.add(
                EventRecordDB(
                    tenant_id=rec.tenant_id,
                    workspace_id=rec.workspace_id,
                    event_type=NexusEventType.DECISION_INVALIDATED.value,
                    entity_type="decision",
                    entity_id=decision_id,
                    payload={"reason": "world_state_drift"},
                    world_state_version=current_world_state_version,
                )
            )
            await session.flush()
            self._invalidate_cache(decision_id)
            raise StaleWorldStateError(
                f"Decision {decision_id} is stale "
                f"(ws_v{rec.world_state_version} vs current v{current_world_state_version})"
            )

        # Apply transition
        rec.phase = target_phase.value
        rec.updated_at = _utc_now()
        opts: list[dict[str, Any]] = rec.options if isinstance(rec.options, list) else []
        rec.deterministic_hash = _compute_hash(
            decision_id=decision_id,
            options=opts,
            world_state_version=rec.world_state_version,
            world_state_hash=rec.world_state_hash,
            phase=target_phase.value,
            proposal_id=rec.proposal_id,
            chosen_option=rec.chosen_option,
        )
        session.add(
            DecisionTransitionDB(
                decision_id=decision_id,
                from_phase=current_phase.value,
                to_phase=target_phase.value,
                actor=actor,
                reason=reason,
                metadata_=metadata or {},
            )
        )

        # Publish corresponding event
        event_type = self._phase_event_type(target_phase)
        if event_type:
            session.add(
                EventRecordDB(
                    tenant_id=rec.tenant_id,
                    workspace_id=rec.workspace_id,
                    event_type=event_type,
                    entity_type="decision",
                    entity_id=decision_id,
                    payload={
                        "from_phase": current_phase.value,
                        "to_phase": target_phase.value,
                        "actor": actor,
                    },
                    world_state_version=rec.world_state_version,
                )
            )

        await session.flush()
        result_dict = self._rec_to_dict(rec)
        self._invalidate_cache(decision_id)
        return result_dict

    async def record_outcome(
        self,
        session: AsyncSession,
        decision_id: str,
        *,
        actor: str,
        outcome_payload: dict[str, Any],
        actual_nev: float | None = None,
        actual_sla: float | None = None,
        actual_cost: float | None = None,
        outcome_status: str = "succeeded",
        financial_impact: float | None = None,
        actual_result_text: str | None = None,
    ) -> dict[str, Any]:
        """Record an outcome and transition to OUTCOME_RECORDED (terminal)."""
        stmt = (
            select(DecisionRecordDB)
            .where(DecisionRecordDB.decision_id == decision_id)
            .with_for_update()
        )
        result = await session.execute(stmt)
        rec = result.scalar_one_or_none()
        if rec is None:
            raise ValueError(f"Decision {decision_id} not found")

        # Must be EXECUTED to record outcome (EXECUTING allowed as graceful fallback)
        if rec.phase != DecisionPhase.EXECUTED.value and rec.phase != DecisionPhase.EXECUTING.value:
            raise InvalidTransitionError(
                f"Cannot record outcome in phase {rec.phase}; must be EXECUTED"
            )

        rec.outcome_payload = outcome_payload
        rec.actual_nev = actual_nev
        rec.actual_sla = actual_sla
        rec.actual_cost = actual_cost
        rec.outcome_status = outcome_status
        rec.financial_impact = financial_impact
        rec.actual_result_text = actual_result_text

        # Transition EXECUTED → OUTCOME_RECORDED
        current_phase = DecisionPhase(rec.phase)
        target = DecisionPhase.OUTCOME_RECORDED
        rec.phase = target.value
        rec.updated_at = _utc_now()
        opts2: list[dict[str, Any]] = rec.options if isinstance(rec.options, list) else []
        rec.deterministic_hash = _compute_hash(
            decision_id=decision_id,
            options=opts2,
            world_state_version=rec.world_state_version,
            world_state_hash=rec.world_state_hash,
            phase=target.value,
            proposal_id=rec.proposal_id,
            chosen_option=rec.chosen_option,
        )
        session.add(
            DecisionTransitionDB(
                decision_id=decision_id,
                from_phase=current_phase.value,
                to_phase=target.value,
                actor=actor,
                reason="outcome_recorded",
            )
        )
        session.add(
            EventRecordDB(
                tenant_id=rec.tenant_id,
                workspace_id=rec.workspace_id,
                event_type=NexusEventType.OUTCOME_RECORDED.value,
                entity_type="decision",
                entity_id=decision_id,
                payload={"outcome_status": outcome_status},
                world_state_version=rec.world_state_version,
            )
        )
        await session.flush()
        self._invalidate_cache(decision_id)
        return self._rec_to_dict(rec)

    # ── Cache invalidation ────────────────────────────────────────────

    def _invalidate_cache(self, decision_id: str) -> None:
        with self._lock:
            self._cache.pop(decision_id, None)

    def invalidate_all(self) -> None:
        """Called when we receive a Redis invalidation from a peer worker."""
        with self._lock:
            self._cache.clear()

    # ── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _phase_event_type(phase: DecisionPhase) -> str | None:
        mapping = {
            DecisionPhase.SIMULATED: None,
            DecisionPhase.POLICY_CHECKED: None,
            DecisionPhase.AWAITING_APPROVAL: None,
            DecisionPhase.APPROVED: NexusEventType.APPROVAL_GRANTED.value,
            DecisionPhase.REJECTED: NexusEventType.APPROVAL_REJECTED.value,
            DecisionPhase.AUTHORIZED: None,
            DecisionPhase.EXECUTING: NexusEventType.EXECUTION_STARTED.value,
            DecisionPhase.EXECUTED: NexusEventType.EXECUTION_COMPLETED.value,
            DecisionPhase.OUTCOME_RECORDED: NexusEventType.OUTCOME_RECORDED.value,
            DecisionPhase.STALE: NexusEventType.DECISION_INVALIDATED.value,
            DecisionPhase.INVALIDATED: NexusEventType.DECISION_INVALIDATED.value,
            DecisionPhase.EXECUTION_FAILED: NexusEventType.EXECUTION_FAILED.value,
        }
        return mapping.get(phase)

    @staticmethod
    def _rec_to_dict(rec: DecisionRecordDB) -> dict[str, Any]:
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
            "situation": rec.situation,
            "recommended_option_id": rec.recommended_option_id,
            "policy_id": rec.policy_id,
            "recommended_nev": rec.recommended_nev,
            "recommended_sla": rec.recommended_sla,
            "recommended_cost": rec.recommended_cost,
            "confidence": rec.confidence,
            "actual_nev": rec.actual_nev,
            "actual_sla": rec.actual_sla,
            "actual_cost": rec.actual_cost,
            "outcome_status": rec.outcome_status,
            "financial_impact": rec.financial_impact,
            "actual_result_text": rec.actual_result_text,
            "tags": rec.tags or [],
            "deterministic_hash": rec.deterministic_hash,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        }


# ── Singleton ────────────────────────────────────────────────────────────

_singleton: AuthoritativeDecisionService | None = None


def get_authoritative_decision_service() -> AuthoritativeDecisionService:
    global _singleton
    if _singleton is None:
        _singleton = AuthoritativeDecisionService()
    return _singleton
