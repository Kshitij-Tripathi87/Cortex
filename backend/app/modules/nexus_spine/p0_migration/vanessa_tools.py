"""Workspace-scoped, evidence-backed tools for the Nexus reasoning pipeline.

All tools are read-only or produce isolated digital-twin simulations. The
LLM cannot write canonical world state, approve a decision, or execute work.
"""

from __future__ import annotations

import logging
import math
from statistics import fmean, pstdev
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot
from app.modules.nexus_spine.ontology.core_types import EntityKind
from app.modules.nexus_spine.ontology.entities import Entity
from app.modules.nexus_spine.p0_migration.authoritative_decisions import (
    get_authoritative_decision_service,
)
from app.modules.nexus_spine.p0_migration.authoritative_inference import (
    get_authoritative_inference_engine,
)
from app.modules.nexus_spine.p0_migration.authoritative_memory import (
    get_authoritative_decision_memory,
)
from app.modules.nexus_spine.p0_migration.authoritative_registries import (
    get_authoritative_registry_service,
)
from app.modules.nexus_spine.p0_migration.authoritative_truth import (
    get_authoritative_truth_loop,
)
from app.modules.nexus_spine.p0_migration.authz import Principal
from app.modules.nexus_spine.p0_migration.vanessa_pipeline import (
    ToolCall,
    VanessaPipeline,
)
from app.modules.nexus_spine.persistence.models import (
    ForecastRecordDB,
    ObservationRecordDB,
)
from app.modules.nexus_spine.scenarios.studio import (
    MutationKind,
    ScenarioDefinition,
    ScenarioMutation,
    ScenarioStudio,
)

_LOG = logging.getLogger(__name__)


def _limit(value: int, maximum: int = 50) -> int:
    return max(1, min(int(value), maximum))


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


async def _latest_graph_snapshot(session: AsyncSession, workspace_id: str) -> GraphSnapshot | None:
    result = await session.execute(
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .order_by(GraphSnapshot.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _graph_read(
    session: AsyncSession, workspace_id: str, *, include_entities: bool = True
) -> dict[str, Any]:
    snapshot = await _latest_graph_snapshot(session, workspace_id)
    node_count = int(
        await session.scalar(
            select(func.count(GraphNode.node_id)).where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.valid_to.is_(None),
            )
        )
        or 0
    )
    edge_count = int(
        await session.scalar(
            select(func.count(GraphEdge.edge_id)).where(
                GraphEdge.workspace_id == workspace_id,
                GraphEdge.valid_to.is_(None),
            )
        )
        or 0
    )
    entities: list[dict[str, Any]] = []
    if include_entities:
        rows = await session.execute(
            select(GraphNode)
            .where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.valid_to.is_(None),
            )
            .order_by(GraphNode.last_modified_version.desc())
            .limit(20)
        )
        for row in rows.scalars().all():
            attrs = row.attributes or {}
            label = (
                attrs.get("name")
                or attrs.get("supplier_name")
                or attrs.get("product_name")
                or attrs.get("sku")
                or attrs.get("code")
                or row.entity_id
            )
            entities.append(
                {
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "label": str(label)[:160],
                    "last_modified_version": row.last_modified_version,
                }
            )
    return {
        "snapshot_id": snapshot.snapshot_id if snapshot else None,
        "world_state_version": snapshot.version if snapshot else 0,
        "snapshot_hash": snapshot.snapshot_hash if snapshot else None,
        "snapshot_sealed_at": snapshot.sealed_at.isoformat() if snapshot else None,
        "active_node_count": node_count,
        "active_edge_count": edge_count,
        "recent_entities": entities,
        "source_batch_id": snapshot.source_batch_id if snapshot else None,
        "evidence_status": (
            "published_graph_available" if snapshot else "no_published_source_batch"
        ),
    }


