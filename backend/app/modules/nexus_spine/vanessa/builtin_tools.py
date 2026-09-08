"""Nexus Vanessa — Concrete Tool Implementations.

Each tool reads from the live world model / demand engine / decision memory
and produces a structured ToolResult. Tools never invent data — they only
return what the deterministic engines produced.

This module registers all tools into a default ToolRegistry; callers can
construct their own registry with a different set if needed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.nexus_spine.demand import get_demand_engine, get_truth_loop
from app.modules.nexus_spine.memory import get_decision_memory
from app.modules.nexus_spine.ontology import (
    EntityKind,
    EntityQuery,
    get_world_model,
)
from app.modules.nexus_spine.ontology.core_types import EntityKind as _EK
from app.modules.nexus_spine.vanessa.tools import (
    Tool,
    ToolCall,
    ToolPermission,
    ToolRegistry,
    ToolResult,
)

# ──────────────────────────────────────────────────────────────────────────────
# Input schemas
# ──────────────────────────────────────────────────────────────────────────────


class QueryWorldStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kinds: list[str] | None = Field(default=None)
    text_search: str | None = Field(default=None)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=50, ge=1, le=200)


class TraverseGraphInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_entity_id: str
    max_depth: int = Field(default=3, ge=1, le=6)


class GetSignalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str | None = None
    min_severity: float = Field(default=0.0, ge=0.0, le=1.0)


class GetBlastRadiusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_entity_id: str
    max_depth: int = Field(default=4, ge=1, le=6)


class GetForecastInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    horizon_days: int = Field(default=14, ge=1, le=365)


class CompareForecastActualInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str
    min_samples: int = Field(default=3, ge=1)


class GetSupplierRiskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_entity_id: str | None = None
    min_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class GetOrdersAtRiskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_revenue: float = Field(default=0.0, ge=0.0)


class GetDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str


class FindAnalogousDecisionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    situation: str
    limit: int = Field(default=5, ge=1, le=20)


# ──────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────────────


class QueryWorldStateTool(Tool):
    name = "query_world_state"
    description = "Query entities in the Nexus world model. Supports filtering by kind, text search, and confidence."
    permission = ToolPermission.AUTHENTICATED
    input_schema = QueryWorldStateInput

    def invoke(self, call: ToolCall) -> ToolResult:
        wm = get_world_model()
        kinds = None
        if call.arguments.get("kinds"):
            kinds = []
            for k in call.arguments["kinds"]:
                try:
                    kinds.append(EntityKind(k))
                except ValueError:
                    return ToolResult(
                        call_id=call.call_id,
                        tool_name=self.name,
                        ok=False,
                        error=f"unknown entity kind: {k}",
                    )
        query = EntityQuery(
            tenant_id=call.tenant_id,
            workspace_id=call.workspace_id,
            kinds=kinds,
            text_search=call.arguments.get("text_search"),
            min_confidence=call.arguments.get("min_confidence", 0.0),
            limit=call.arguments.get("limit", 50),
            offset=0,
        )
        page = wm.query(query)
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={
                "total": page.total,
                "count": len(page.items),
                "entities": [
                    {
                        "entity_id": str(e.entity_id),
                        "kind": e.kind.value,
                        "natural_key": e.natural_key,
                        "name": e.name,
                        "state": dict(e.state),
                        "confidence": e.confidence,
                        "updated_at": e.updated_at.isoformat(),
                    }
                    for e in page.items
                ],
            },
            evidence=["world_model_repository.query"],
        )


class TraverseGraphTool(Tool):
    name = "traverse_graph"
    description = "BFS traversal from a seed entity up to max_depth. Returns all reachable downstream entities and edges."
    permission = ToolPermission.AUTHENTICATED
    input_schema = TraverseGraphInput

    def invoke(self, call: ToolCall) -> ToolResult:
        wm = get_world_model()
        try:
            seed_id = UUID(call.arguments["seed_entity_id"])
        except (KeyError, ValueError) as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=self.name,
                ok=False,
                error=f"invalid seed_entity_id: {exc}",
            )
        if wm.get(call.tenant_id, call.workspace_id, seed_id) is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=self.name,
                ok=False,
                error="seed entity not found",
            )
        reachable = wm.neighbors(
            call.tenant_id,
            call.workspace_id,
            seed_id,
            direction="out",
            max_depth=call.arguments.get("max_depth", 3),
        )
        entities = []
        for entity_id, edge in reachable:
            ent = wm.get(call.tenant_id, call.workspace_id, entity_id)
            if ent is None:
                continue
            entities.append(
                {
                    "entity_id": str(entity_id),
                    "kind": ent.kind.value,
                    "name": ent.name,
                    "via_edge": edge.kind.value,
                    "edge_confidence": edge.confidence,
                }
            )
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={"reachable": entities, "count": len(entities)},
            evidence=["world_model_repository.neighbors"],
        )


class GetSignalTool(Tool):
    name = "get_signal"
    description = "List active signals (operational anomalies) for the workspace, optionally filtered by entity or severity."
    permission = ToolPermission.AUTHENTICATED
    input_schema = GetSignalInput

    def invoke(self, call: ToolCall) -> ToolResult:
        wm = get_world_model()
        query = EntityQuery(
            tenant_id=call.tenant_id,
            workspace_id=call.workspace_id,
            kinds=[_EK.SIGNAL],
            min_confidence=0.0,
            limit=200,
            offset=0,
        )
        page = wm.query(query)
        out = []
        for s in page.items:
            sev = s.state.get("severity_score", 0.0)
            if sev < call.arguments.get("min_severity", 0.0):
                continue
            if (
                call.arguments.get("entity_id")
                and s.state.get("affected_entity_id") != call.arguments["entity_id"]
            ):
                continue
            out.append(
                {
                    "entity_id": str(s.entity_id),
                    "name": s.name,
                    "description": s.description,
                    "severity": sev,
                    "signal_type": s.state.get("signal_type"),
                    "affected_entity_id": s.state.get("affected_entity_id"),
                    "acknowledged": s.state.get("acknowledged", False),
                    "confidence": s.confidence,
                    "created_at": s.created_at.isoformat(),
                }
            )
        out.sort(key=lambda x: x["severity"], reverse=True)
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={"signals": out, "count": len(out)},
            evidence=["world_model_repository.query(kinds=[SIGNAL])"],
        )


class GetBlastRadiusTool(Tool):
    name = "get_blast_radius"
    description = (
        "Compute the supply-chain blast radius from a seed entity (typically a supplier or port)."
    )
    permission = ToolPermission.ANALYST
    input_schema = GetBlastRadiusInput

    def invoke(self, call: ToolCall) -> ToolResult:
        wm = get_world_model()
        try:
            seed_id = UUID(call.arguments["seed_entity_id"])
        except (KeyError, ValueError) as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=self.name,
                ok=False,
                error=f"invalid seed_entity_id: {exc}",
            )
        seed = wm.get(call.tenant_id, call.workspace_id, seed_id)
        if seed is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=self.name,
                ok=False,
                error="seed entity not found",
            )
        paths = wm.traverse_supply_chain(
            call.tenant_id,
            call.workspace_id,
            seed_id,
            max_depth=call.arguments.get("max_depth", 4),
        )
        affected = []
        revenue_exposed = 0.0
        for entity_id, edges in paths.items():
            ent = wm.get(call.tenant_id, call.workspace_id, entity_id)
            if ent is None:
                continue
            entry: dict[str, Any] = {
                "entity_id": str(entity_id),
                "kind": ent.kind.value,
                "name": ent.name,
                "hops": len(edges),
            }
            if ent.kind == _EK.SALES_ORDER:
                revenue_exposed += float(ent.state.get("revenue", 0.0))
                entry["revenue"] = ent.state.get("revenue", 0.0)
                entry["sla_risk_pct"] = ent.state.get("sla_risk_pct", 0.0)
            affected.append(entry)
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={
                "seed_entity_id": str(seed_id),
                "seed_name": seed.name,
                "affected_entities": affected,
                "count": len(affected),
                "revenue_exposed": round(revenue_exposed, 2),
            },
            evidence=["world_model_repository.traverse_supply_chain"],
        )


class GetForecastTool(Tool):
    name = "get_forecast"
    description = (
        "Produce a probabilistic demand forecast (P50/P80/P95 + drivers + confidence) for one SKU."
    )
    permission = ToolPermission.AUTHENTICATED
    input_schema = GetForecastInput

    def invoke(self, call: ToolCall) -> ToolResult:
        engine = get_demand_engine()
        forecast = engine.forecast(
            sku=call.arguments["sku"],
            horizon_days=call.arguments.get("horizon_days", 14),
        )
        get_truth_loop().record_forecast(forecast)
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload=forecast.to_dict(),
            evidence=[f"demand_engine.MODEL_VERSION={forecast.model_version}"],
        )


class CompareForecastActualTool(Tool):
    name = "compare_forecast_actual"
    description = "Compare forecast vs reality for a SKU — exposes systematic bias and calibration."
    permission = ToolPermission.ANALYST
    input_schema = CompareForecastActualInput

    def invoke(self, call: ToolCall) -> ToolResult:
        loop = get_truth_loop()
        buckets = loop.calibration_for(call.arguments["sku"])
        flagged = loop.systematic_bias(
            min_samples=call.arguments.get("min_samples", 3),
            bias_threshold=0.05,
        )
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={
                "sku": call.arguments["sku"],
                "calibration": [b.to_dict() for b in buckets],
                "systematic_bias": [b for b in flagged if b["sku"] == call.arguments["sku"]],
            },
            evidence=["truth_loop.calibration_for", "truth_loop.systematic_bias"],
        )


class GetSupplierRiskTool(Tool):
    name = "get_supplier_risk"
    description = (
        "List suppliers with their current risk_score and capacity_pct, optionally filtered."
    )
    permission = ToolPermission.AUTHENTICATED
    input_schema = GetSupplierRiskInput

    def invoke(self, call: ToolCall) -> ToolResult:
        wm = get_world_model()
        query = EntityQuery(
            tenant_id=call.tenant_id,
            workspace_id=call.workspace_id,
            kinds=[_EK.SUPPLIER],
            limit=500,
            offset=0,
        )
        page = wm.query(query)
        out = []
        for s in page.items:
            risk = float(s.state.get("risk_score", 0.0))
            capacity = float(s.state.get("capacity_pct", 100.0))
            if risk < call.arguments.get("min_risk", 0.0):
                continue
            if (
                call.arguments.get("supplier_entity_id")
                and str(s.entity_id) != call.arguments["supplier_entity_id"]
            ):
                continue
            out.append(
                {
                    "entity_id": str(s.entity_id),
                    "name": s.name,
                    "natural_key": s.natural_key,
                    "risk_score": risk,
                    "capacity_pct": capacity,
                    "on_time_rate": s.state.get("on_time_rate"),
                    "lead_time_days": s.state.get("lead_time_days"),
                }
            )
        out.sort(key=lambda x: x["risk_score"], reverse=True)
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={"suppliers": out, "count": len(out)},
            evidence=["world_model_repository.query(kinds=[SUPPLIER])"],
        )


class GetOrdersAtRiskTool(Tool):
    name = "get_orders_at_risk"
    description = "List sales orders at risk of SLA breach, filtered by minimum revenue."
    permission = ToolPermission.AUTHENTICATED
    input_schema = GetOrdersAtRiskInput

    def invoke(self, call: ToolCall) -> ToolResult:
        wm = get_world_model()
        query = EntityQuery(
            tenant_id=call.tenant_id,
            workspace_id=call.workspace_id,
            kinds=[_EK.SALES_ORDER],
            limit=500,
            offset=0,
        )
        page = wm.query(query)
        out = []
        for o in page.items:
            revenue = float(o.state.get("revenue", 0.0))
            sla_risk = float(o.state.get("sla_risk_pct", 0.0))
            if revenue < call.arguments.get("min_revenue", 0.0):
                continue
            if sla_risk <= 0.0:
                continue
            out.append(
                {
                    "entity_id": str(o.entity_id),
                    "name": o.name,
                    "revenue": revenue,
                    "sla_risk_pct": sla_risk,
                    "customer_id": o.state.get("customer_id"),
                    "promised_delivery": o.state.get("promised_delivery"),
                    "status": o.state.get("status"),
                }
            )
        out.sort(key=lambda x: x["revenue"] * x["sla_risk_pct"], reverse=True)
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={
                "orders_at_risk": out,
                "count": len(out),
                "total_revenue_at_risk": round(sum(o["revenue"] for o in out), 2),
            },
            evidence=["world_model_repository.query(kinds=[SALES_ORDER])"],
        )


class GetDecisionTool(Tool):
    name = "get_decision"
    description = "Retrieve a recorded decision by id."
    permission = ToolPermission.AUTHENTICATED
    input_schema = GetDecisionInput

    def invoke(self, call: ToolCall) -> ToolResult:
        record = get_decision_memory().get(call.arguments["decision_id"])
        if record is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=self.name,
                ok=False,
                error="decision not found",
            )
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload=record.to_dict(),
            evidence=["decision_memory.get"],
        )


class FindAnalogousDecisionsTool(Tool):
    name = "find_analogous_decisions"
    description = "Find past decisions similar to the given situation, with outcomes. Used to ground recommendations in organizational history."
    permission = ToolPermission.ANALYST
    input_schema = FindAnalogousDecisionsInput

    def invoke(self, call: ToolCall) -> ToolResult:
        analogous = get_decision_memory().find_analogous(
            tenant_id=str(call.tenant_id),
            workspace_id=str(call.workspace_id),
            situation=call.arguments["situation"],
            limit=call.arguments.get("limit", 5),
        )
        return ToolResult(
            call_id=call.call_id,
            tool_name=self.name,
            ok=True,
            payload={
                "analogous_decisions": [a.to_dict() for a in analogous],
                "count": len(analogous),
            },
            evidence=["decision_memory.find_analogous"],
        )


# ──────────────────────────────────────────────────────────────────────────────
# Default registry
# ──────────────────────────────────────────────────────────────────────────────


def build_default_registry() -> ToolRegistry:
    """Construct the standard Vanessa tool registry with all grounded tools."""
    registry = ToolRegistry()
    registry.register(QueryWorldStateTool())
    registry.register(TraverseGraphTool())
    registry.register(GetSignalTool())
    registry.register(GetBlastRadiusTool())
    registry.register(GetForecastTool())
    registry.register(CompareForecastActualTool())
    registry.register(GetSupplierRiskTool())
    registry.register(GetOrdersAtRiskTool())
    registry.register(GetDecisionTool())
    registry.register(FindAnalogousDecisionsTool())
    return registry


_singleton: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide singleton ToolRegistry."""
    global _singleton
    if _singleton is None:
        _singleton = build_default_registry()
    return _singleton


def reset_tool_registry() -> None:
    """Reset the singleton — used by tests only."""
    global _singleton
    _singleton = None
