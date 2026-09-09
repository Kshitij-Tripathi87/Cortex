"""Nexus v0.8 P0 — Authoritative golden-path registries (v0.8.5-B3).

Promotes ``RiskRepository`` / ``ScenarioRepository`` / ``EvidenceRepository``
from dead code (called by nothing, not even tests — register finding F3)
to the canonical write path behind ``/nexus/risks|signals|scenarios`` and
the decision evidence / approval APIs.

Conventions mirror ``AuthoritativeDecisionService``:

* every mutation runs in the caller's ``AsyncSession`` and is flushed, never
  committed (the endpoint owns the commit);
* every mutation appends an in-transaction outbox event via
  ``allocate_outbox_seq``;
* ``ValueError`` means "not found" (→ 404), ``RegistryValidationError``
  means "bad request" (→ 400), ``RegistryConflictError`` means "duplicate"
  (→ 409).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.outbox_publisher import allocate_outbox_seq
from app.modules.nexus_spine.ontology.entities import Entity
from app.modules.nexus_spine.persistence.models import (
    EventRecordDB,
    EvidenceEdgeDB,
    EvidenceNodeDB,
    RiskRecordDB,
    ScenarioRecordDB,
)
from app.modules.nexus_spine.persistence.repositories import (
    get_approval_repository,
    get_evidence_repository,
    get_risk_repository,
    get_scenario_repository,
)
from app.modules.nexus_spine.realtime_events import NexusEventType
from app.modules.nexus_spine.scenarios.studio import (
    ScenarioDefinition,
    ScenarioMutation,
    ScenarioStudio,
)

RISK_SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "WATCH"})
RISK_STATUSES = frozenset({"open", "mitigated", "closed", "stale"})
EVIDENCE_NODE_TYPES = frozenset(
    {
        "observation",
        "signal",
        "forecast",
        "risk",
        "scenario",
        "decision",
        "approval",
        "execution",
        "outcome",
        "claim",
    }
)
EVIDENCE_RELATIONS = frozenset(
    {"supports", "causes", "informs", "contradicts", "proves", "derived_from"}
)


class RegistryValidationError(ValueError):
    """Caller error (→ 400): bad enum, out-of-range score, corrupt payload."""


class RegistryConflictError(ValueError):
    """Duplicate write (→ 409). Caught before the 404-mapping ValueError."""


def _utc_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _checksum(canonical: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


async def _emit(
    session: AsyncSession,
    *,
    tenant_id: str,
    workspace_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
    world_state_version: int = 0,
) -> None:
    seq = await allocate_outbox_seq(session, tenant_id=tenant_id, workspace_id=workspace_id)
    session.add(
        EventRecordDB(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            seq=seq,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            world_state_version=world_state_version,
        )
    )


def _risk_to_dict(rec: RiskRecordDB) -> dict[str, Any]:
    return {
        "risk_id": rec.risk_id,
        "tenant_id": rec.tenant_id,
        "workspace_id": rec.workspace_id,
        "entity_id": rec.entity_id,
        "entity_kind": rec.entity_kind,
        "severity": rec.severity,
        "risk_score": rec.risk_score,
        "gnn_risk_score": rec.gnn_risk_score,
        "title": rec.title,
        "description": rec.description,
        "blast_radius_count": rec.blast_radius_count,
        "revenue_exposure": rec.revenue_exposure,
        "sla_risk_pct": rec.sla_risk_pct,
        "root_causes": rec.root_causes,
        "hidden_dependencies": rec.hidden_dependencies,
        "world_state_version": rec.world_state_version,
        "status": rec.status,
        "created_at": _utc_iso(rec.created_at),
        "updated_at": _utc_iso(rec.updated_at),
    }


def _scenario_to_dict(rec: ScenarioRecordDB) -> dict[str, Any]:
    return {
        "scenario_id": rec.scenario_id,
        "tenant_id": rec.tenant_id,
        "workspace_id": rec.workspace_id,
        "name": rec.name,
        "description": rec.description,
        "decision_id": rec.decision_id,
        "parent_scenario_id": rec.parent_scenario_id,
        "is_baseline": rec.is_baseline,
        "mutations": rec.mutations,
        "kpi_results": rec.kpi_results,
        "gnn_insights": rec.gnn_insights,
        "world_state_version": rec.world_state_version,
        "status": rec.status,
        "started_at": _utc_iso(rec.started_at),
        "completed_at": _utc_iso(rec.completed_at),
        "created_at": _utc_iso(rec.created_at),
    }


def _node_to_dict(rec: EvidenceNodeDB) -> dict[str, Any]:
    return {
        "node_id": rec.node_id,
        "decision_id": rec.decision_id,
        "tenant_id": rec.tenant_id,
        "workspace_id": rec.workspace_id,
        "node_type": rec.node_type,
        "label": rec.label,
        "checksum": rec.checksum,
        "payload": rec.payload,
        "source_entity_id": rec.source_entity_id,
        "created_at": _utc_iso(rec.created_at),
    }


def _edge_to_dict(rec: EvidenceEdgeDB) -> dict[str, Any]:
    return {
        "id": rec.id,
        "from_node_id": rec.from_node_id,
        "to_node_id": rec.to_node_id,
        "relation": rec.relation,
        "weight": rec.weight,
        "created_at": _utc_iso(rec.created_at),
    }


class AuthoritativeRegistryService:
    """Canonical write/read path for risks, scenarios, evidence, approvals."""

    # ── Risks ─────────────────────────────────────────────────────────

    async def record_risk(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        entity_id: str,
        entity_kind: str,
        severity: str,
        title: str,
        world_state_version: int,
        risk_score: float = 0.0,
        gnn_risk_score: float | None = None,
        description: str = "",
        blast_radius_count: int = 0,
        revenue_exposure: float | None = None,
        sla_risk_pct: float | None = None,
        root_causes: list[str] | None = None,
        hidden_dependencies: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record (upsert keyed on open risk for the entity) a risk assessment."""
        if severity not in RISK_SEVERITIES:
            raise RegistryValidationError(
                f"invalid severity: {severity} (expected one of {sorted(RISK_SEVERITIES)})"
            )
        if not 0.0 <= risk_score <= 1.0:
            raise RegistryValidationError(f"invalid risk_score: {risk_score} (expected 0.0–1.0)")
        record = RiskRecordDB(
            risk_id=f"risk-{uuid7()}",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            entity_id=entity_id,
            entity_kind=entity_kind,
            severity=severity,
            risk_score=risk_score,
            gnn_risk_score=gnn_risk_score,
            title=title,
            description=description,
            blast_radius_count=blast_radius_count,
            revenue_exposure=revenue_exposure,
            sla_risk_pct=sla_risk_pct,
            root_causes=root_causes or [],
            hidden_dependencies=hidden_dependencies or [],
            world_state_version=world_state_version,
            status="open",
        )
        rec = await get_risk_repository().upsert(session, record)
        await _emit(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            event_type=NexusEventType.RISK_CHANGED.value,
            entity_type="risk",
            entity_id=rec.risk_id,
            payload={"severity": rec.severity, "risk_score": rec.risk_score},
            world_state_version=world_state_version,
        )
        return _risk_to_dict(rec)

    async def list_risks(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        min_severity: str | None = None,
        status: str | None = "open",
    ) -> list[dict[str, Any]]:
        if min_severity is not None and min_severity not in RISK_SEVERITIES:
            raise RegistryValidationError(f"invalid min_severity: {min_severity}")
        if status is not None and status not in RISK_STATUSES:
            raise RegistryValidationError(f"invalid status: {status}")
        recs = await get_risk_repository().list_open(
            session, tenant_id, workspace_id, min_severity, status
        )
        return [_risk_to_dict(rec) for rec in recs]

    async def get_risk(self, session: AsyncSession, risk_id: str) -> dict[str, Any]:
        rec = await get_risk_repository().get(session, risk_id)
        if rec is None:
            raise ValueError(f"Risk {risk_id} not found")
        return _risk_to_dict(rec)

    async def set_risk_status(
        self, session: AsyncSession, risk_id: str, status: str
    ) -> dict[str, Any]:
        if status not in RISK_STATUSES:
            raise RegistryValidationError(
                f"invalid status: {status} (expected one of {sorted(RISK_STATUSES)})"
            )
        rec = await get_risk_repository().set_status(session, risk_id, status)
        if rec is None:
            raise ValueError(f"Risk {risk_id} not found")
        await _emit(
            session,
            tenant_id=rec.tenant_id,
            workspace_id=rec.workspace_id,
            event_type=NexusEventType.RISK_CHANGED.value,
            entity_type="risk",
            entity_id=rec.risk_id,
            payload={"status": rec.status},
            world_state_version=rec.world_state_version,
        )
        return _risk_to_dict(rec)

    # ── Scenarios ─────────────────────────────────────────────────────

    async def create_scenario(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        name: str,
        world_state_version: int,
        description: str = "",
        decision_id: str | None = None,
        parent_scenario_id: str | None = None,
        is_baseline: bool = False,
        mutations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            validated = [ScenarioMutation.model_validate(m) for m in (mutations or [])]
        except ValidationError as exc:
            raise RegistryValidationError(f"invalid mutations: {exc}") from exc
        record = ScenarioRecordDB(
            scenario_id=f"scn-{uuid7()}",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            name=name,
            description=description,
            decision_id=decision_id,
            parent_scenario_id=parent_scenario_id,
            is_baseline=is_baseline,
            mutations=[m.model_dump(mode="json") for m in validated],
            world_state_version=world_state_version,
            status="pending",
        )
        rec = await get_scenario_repository().create(session, record)
        return _scenario_to_dict(rec)

    async def list_scenarios(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        decision_id: str | None = None,
    ) -> list[dict[str, Any]]:
        repo = get_scenario_repository()
        if decision_id is not None:
            recs = await repo.list_by_decision(session, decision_id)
            recs = [r for r in recs if r.workspace_id == workspace_id]
        else:
            recs = await repo.list_by_workspace(session, tenant_id, workspace_id)
        return [_scenario_to_dict(rec) for rec in recs]

    async def get_scenario(self, session: AsyncSession, scenario_id: str) -> dict[str, Any]:
        rec = await get_scenario_repository().get(session, scenario_id)
        if rec is None:
            raise ValueError(f"Scenario {scenario_id} not found")
        return _scenario_to_dict(rec)

    async def simulate_scenario(
        self,
        session: AsyncSession,
        scenario_id: str,
        entities: list[Entity],
        *,
        world_state_version: int = 0,
    ) -> dict[str, Any]:
        """Run the twin's pure simulation core against an explicit snapshot.

        Never touches the process-local world-model singleton: the caller
        supplies the entity snapshot (e.g. sourced from the PG-backed world
        state). Re-simulation is allowed — results are overwritten.
        """
        repo = get_scenario_repository()
        rec = await repo.get(session, scenario_id)
        if rec is None:
            raise ValueError(f"Scenario {scenario_id} not found")
        try:
            definition = ScenarioDefinition(
                scenario_id=rec.scenario_id,
                name=rec.name,
                workspace_id=rec.workspace_id,
                tenant_id=rec.tenant_id,
                description=rec.description or "",
                mutations=[ScenarioMutation.model_validate(m) for m in (rec.mutations or [])],
            )
            tid = UUID(rec.tenant_id)
            wid = UUID(rec.workspace_id)
        except (ValidationError, ValueError) as exc:
            raise RegistryValidationError(f"scenario {scenario_id} cannot simulate: {exc}") from exc
        await repo.mark_running(session, scenario_id)
        result = ScenarioStudio().run_with_snapshot(
            definition,
            entities,
            tenant_id=tid,
            workspace_id=wid,
            world_state_version=world_state_version,
        )
        updated = await repo.complete(session, scenario_id, result.kpis.to_dict())
        await _emit(
            session,
            tenant_id=rec.tenant_id,
            workspace_id=rec.workspace_id,
            event_type=NexusEventType.SCENARIO_COMPLETED.value,
            entity_type="scenario",
            entity_id=scenario_id,
            payload={
                "kpis": result.kpis.to_dict(),
                "affected_entity_ids": result.affected_entity_ids,
            },
            world_state_version=world_state_version,
        )
        return {"scenario": _scenario_to_dict(updated), "result": result.to_dict()}

    # ── Evidence ──────────────────────────────────────────────────────

    async def append_evidence_node(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        decision_id: str,
        node_type: str,
        label: str,
        payload: dict[str, Any] | None = None,
        checksum: str | None = None,
        source_entity_id: str | None = None,
    ) -> dict[str, Any]:
        if node_type not in EVIDENCE_NODE_TYPES:
            raise RegistryValidationError(
                f"invalid node_type: {node_type} (expected one of {sorted(EVIDENCE_NODE_TYPES)})"
            )
        body = payload or {}
        node = EvidenceNodeDB(
            node_id=f"evd-{uuid7()}",
            decision_id=decision_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            node_type=node_type,
            label=label,
            checksum=checksum
            or _checksum(
                {
                    "decision_id": decision_id,
                    "node_type": node_type,
                    "label": label,
                    "payload": body,
                    "source_entity_id": source_entity_id,
                }
            ),
            payload=body,
            source_entity_id=source_entity_id,
        )
        rec = await get_evidence_repository().add_node(session, node)
        await _emit(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            event_type=NexusEventType.EVIDENCE_APPENDED.value,
            entity_type="evidence_node",
            entity_id=rec.node_id,
            payload={"decision_id": decision_id, "node_type": node_type},
        )
        return _node_to_dict(rec)

    async def append_evidence_edge(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        workspace_id: str,
        decision_id: str,
        from_node_id: str,
        to_node_id: str,
        relation: str,
        weight: float = 1.0,
    ) -> dict[str, Any]:
        if relation not in EVIDENCE_RELATIONS:
            raise RegistryValidationError(
                f"invalid relation: {relation} (expected one of {sorted(EVIDENCE_RELATIONS)})"
            )
        repo = get_evidence_repository()
        nodes, edges = await repo.get_graph(session, decision_id)
        node_ids = {n.node_id for n in nodes}
        if from_node_id not in node_ids or to_node_id not in node_ids:
            raise ValueError(f"edge endpoint not found in decision {decision_id} evidence graph")
        for existing in edges:
            if (
                existing.from_node_id == from_node_id
                and existing.to_node_id == to_node_id
                and existing.relation == relation
            ):
                raise RegistryConflictError(
                    f"edge {from_node_id} -[{relation}]-> {to_node_id} already exists"
                )
        rec = await repo.add_edge(
            session,
            EvidenceEdgeDB(
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                relation=relation,
                weight=weight,
            ),
        )
        await _emit(
            session,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            event_type=NexusEventType.EVIDENCE_APPENDED.value,
            entity_type="evidence_edge",
            entity_id=str(rec.id),
            payload={
                "decision_id": decision_id,
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
                "relation": relation,
            },
        )
        return _edge_to_dict(rec)

    async def get_evidence_graph(self, session: AsyncSession, decision_id: str) -> dict[str, Any]:
        nodes, edges = await get_evidence_repository().get_graph(session, decision_id)
        return {
            "decision_id": decision_id,
            "nodes": [_node_to_dict(n) for n in nodes],
            "edges": [_edge_to_dict(e) for e in edges],
        }

    # ── Approvals (B8 read side; writes live in advance()) ────────────

    async def list_approvals(self, session: AsyncSession, decision_id: str) -> list[dict[str, Any]]:
        recs = await get_approval_repository().list_by_decision(session, decision_id)
        return [
            {
                "approval_id": rec.approval_id,
                "decision_id": rec.decision_id,
                "tenant_id": rec.tenant_id,
                "workspace_id": rec.workspace_id,
                "approver_id": rec.approver_id,
                "approver_role": rec.approver_role,
                "decision_hash": rec.decision_hash,
                "approved": rec.approved,
                "rejection_reason": rec.rejection_reason,
                "policy_checks": rec.policy_checks,
                "created_at": _utc_iso(rec.created_at),
            }
            for rec in recs
        ]


_singleton: AuthoritativeRegistryService | None = None


def get_authoritative_registry_service() -> AuthoritativeRegistryService:
    global _singleton
    if _singleton is None:
        _singleton = AuthoritativeRegistryService()
    return _singleton