async def _risk_read(
    session: AsyncSession, principal: Principal, workspace_id: str
) -> dict[str, Any]:
    service = get_authoritative_registry_service()
    risks = await service.list_risks(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        status="open",
    )
    risks = risks[:50]
    summary: dict[str, int] = {}
    for item in risks:
        severity = str(item.get("severity") or "unknown").upper()
        summary[severity] = summary.get(severity, 0) + 1
    return {"open_risks": risks, "count": len(risks), "by_severity": summary}


async def _scenario_read(
    session: AsyncSession, principal: Principal, workspace_id: str
) -> dict[str, Any]:
    scenarios = await get_authoritative_registry_service().list_scenarios(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
    )
    return {"scenarios": scenarios[:50], "count": len(scenarios)}


async def _signal_read(session: AsyncSession, workspace_id: str) -> dict[str, Any]:
    from app.modules.graph.cache import create_cache
    from app.modules.graph.context_engine import (
        OperationalStateEngine,
        SqlOperationalStateRepository,
        create_context_cache,
    )
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService
    from app.modules.graph.signal_engine import SignalEngine

    repository = SqlGraphRepository(session)
    graph_service = GraphService(repository)
    feature_engine = FeatureEngine(graph_service, create_cache())
    context_cache = create_context_cache()
    context_engine = OperationalStateEngine(
        SqlOperationalStateRepository(session, context_cache),
        context_cache=context_cache,
    )
    result = await SignalEngine(feature_engine, context_engine).detect_signals(workspace_id)
    snapshot = result.snapshot
    signals = [
        {
            "signal_id": signal.signal_id,
            "signal_name": signal.signal_name,
            "severity": signal.severity.value,
            "confidence": signal.confidence,
            "category": signal.category.value,
            "affected_node_ids": signal.affected_node_ids[:25],
            "affected_entity_types": signal.affected_entity_types,
            "affected_entity_ids": signal.affected_entity_ids[:25],
            "explanation": signal.explanation,
            "feature_evidence": signal.feature_evidence,
            "snapshot_version": signal.snapshot_version,
            "snapshot_hash": signal.snapshot_hash,
            "created_at": signal.created_at.isoformat(),
        }
        for signal in snapshot.signals
    ]
    return {
        "workspace_id": workspace_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.snapshot_hash,
        "signals": signals[:50],
        "count": len(signals),
        "metadata": snapshot.metadata,
        "computation_time_ms": result.computation_time_ms,
    }


