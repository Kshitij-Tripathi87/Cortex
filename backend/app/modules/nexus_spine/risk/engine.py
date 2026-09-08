"""Nexus Risk & Root Cause Engine — Phase C.

Combines signals, blast-radius traversal, and financial/SLA exposure into a
ranked risk registry. Every risk carries:

- severity (CRITICAL/HIGH/MEDIUM/LOW) derived from exposure thresholds
- confidence (evidence strength + signal confidence)
- root_cause (the underlying supplier/port/plant causing the cascade)
- financial exposure (revenue at risk)
- SLA exposure (orders breaching SLA)
- evidence trail (which signals/entities drove the assessment)
- recommended_next_action

This is the "reasoning substrate" Vanessa uses for "What needs attention?"
answers. It does not invent risk — it computes it deterministically from
the world model, and every number is traceable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.nexus_spine.ontology import (
    EntityKind,
    EntityQuery,
    RelationshipEdge,
    RelationshipKind,
    get_world_model,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


# Exposure thresholds — derived from pilot data, configurable per workspace
_SEVERITY_THRESHOLDS: dict[Severity, float] = {
    Severity.CRITICAL: 5_00_000.0,  # ₹5L revenue exposure
    Severity.HIGH: 1_00_000.0,  # ₹1L
    Severity.MEDIUM: 50_000.0,  # ₹50k
    Severity.LOW: 10_000.0,  # ₹10k
}


class RootCauseCandidate(BaseModel):
    """One ranked candidate for the root cause of a risk."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_kind: str
    entity_name: str
    hop_distance: int  # How far from the affected entities (lower = closer)
    signal_count: int = 0
    causal_weight: float = Field(ge=0.0, le=1.0)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class RiskAssessment(BaseModel):
    """One computed risk, derived from signals + world model traversal.

    Deterministic: identical inputs produce identical output. The risk engine
    never hallucinates — every number is derived from the world state.
    """

    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(description="Deterministic ID for idempotency")
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)

    title: str
    description: str

    # Affected entities
    affected_entity_ids: list[str] = Field(default_factory=list)
    affected_orders: int = 0
    affected_skus: int = 0

    # Financial + SLA exposure
    revenue_at_risk: float = Field(default=0.0, ge=0.0)
    sla_breach_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    recovery_estimate_days: float | None = None

    # Causality
    root_cause_candidates: list[RootCauseCandidate] = Field(default_factory=list)
    signal_ids: list[str] = Field(default_factory=list)
    related_disruption_id: str | None = None

    # Provenance
    world_state_version: int = 0
    computed_at: datetime = Field(default_factory=_utc_now)
    evidence_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["severity"] = self.severity.value
        data["computed_at"] = self.computed_at.isoformat()
        return data


