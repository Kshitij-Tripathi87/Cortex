"""Nexus v1.0 P0 — Authoritative Decision Memory.

PostgreSQL-backed Decision Memory with similarity-based retrieval.
Replaces the in-memory DecisionMemory singleton for production.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.persistence.models import DecisionRecordDB


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if t}


@dataclass
class CachedMemoryQuery:
    results: list[dict[str, Any]]
    cached_at: float = field(default_factory=time.time)


CACHE_TTL = 30


class AuthoritativeDecisionMemory:
    """DB-backed decision memory with append-only record semantics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._recent_cache: dict[str, CachedMemoryQuery] = {}

    async def record(
        self,
        session: AsyncSession,
        *,
        decision_id: str,
        tenant_id: str,
        workspace_id: str,
        situation: str,
        evidence_ids: list[str],
        world_state_version: int,
        options: list[dict[str, Any]],
        recommended_option_id: str,
        chosen_option_id: str,
        policy_id: str,
        approval_id: str | None = None,
        executed_at: datetime | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record a completed decision (or update outcome on existing)."""
        existing = await session.execute(
            select(DecisionRecordDB).where(DecisionRecordDB.decision_id == decision_id)
        )
        rec = existing.scalar_one_or_none()
        if rec is not None:
            # Update metadata on existing
            rec.situation = situation
            rec.outcome_status = rec.outcome_status or "pending"
            await session.flush()
            self._invalidate_workspace(tenant_id, workspace_id)
            return self._rec_to_memory_dict(rec)

        # Create memory entry — expects the decision row to already exist via
        # AuthoritativeDecisionService.create(). If it doesn't, we create a
        # minimal record in OUTCOME_RECORDED state for memory-only entries.
        import hashlib as _hl

        _hash_input = f"{decision_id}|{world_state_version}|{chosen_option_id}|{policy_id}"
        _hash = _hl.sha256(_hash_input.encode()).hexdigest()[:16]
        rec = DecisionRecordDB(
            decision_id=decision_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            phase="outcome_recorded",
            world_state_version=world_state_version,
            world_state_hash=_hash,
            proposal_id=decision_id,
            options=options,
            chosen_option=chosen_option_id,
            situation=situation,
            recommended_option_id=recommended_option_id,
            policy_id=policy_id,
            approval_id=approval_id,
            deterministic_hash=_hash,
            outcome_status="pending",
            tags=tags or [],
        )
        session.add(rec)
        await session.flush()
        self._invalidate_workspace(tenant_id, workspace_id)
        return self._rec_to_memory_dict(rec)

    async def update_outcome(
        self,
        session: AsyncSession,
        decision_id: str,
        *,
        outcome_status: str | None = None,
        financial_impact: float | None = None,
        actual_result: str | None = None,
        human_feedback: str | None = None,
        actual_nev: float | None = None,
        actual_sla: float | None = None,
        actual_cost: float | None = None,
    ) -> dict[str, Any] | None:
        result = await session.execute(
            select(DecisionRecordDB).where(DecisionRecordDB.decision_id == decision_id)
        )
        rec = result.scalar_one_or_none()
        if rec is None:
            return None
        if outcome_status is not None:
            rec.outcome_status = outcome_status
        if financial_impact is not None:
            rec.financial_impact = financial_impact
        if actual_result is not None:
            rec.actual_result_text = actual_result
        if human_feedback is not None:
            rec.human_feedback = human_feedback
        if actual_nev is not None:
            rec.actual_nev = actual_nev
        if actual_sla is not None:
            rec.actual_sla = actual_sla
        if actual_cost is not None:
            rec.actual_cost = actual_cost
        rec.updated_at = _utc_now()
        await session.flush()
        self._invalidate_workspace(rec.tenant_id, rec.workspace_id)
        return self._rec_to_memory_dict(rec)

    async def find_analogous(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        situation: str,
        limit: int = 5,
        min_similarity: float = 0.1,
    ) -> list[dict[str, Any]]:
        needles = _tokenize(situation)
        if not needles:
            return []
        # Pull candidates from DB (completed decisions only)
        result = await session.execute(
            select(DecisionRecordDB)
            .where(
                DecisionRecordDB.tenant_id == tenant_id,
                DecisionRecordDB.workspace_id == workspace_id,
                DecisionRecordDB.phase == "outcome_recorded",
            )
            .order_by(DecisionRecordDB.updated_at.desc())
            .limit(500)
        )
        recs = result.scalars().all()
        scored = []
        for rec in recs:
            haystack_text = (rec.situation or "") + " " + " ".join(rec.tags or [])
            haystack = _tokenize(haystack_text)
            if not haystack:
                continue
            intersection = needles & haystack
            union = needles | haystack
            if not union:
                continue
            sim = len(intersection) / len(union)
            if sim < min_similarity:
                continue
            outcome_summary = self._outcome_summary(rec)
            scored.append(
                {
                    "decision": self._rec_to_memory_dict(rec),
                    "similarity": round(sim, 4),
                    "outcome_summary": outcome_summary,
                }
            )
        scored.sort(key=lambda x: cast(float, x["similarity"]), reverse=True)
        return scored[:limit]

    async def recent(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        limit: int = 20,
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
        return [self._rec_to_memory_dict(r) for r in result.scalars().all()]

    def _invalidate_workspace(self, tenant_id: str, workspace_id: str) -> None:
        with self._lock:
            key = f"{tenant_id}:{workspace_id}"
            self._recent_cache.pop(key, None)

    @staticmethod
    def _outcome_summary(rec: DecisionRecordDB) -> str:
        parts = [f"Chose {rec.chosen_option or 'unknown'}"]
        parts.append(f"Outcome: {rec.outcome_status or 'pending'}")
        if rec.financial_impact is not None:
            parts.append(f"Financial: {rec.financial_impact:+.2f}")
        if rec.actual_result_text:
            parts.append(rec.actual_result_text[:80])
        return "; ".join(parts)

    @staticmethod
    def _rec_to_memory_dict(rec: DecisionRecordDB) -> dict[str, Any]:
        return {
            "decision_id": rec.decision_id,
            "tenant_id": rec.tenant_id,
            "workspace_id": rec.workspace_id,
            "situation": rec.situation,
            "evidence_ids": [],  # Populated from evidence nodes when needed
            "world_state_version": rec.world_state_version,
            "options": rec.options or [],
            "recommended_option_id": rec.recommended_option_id,
            "chosen_option_id": rec.chosen_option,
            "policy_id": rec.policy_id,
            "approval_id": rec.approval_id,
            "executed_at": rec.created_at.isoformat() if rec.created_at else None,
            "outcome_status": rec.outcome_status,
            "financial_impact": rec.financial_impact,
            "actual_result": rec.actual_result_text,
            "tags": rec.tags or [],
        }


_singleton: AuthoritativeDecisionMemory | None = None


def get_authoritative_decision_memory() -> AuthoritativeDecisionMemory:
    global _singleton
    if _singleton is None:
        _singleton = AuthoritativeDecisionMemory()
    return _singleton