async def _forecast_read(
    session: AsyncSession, principal: Principal, workspace_id: str, sku: str | None = None
) -> dict[str, Any]:
    statement = select(ForecastRecordDB).where(
        ForecastRecordDB.tenant_id == principal.tenant_id,
        ForecastRecordDB.workspace_id == workspace_id,
    )
    if sku:
        statement = statement.where(ForecastRecordDB.sku == sku)
    statement = statement.order_by(ForecastRecordDB.created_at.desc()).limit(25)
    rows = (await session.execute(statement)).scalars().all()
    forecasts = [
        {
            "forecast_id": row.forecast_id,
            "sku": row.sku,
            "model_id": row.model_id,
            "model_version": row.model_version,
            "world_state_version": row.world_state_version,
            "horizon_days": row.horizon_days,
            "p10": row.p10,
            "p50": row.p50,
            "p80": row.p80,
            "p95": row.p95,
            "p99": row.p99,
            "confidence": row.confidence,
            "feature_hash": row.feature_hash,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    calibration = await get_authoritative_truth_loop().calibration_for(
        session, tenant_id=principal.tenant_id, workspace_id=workspace_id, sku=sku
    )
    return {
        "forecasts": forecasts,
        "count": len(forecasts),
        "calibration": calibration,
        "sku_filter": sku,
    }


async def _run_demand(
    session: AsyncSession,
    principal: Principal,
    workspace_id: str,
    sku: str | None,
    supplier_id: str | None,
    region: str | None,
) -> dict[str, Any]:
    if not sku:
        return {
            "status": "insufficient_input",
            "message": "A SKU is required to run a demand forecast. Include the product SKU in the question.",
        }
    observation_query = (
        select(ObservationRecordDB)
        .where(
            ObservationRecordDB.tenant_id == principal.tenant_id,
            ObservationRecordDB.workspace_id == workspace_id,
            ObservationRecordDB.sku == sku,
            ObservationRecordDB.observation_type == "demand",
        )
        .order_by(ObservationRecordDB.observed_at.desc())
        .limit(90)
    )
    observations = (await session.execute(observation_query)).scalars().all()
    actuals = [float(row.actual_value) for row in observations if row.actual_value is not None]
    if len(actuals) < 3:
        return {
            "status": "insufficient_history",
            "sku": sku,
            "observations_found": len(actuals),
            "minimum_observations_required": 3,
            "message": "Nexus will not invent a baseline demand value. Ingest at least three historical demand observations or sales periods for this SKU.",
        }
    historical_mean = fmean(actuals)
    if historical_mean <= 0:
        return {
            "status": "invalid_history",
            "sku": sku,
            "observations_found": len(actuals),
            "message": "Historical demand average is not positive; a forecast was not generated.",
        }
    historical_cv = pstdev(actuals) / historical_mean
    graph_snapshot = await _latest_graph_snapshot(session, workspace_id)
    features: dict[str, Any] = {
        "base_demand": historical_mean,
        "historical_mean": historical_mean,
        "historical_cv": historical_cv,
        "volatility": historical_cv,
        "history_observation_count": len(actuals),
    }
    if supplier_id:
        features["supplier_id"] = supplier_id
    if region:
        features["region"] = region
    result = await get_authoritative_inference_engine().predict_demand(
        session,
        tenant_id=principal.tenant_id,
        workspace_id=workspace_id,
        sku=sku,
        features=features,
        horizon_days=14,
        world_state_version=graph_snapshot.version if graph_snapshot else 0,
        supplier_id=supplier_id,
        region=region,
        actor_principal=principal,
    )
    result["training_data"] = {
        "source": "workspace_persisted_observations",
        "observation_count": len(actuals),
        "observation_window_start": min(row.observed_at for row in observations).isoformat(),
        "observation_window_end": max(row.observed_at for row in observations).isoformat(),
        "historical_mean": round(historical_mean, 4),
        "historical_coefficient_of_variation": round(historical_cv, 4),
    }
    result["model_class"] = "probabilistic_baseline_with_observation_derived_features"
    result["limitations"] = [
        "The current forecast engine is a deterministic probabilistic baseline, not a trained SKU-specific model.",
        "The seasonal index is a generic weekly prior; item-specific seasonality requires a longer history and a promoted forecasting model.",
    ]
    return result


def _entity_kind_for_graph_node(node: GraphNode) -> EntityKind | None:
    entity_type = node.entity_type.strip().lower()
    aliases = {
        "supplier": EntityKind.SUPPLIER,
        "customer": EntityKind.CUSTOMER,
        "product": EntityKind.PRODUCT,
        "sku": EntityKind.SKU,
        "component": EntityKind.COMPONENT,
        "warehouse": EntityKind.WAREHOUSE,
        "plant": EntityKind.PLANT,
        "factory": EntityKind.FACTORY,
        "port": EntityKind.PORT,
        "shipment": EntityKind.SHIPMENT,
        "salesorder": EntityKind.SALES_ORDER,
        "sales_order": EntityKind.SALES_ORDER,
        "purchaseorder": EntityKind.PURCHASE_ORDER,
        "purchase_order": EntityKind.PURCHASE_ORDER,
        "carrier": EntityKind.CARRIER,
        "route": EntityKind.ROUTE,
        "inventoryitem": EntityKind.INVENTORY_POSITION,
        "inventory_item": EntityKind.INVENTORY_POSITION,
        "inventoryposition": EntityKind.INVENTORY_POSITION,
        "inventory_position": EntityKind.INVENTORY_POSITION,
    }
    if entity_type == "facility":
        facility_kind = str((node.attributes or {}).get("_facility_type", "")).lower()
        aliases[entity_type] = {
            "warehouse": EntityKind.WAREHOUSE,
            "plant": EntityKind.PLANT,
            "port": EntityKind.PORT,
            "distribution_center": EntityKind.WAREHOUSE,
            "cross_dock": EntityKind.WAREHOUSE,
        }.get(facility_kind, EntityKind.WAREHOUSE)
    return aliases.get(entity_type)


def _entity_from_graph_node(node: GraphNode, tenant_id: UUID, workspace_id: UUID) -> Entity | None:
    kind = _entity_kind_for_graph_node(node)
    if kind is None:
        return None
    attrs = dict(node.attributes or {})
    state = dict(attrs)
    if "on_hand_qty" not in state:
        quantity = state.get("quantity") or state.get("on_hand") or state.get("stock")
        if quantity is not None:
            state["on_hand_qty"] = _as_float(quantity)
    if "safety_stock_qty" not in state and state.get("safety_stock") is not None:
        state["safety_stock_qty"] = _as_float(state.get("safety_stock"))
    if "revenue" not in state:
        revenue = state.get("total_value") or state.get("order_value") or state.get("amount")
        if revenue is not None:
            state["revenue"] = _as_float(revenue)
    label = (
        attrs.get("name")
        or attrs.get("supplier_name")
        or attrs.get("product_name")
        or attrs.get("sku")
        or node.entity_id
    )
    try:
        return Entity(
            entity_id=UUID(node.node_id),
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            kind=kind,
            natural_key=str(node.entity_id),
            name=str(label)[:256],
            source="cortex_canonical_graph",
            confidence=0.75,
            confidence_reason="Derived from a published, provenance-checked graph snapshot.",
            state=state,
            metadata={
                "graph_entity_type": node.entity_type,
                "graph_node_id": node.node_id,
                "graph_last_modified_version": node.last_modified_version,
            },
        )
    except (ValueError, TypeError):
        return None


def register_vanessa_tools(
    pipeline: VanessaPipeline,
    session: AsyncSession,
    principal: Principal,
    workspace_id: str,
) -> None:
    """Register only workspace-scoped evidence tools; no real-world execution."""

    registry = get_authoritative_registry_service()
    memory = get_authoritative_decision_memory()
    decision_service = get_authoritative_decision_service()

    async def graph_read(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        return await _graph_read(session, workspace_id)

    async def risk_read(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        return await _risk_read(session, principal, workspace_id)

    async def signal_read(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        return await _signal_read(session, workspace_id)

    async def scenario_read(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        return await _scenario_read(session, principal, workspace_id)

    async def decisions_list(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        items = await decision_service.list_by_workspace(
            session, tenant_id=principal.tenant_id, workspace_id=workspace_id, limit=25
        )
        return {"decisions": items, "count": len(items)}

    async def trace_read(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        items = await memory.recent(
            session, tenant_id=principal.tenant_id, workspace_id=workspace_id, limit=15
        )
        return {"recent_decision_memory": items, "count": len(items)}

    async def forecast_read(tc: ToolCall, _p: Principal) -> dict[str, Any]:
        sku = str(tc.args.get("sku")) if tc.args.get("sku") else None
        return await _forecast_read(session, principal, workspace_id, sku)

    async def cockpit_read(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        graph = await _graph_read(session, workspace_id, include_entities=False)
        risks = await _risk_read(session, principal, workspace_id)
        decisions = await decision_service.list_by_workspace(
            session, tenant_id=principal.tenant_id, workspace_id=workspace_id, limit=25
        )
        return {
            "summary": (
                f"{graph['active_node_count']} active graph entities, "
                f"{graph['active_edge_count']} active relationships, "
                f"{risks['count']} open risks and {len(decisions)} recent decisions."
            ),
            "graph": graph,
            "risk_count": risks["count"],
            "risk_severity": risks["by_severity"],
            "recent_decision_count": len(decisions),
        }

    async def demand_run(tc: ToolCall, _p: Principal) -> dict[str, Any]:
        sku = str(tc.args.get("sku")) if tc.args.get("sku") else None
        supplier_id = str(tc.args.get("supplier_id")) if tc.args.get("supplier_id") else None
        region = str(tc.args.get("region")) if tc.args.get("region") else None
        return await _run_demand(session, principal, workspace_id, sku, supplier_id, region)

    async def recommendation_context(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        # One AsyncSession must not be used by concurrent tasks. Keep these
        # evidence reads ordered within the request transaction.
        graph = await _graph_read(session, workspace_id)
        risks = await _risk_read(session, principal, workspace_id)
        signals = await _signal_read(session, workspace_id)
        scenarios = await _scenario_read(session, principal, workspace_id)
        decisions = await decision_service.list_by_workspace(
            session, tenant_id=principal.tenant_id, workspace_id=workspace_id, limit=10
        )
        return {
            "analysis_context": {
                "graph": graph,
                "open_risks": risks,
                "signals": signals,
                "scenarios": scenarios,
                "recent_decisions": decisions,
            },
            "recommendation_scope": "evidence-grounded analyst suggestions only",
            "execution_authority": "not granted; use governed decision and approval workflows",
        }

    async def scenario_simulate(tc: ToolCall, _p: Principal) -> dict[str, Any]:
        args = tc.args
        scenario_id = str(args.get("scenario_id") or "").strip()
        graph_snapshot = await _latest_graph_snapshot(session, workspace_id)
        graph_rows = (
            (
                await session.execute(
                    select(GraphNode)
                    .where(
                        GraphNode.workspace_id == workspace_id,
                        GraphNode.valid_to.is_(None),
                    )
                    .order_by(GraphNode.last_modified_version.desc())
                    .limit(5000)
                )
            )
            .scalars()
            .all()
        )
        try:
            tenant_uuid = UUID(principal.tenant_id)
        except ValueError:
            tenant_uuid = UUID(workspace_id)
        workspace_uuid = UUID(workspace_id)
        entities = [
            entity
            for row in graph_rows
            if (entity := _entity_from_graph_node(row, tenant_uuid, workspace_uuid)) is not None
        ]
        if not entities:
            return {
                "status": "no_simulatable_entities",
                "world_state_version": graph_snapshot.version if graph_snapshot else 0,
                "message": "Publish a canonical graph snapshot containing supported supply-chain entity types before simulating.",
            }

        if scenario_id:
            stored = await registry.get_scenario(session, scenario_id)
            if stored["workspace_id"] != workspace_id or stored["tenant_id"] != principal.tenant_id:
                return {"status": "not_found", "message": "Scenario not found in this workspace."}
            outcome = await registry.simulate_scenario(
                session,
                scenario_id,
                entities,
                world_state_version=graph_snapshot.version if graph_snapshot else 0,
            )
            return {
                "status": "completed",
                "mode": "saved_scenario",
                "scenario": stored,
                "outcome": outcome,
                "graph_entities_loaded": len(entities),
            }

        mutation_kind_raw = str(args.get("mutation_kind") or "").strip().lower()
        try:
            mutation_kind = MutationKind(mutation_kind_raw)
        except ValueError:
            return {
                "status": "insufficient_input",
                "message": (
                    "A counterfactual needs an explicit supported mutation and a target entity. "
                    "Supported mutations include supplier_failure, demand_surge, capacity_shock, "
                    "port_closure, lead_time_increase and price_change."
                ),
            }

        target_ref = (
            str(args.get("target_entity_id") or "").strip()
            or str(args.get("supplier_id") or "").strip()
            or str(args.get("sku") or "").strip()
            or str(args.get("entity_id") or "").strip()
        )
        target_rows = [
            row for row in graph_rows if row.entity_id == target_ref or row.node_id == target_ref
        ]
        if len(target_rows) != 1:
            return {
                "status": "target_not_found_or_ambiguous",
                "target": target_ref or None,
                "matches": len(target_rows),
                "message": "Specify one canonical supplier_id, SKU, or graph node ID present in the published workspace graph.",
            }
        target = target_rows[0]
        parameters: dict[str, Any] = {}
        if mutation_kind == MutationKind.SUPPLIER_FAILURE:
            parameters["availability_pct"] = _as_float(args.get("availability_pct"))
            if parameters["availability_pct"] is None:
                parameters["availability_pct"] = 0.0
        elif mutation_kind == MutationKind.DEMAND_SURGE:
            parameters["demand_multiplier"] = _as_float(args.get("demand_multiplier"))
        elif mutation_kind == MutationKind.CAPACITY_SHOCK:
            parameters["capacity_pct"] = _as_float(args.get("capacity_pct"))
        elif mutation_kind == MutationKind.PORT_CLOSURE:
            parameters["closure_days"] = _as_float(args.get("closure_days"))
        elif mutation_kind == MutationKind.LEAD_TIME_INCREASE:
            parameters["extra_days"] = _as_float(args.get("delay_days"))
        elif mutation_kind == MutationKind.PRICE_CHANGE:
            parameters["unit_price"] = _as_float(args.get("unit_price"))
        if any(value is None for value in parameters.values()):
            return {
                "status": "insufficient_input",
                "mutation_kind": mutation_kind.value,
                "message": "The requested mutation requires a numeric parameter explicitly supplied in the question.",
            }
        mutation = ScenarioMutation(
            kind=mutation_kind,
            target_entity_id=UUID(target.node_id),
            parameters=parameters,
        )
        scenario = ScenarioDefinition(
            name=f"Vanessa what-if: {mutation_kind.value}",
            workspace_id=workspace_id,
            tenant_id=str(tenant_uuid),
            description="One-run counterfactual generated from the user's explicit question; no canonical state is changed.",
            mutations=[mutation],
        )
        result = ScenarioStudio().run_with_snapshot(
            scenario,
            entities,
            tenant_id=tenant_uuid,
            workspace_id=workspace_uuid,
            world_state_version=graph_snapshot.version if graph_snapshot else 0,
        )
        return {
            "status": "completed",
            "mode": "ephemeral_counterfactual",
            "scenario": {
                "scenario_id": result.scenario_id,
                "mutation_kind": mutation_kind.value,
                "target_entity_type": target.entity_type,
                "target_entity_id": target.entity_id,
                "parameters": parameters,
            },
            "outcome": result.to_dict(),
            "graph_entities_loaded": len(entities),
            "graph_entities_skipped": len(graph_rows) - len(entities),
            "world_state_version": graph_snapshot.version if graph_snapshot else 0,
            "assumptions": [
                "Counterfactual uses the current published graph snapshot.",
                "Only the supported fields modeled by the digital twin are changed.",
                "This is an advisory simulation; no operational state or external system is modified.",
            ],
        }

    async def explain(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        return {
            "architecture": [
                "Authenticated source upload and immutable object storage",
                "Source profiling, canonical mapping suggestions, claim review and conflict resolution",
                "Integrity-checked publication into the workspace-scoped operational graph",
                "Feature, context, signal, risk, forecast and scenario engines",
                "Evidence-grounded reasoning with a configured model provider",
                "Human-governed decision, approval and execution endpoints",
                "Forecast observations and decision outcomes feed the truth and calibration loops",
            ],
            "authority_boundary": (
                "Vanessa can retrieve evidence and run an isolated digital-twin scenario. "
                "It cannot approve or execute operational changes."
            ),
        }

    async def recommendation(_tc: ToolCall, _p: Principal) -> dict[str, Any]:
        return await recommendation_context(_tc, _p)

    tools = {
        "nexus.cockpit.read": cockpit_read,
        "nexus.graph.read": graph_read,
        "nexus.risk.read": risk_read,
        "nexus.signal.read": signal_read,
        "nexus.scenario.read": scenario_read,
        "nexus.scenario.simulate": scenario_simulate,
        "nexus.forecast.read": forecast_read,
        "nexus.decision.list": decisions_list,
        "nexus.trace.get": trace_read,
        "nexus.demand.run": demand_run,
        "nexus.recommend": recommendation,
        "nexus.explain": explain,
    }
    for tool_name, executor in tools.items():
        pipeline.register_tool_executor(tool_name, executor)