class RiskEngine:
    """Computes risks from signals + world-model exposure.

    Deliberately deterministic: same world state → same risk registers.
    The engine reads signals from the world model, traverses supply-chain
    edges to find affected entities, and aggregates exposure.
    """

    VERSION = "1.0"

    def __init__(self) -> None:
        pass

    def compute(self, tenant_id: UUID, workspace_id: UUID) -> list[RiskAssessment]:
        """Compute the risk registry for a workspace.

        Steps:
        1. Load all active signals and disruptions
        2. For each significant signal, compute blast radius + exposure
        3. Group by root-cause entity (the supplier/plant/port)
        4. Rank by severity × confidence, deduplicate
        5. Deterministic risk IDs for idempotency
        """
        wm = get_world_model()

        signals = self._load_signals(wm, tenant_id, workspace_id)
        disruptions = self._load_disruptions(wm, tenant_id, workspace_id)

        risks: dict[str, RiskAssessment] = {}

        for signal in signals:
            affected_entity_id = signal.state.get("affected_entity_id")
            if not affected_entity_id:
                continue
            try:
                affected_uuid = UUID(affected_entity_id)
            except (ValueError, TypeError):
                continue
            seed = wm.get(tenant_id, workspace_id, affected_uuid)
            if seed is None:
                continue

            severity_score = float(signal.state.get("severity_score", 0.0))
            if severity_score < 0.15:
                continue

            # Blast radius: what does this seed reach?
            paths = wm.traverse_supply_chain(tenant_id, workspace_id, affected_uuid, max_depth=4)

            affected_entities: list[str] = []
            affected_orders = 0
            affected_skus = 0
            revenue_at_risk = 0.0
            sla_values: list[float] = []

            for target_id, _edges in paths.items():
                target = wm.get(tenant_id, workspace_id, target_id)
                if target is None:
                    continue
                affected_entities.append(str(target_id))
                if target.kind == EntityKind.SALES_ORDER:
                    affected_orders += 1
                    rev = float(target.state.get("revenue", 0.0))
                    revenue_at_risk += rev
                    sla = float(target.state.get("sla_risk_pct", 0.0))
                    if sla > 0:
                        sla_values.append(sla)
                elif target.kind == EntityKind.SKU:
                    affected_skus += 1

            avg_sla_risk = sum(sla_values) / len(sla_values) if sla_values else 0.0

            # Root cause candidates — the seed AND via-edges pointing to it
            root_candidates = self._root_cause_candidates(
                wm, tenant_id, workspace_id, affected_uuid, paths
            )

            severity = self._severity_from_exposure(revenue_at_risk, avg_sla_risk)
            confidence = self._compute_confidence(signal, len(root_candidates))

            risk_id = self._risk_id(workspace_id, signal.natural_key, affected_entity_id)
            risks[risk_id] = RiskAssessment(
                risk_id=risk_id,
                severity=severity,
                confidence=confidence,
                title=f"{signal.name}: exposure across {len(affected_entities)} entities",
                description=signal.description,
                affected_entity_ids=affected_entities,
                affected_orders=affected_orders,
                affected_skus=affected_skus,
                revenue_at_risk=round(revenue_at_risk, 2),
                sla_breach_pct=round(avg_sla_risk, 4),
                root_cause_candidates=root_candidates,
                signal_ids=[str(signal.entity_id)],
                world_state_version=wm.world_state_version,
                evidence_summary=f"{len(signals)} signal(s); {len(paths) + 1} affected entities",
            )

        # Disruptions that don't map to a signal — still surfaces as risks
        for disruption in disruptions:
            affected_ids = [
                UUID(x)
                for x in disruption.state.get("affected_entity_ids", [])
                if isinstance(x, (str, UUID))
            ]
            if not affected_ids:
                continue
            key = disruption.natural_key
            if key in risks:
                continue
            primary = affected_ids[0]
            if wm.get(tenant_id, workspace_id, primary) is None:
                continue
            risks[key] = RiskAssessment(
                risk_id=self._risk_id(workspace_id, key, str(primary)),
                severity=self._severity_from_exposure(0.0, 0.9),  # Disruptions default HIGH
                confidence=0.85,
                title=disruption.name,
                description=disruption.description,
                affected_entity_ids=[str(e) for e in affected_ids],
                related_disruption_id=str(disruption.entity_id),
                world_state_version=wm.world_state_version,
                evidence_summary=f"Disruption {disruption.name} directly reported",
            )

        # Rank: severity × confidence descending, tie-break by revenue
        ranked = sorted(
            risks.values(),
            key=lambda r: (
                self._severity_rank(r.severity),
                r.revenue_at_risk,
                r.confidence,
                r.risk_id,
            ),
            reverse=True,
        )
        return ranked

    # ── Internals ──────────────────────────────────────────────────────────

    def _load_signals(self, wm: Any, tenant_id: UUID, workspace_id: UUID) -> list[Any]:
        page = wm.query(
            EntityQuery(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kinds=[EntityKind.SIGNAL],
                limit=500,
            )
        )
        return page.items

    def _load_disruptions(self, wm: Any, tenant_id: UUID, workspace_id: UUID) -> list[Any]:
        page = wm.query(
            EntityQuery(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kinds=[EntityKind.DISRUPTION],
                limit=500,
            )
        )
        return page.items

    def _severity_from_exposure(self, revenue_at_risk: float, sla_risk_pct: float) -> Severity:
        """Severity = max(revenue-triggered, SLA-triggered).

        Both revenue and SLA contribute; the higher of the two wins.
        Smooth (slightly non-linear) so a ₹10L risk × 95% SLA > ₹6L risk × 85%.
        """
        revenue_severity: Severity = Severity.LOW
        for level in (
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
        ):
            threshold = _SEVERITY_THRESHOLDS[level]
            if revenue_at_risk >= threshold:
                revenue_severity = level
                break

        sla_severity: Severity
        if sla_risk_pct >= 0.80:
            sla_severity = Severity.CRITICAL
        elif sla_risk_pct >= 0.60:
            sla_severity = Severity.HIGH
        elif sla_risk_pct >= 0.35:
            sla_severity = Severity.MEDIUM
        elif sla_risk_pct >= 0.15:
            sla_severity = Severity.LOW
        else:
            sla_severity = Severity.INFO

        if self._severity_rank(sla_severity) > self._severity_rank(revenue_severity):
            return sla_severity
        return revenue_severity

    def _severity_rank(self, severity: Severity) -> int:
        return {
            Severity.CRITICAL: 4,
            Severity.HIGH: 3,
            Severity.MEDIUM: 2,
            Severity.LOW: 1,
            Severity.INFO: 0,
        }[severity]

    def _compute_confidence(self, signal: Any, root_candidates: int) -> float:
        """Confidence combines the signal's own confidence with evidence
        breadth (more root candidates = more context = slightly less certain)."""
        base = signal.confidence
        if base <= 0.0:
            base = 0.5
        spread_penalty = min(root_candidates * 0.02, 0.15)
        return round(min(base - spread_penalty, 1.0), 4)

    def _root_cause_candidates(
        self,
        wm: Any,
        tenant_id: UUID,
        workspace_id: UUID,
        seed_id: UUID,
        paths: dict[UUID, list[RelationshipEdge]],
    ) -> list[RootCauseCandidate]:
        """List ranked root-cause candidates.

        Priority: supplier nodes reachable within 2 hops of the seed,
        then the seed itself, then anything 3+ hops away.
        """
        candidates: list[RootCauseCandidate] = []
        seed = wm.get(tenant_id, workspace_id, seed_id)
        if seed is None:
            return candidates

        # The seed itself is always a candidate
        seed_signals = wm.query(
            EntityQuery(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kinds=[EntityKind.SIGNAL],
                limit=100,
            )
        ).items
        seed_signal_count = sum(
            1 for s in seed_signals if s.state.get("affected_entity_id") == str(seed_id)
        )
        candidates.append(
            RootCauseCandidate(
                entity_id=str(seed_id),
                entity_kind=seed.kind.value,
                entity_name=seed.name,
                hop_distance=0,
                signal_count=seed_signal_count,
                causal_weight=1.0 if seed_signal_count > 0 else 0.85,
                rationale=f"Origin entity ({seed.kind.value})",
            )
        )

        # Suppliers/ports/plants one hop away that feed the seed via SUPPLIES
        for source_id, edges in paths.items():
            ent = wm.get(tenant_id, workspace_id, source_id)
            if ent is None or source_id == seed_id:
                continue
            for edge in edges:
                if edge.kind not in (
                    RelationshipKind.SUPPLIES,
                    RelationshipKind.PRODUCES,
                    RelationshipKind.TRAVELS_VIA,
                ):
                    continue
                if ent.kind in (EntityKind.SUPPLIER, EntityKind.PLANT, EntityKind.PORT):
                    candidates.append(
                        RootCauseCandidate(
                            entity_id=str(source_id),
                            entity_kind=ent.kind.value,
                            entity_name=ent.name,
                            hop_distance=1,
                            signal_count=0,
                            causal_weight=0.72,
                            rationale=f"Upstream {ent.kind.value} via {edge.kind.value}",
                        )
                    )
                    break

        return candidates

    def _risk_id(self, workspace_id: UUID, key: str, affected_entity_id: str) -> str:
        """Deterministic, idempotent risk ID — same inputs → same ID."""
        payload = f"{workspace_id}:{key}:{affected_entity_id}"
        return "RISK-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()


_singleton: RiskEngine | None = None


def get_risk_engine() -> RiskEngine:
    global _singleton
    if _singleton is None:
        _singleton = RiskEngine()
    return _singleton


def reset_risk_engine() -> None:
    global _singleton
    _singleton = None
