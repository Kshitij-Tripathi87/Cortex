"""Engine types — frozen dataclasses shared across the disruption engines.

These are the canonical contracts for the pure-functional Morning Brief
pipeline (ADR-0003: Deterministic MVP). Every engine takes typed inputs and
returns typed outputs; no engine touches a database or the network.

Two halves:

  * Supply-chain snapshot inputs (``*Data``) — plain, normalized records the
    orchestrator assembles from the workspace's ``operational.*`` /
    ``inventory.*`` / ``orders.*`` tables. They intentionally mirror the ORM
    models in ``app.modules.supply_chain.models`` but are free of SQLAlchemy so
    the engines are trivially unit-testable.

  * Morning Brief outputs (``*Result`` / ``*Score``) — frozen, serializable,
    provenance-carrying records that the orchestrator persists to
    ``analytics.impact_reports.payload``.

Design rules (non-negotiable per the locked directive):
  * Every record is ``frozen=True``.
  * Every record is serializable via ``to_dict()``.
  * Every number is traceable to a dataset row or an explicit formula.
  * Determinism: identical inputs produce identical outputs (no wall-clock,
    no RNG, no nondeterministic dict iteration order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

# ─────────────────────────────────────────────────────────────────────────────
# Enums (business-facing, distinct from the generic graph enums)
# ─────────────────────────────────────────────────────────────────────────────


class BriefScenarioType(StrEnum):
    """The single MVP scenario the Decision Brief answers (LOCKED SCOPE)."""

    SUPPLIER_FAILURE = "supplier_failure"
    SUPPLIER_DELAY = "supplier_delay"


class DisruptionKind(StrEnum):
    """How the source supplier is affected in the scenario under test."""

    FAILURE = "failure"  # supplier cannot ship at all
    DELAY = "delay"  # supplier ships late, partial recovery over time


class ImpactDomain(StrEnum):
    """The 6 business-impact components required by Conflict B resolution."""

    REVENUE_RISK = "revenue_risk"
    MARGIN_RISK = "margin_risk"
    PENALTY_EXPOSURE = "penalty_exposure"
    WORKING_CAPITAL = "working_capital"
    CUSTOMER_IMPACT = "customer_impact"
    OPERATIONAL_IMPACT = "operational_impact"


class ConfidenceComponent(StrEnum):
    """The 5 decision-confidence sub-scores required by Conflict C resolution."""

    COMPLETENESS = "completeness"
    FRESHNESS = "freshness"
    AGREEMENT = "agreement"
    CONFLICT_DENSITY = "conflict_density"
    HISTORICAL_VALIDATION = "historical_validation"


class RecommendAction(StrEnum):
    """Fixed action taxonomy (no AI ranking, no RL).

    Only these five actions may appear in a Morning Brief per the directive's
    RECOMMENDATION ENGINE section.
    """

    ALTERNATE_SUPPLIER = "alternate_supplier"
    INVENTORY_TRANSFER = "inventory_transfer"
    EXPEDITE = "expedite"
    REROUTE = "reroute"
    MONITOR = "monitor"


class TimelineBucket(StrEnum):
    """Fixed hour buckets for the timeline engine (LOCKED)."""

    H0 = "h0"
    H12 = "h12"
    H24 = "h24"
    H48 = "h48"
    H72 = "h72"

    @classmethod
    def hours(cls) -> list[int]:
        """Hour offsets backing each bucket, in ascending order."""
        return [0, 12, 24, 48, 72]

    @classmethod
    def ordered(cls) -> list[TimelineBucket]:
        return [cls.H0, cls.H12, cls.H24, cls.H48, cls.H72]

    def hour(self) -> int:
        return {self.H0: 0, self.H12: 12, self.H24: 24, self.H48: 48, self.H72: 72}[self]


class StockoutStatus(StrEnum):
    """Stock state for an affected SKU at a point in time."""

    OK = "ok"
    AT_SAFETY = "at_safety"
    BELOW_SAFETY = "below_safety"
    STOCKED_OUT = "stocked_out"


# ─────────────────────────────────────────────────────────────────────────────
# Supply-chain snapshot inputs — plain, ORM-free, workspace-scoped
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SupplierData:
    id: UUID
    name: str
    country: str
    tier: str
    lead_time_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "country": self.country,
            "tier": self.tier,
            "lead_time_days": self.lead_time_days,
        }


@dataclass(frozen=True)
class ComponentData:
    id: UUID
    sku: str
    name: str
    category: str | None
    unit_of_measure: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "unit_of_measure": self.unit_of_measure,
        }


@dataclass(frozen=True)
class WarehouseData:
    id: UUID
    code: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
        }


@dataclass(frozen=True)
class FactoryData:
    id: UUID
    code: str
    name: str
    throughput_per_day: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "throughput_per_day": self.throughput_per_day,
        }


@dataclass(frozen=True)
class ProductData:
    id: UUID
    sku: str
    name: str
    factory_id: UUID | None
    unit_price: float | None
    margin_pct: float
    lead_time_days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "sku": self.sku,
            "name": self.name,
            "factory_id": str(self.factory_id) if self.factory_id else None,
            "unit_price": self.unit_price,
            "margin_pct": self.margin_pct,
            "lead_time_days": self.lead_time_days,
        }


@dataclass(frozen=True)
class CustomerData:
    id: UUID
    name: str
    country: str
    tier: str | None
    contract_value_annual: float | None
    late_delivery_penalty_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "country": self.country,
            "tier": self.tier,
            "contract_value_annual": self.contract_value_annual,
            "late_delivery_penalty_pct": self.late_delivery_penalty_pct,
        }


@dataclass(frozen=True)
class EdgeData:
    """A directed supply-chain relationship.

    Direction semantics follow MVP §3.2 propagation:
        supplier --supplies--> component
        component --stored_in--> warehouse
        factory --consumes--> component
        factory --makes--> product
        customer --orders--> product
    """

    from_type: str
    from_id: UUID
    to_type: str
    to_id: UUID
    edge_type: str
    weight: float | None = None

    def key(self) -> tuple[str, str, str, str, str]:
        return (
            self.from_type,
            str(self.from_id),
            self.to_type,
            str(self.to_id),
            self.edge_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_type": self.from_type,
            "from_id": str(self.from_id),
            "to_type": self.to_type,
            "to_id": str(self.to_id),
            "edge_type": self.edge_type,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class InventoryData:
    warehouse_id: UUID
    component_id: UUID
    quantity: int
    safety_stock: int
    daily_usage: int  # units consumed/day for this component at this warehouse
    last_updated_at: datetime

    @property
    def coverage_days(self) -> float:
        """How many days current stock covers at current usage. inf if no usage."""
        if self.daily_usage <= 0:
            return float("inf")
        return self.quantity / self.daily_usage

    def to_dict(self) -> dict[str, Any]:
        return {
            "warehouse_id": str(self.warehouse_id),
            "component_id": str(self.component_id),
            "quantity": self.quantity,
            "safety_stock": self.safety_stock,
            "daily_usage": self.daily_usage,
            "last_updated_at": self.last_updated_at.isoformat(),
            "coverage_days": None
            if self.coverage_days == float("inf")
            else round(self.coverage_days, 4),
        }


@dataclass(frozen=True)
class BomData:
    product_id: UUID
    component_id: UUID
    quantity_per_unit: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": str(self.product_id),
            "component_id": str(self.component_id),
            "quantity_per_unit": self.quantity_per_unit,
        }


@dataclass(frozen=True)
class OrderData:
    id: UUID
    customer_id: UUID
    product_id: UUID
    quantity: int
    status: str  # OrderStatus value
    order_date: date
    requested_delivery_date: date
    actual_delivery_date: date | None
    unit_price: float | None  # falling-back price if product price missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "customer_id": str(self.customer_id),
            "product_id": str(self.product_id),
            "quantity": self.quantity,
            "status": self.status,
            "order_date": self.order_date.isoformat(),
            "requested_delivery_date": self.requested_delivery_date.isoformat(),
            "actual_delivery_date": self.actual_delivery_date.isoformat()
            if self.actual_delivery_date
            else None,
            "unit_price": self.unit_price,
        }


@dataclass(frozen=True)
class SupplyChainSnapshot:
    """Immutable, workspace-scoped snapshot fed to every engine.

    Assembled by the Morning Brief orchestrator from repositories. Carrying the
    whole snapshot (rather than live DB handles) is what keeps the engines
    pure-functional and replay-deterministic.
    """

    workspace_id: UUID
    as_of: datetime
    suppliers: tuple[SupplierData, ...] = ()
    components: tuple[ComponentData, ...] = ()
    warehouses: tuple[WarehouseData, ...] = ()
    factories: tuple[FactoryData, ...] = ()
    products: tuple[ProductData, ...] = ()
    customers: tuple[CustomerData, ...] = ()
    edges: tuple[EdgeData, ...] = ()
    inventory: tuple[InventoryData, ...] = ()
    bom: tuple[BomData, ...] = ()
    orders: tuple[OrderData, ...] = ()

    def supplier_by_id(self, supplier_id: UUID) -> SupplierData | None:
        return next((s for s in self.suppliers if s.id == supplier_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "as_of": self.as_of.isoformat(),
            "suppliers": [s.to_dict() for s in self.suppliers],
            "components": [c.to_dict() for c in self.components],
            "warehouses": [w.to_dict() for w in self.warehouses],
            "factories": [f.to_dict() for f in self.factories],
            "products": [p.to_dict() for p in self.products],
            "customers": [c.to_dict() for c in self.customers],
            "edges": [e.to_dict() for e in self.edges],
            "inventory": [i.to_dict() for i in self.inventory],
            "bom": [b.to_dict() for b in self.bom],
            "orders": [o.to_dict() for o in self.orders],
        }


@dataclass(frozen=True)
class DisruptionScenario:
    """The triggering event for a Morning Brief run.

    Maps 1:1 to ``orders.disruption_events``. The supplier is identified by id;
    ``kind`` distinguishes total failure from delay, and ``delay_hours``/\
    ``recovery_hours`` quantify the delay variant.
    """

    workspace_id: UUID
    supplier_id: UUID
    kind: DisruptionKind
    severity: str  # DisruptionSeverity value
    started_at: datetime
    delay_hours: float = 0.0
    recovery_hours: float = 0.0
    description: str | None = None

    def scenario_type(self) -> BriefScenarioType:
        return (
            BriefScenarioType.SUPPLIER_FAILURE
            if self.kind == DisruptionKind.FAILURE
            else BriefScenarioType.SUPPLIER_DELAY
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "supplier_id": str(self.supplier_id),
            "kind": self.kind.value,
            "severity": self.severity,
            "started_at": self.started_at.isoformat(),
            "delay_hours": self.delay_hours,
            "recovery_hours": self.recovery_hours,
            "description": self.description,
            "scenario_type": self.scenario_type().value,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Propagation outputs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AffectedComponent:
    component_id: UUID
    sku: str
    name: str
    hop: int
    attenuated_exposure: float  # 0..1 share of this component's supply affected
    edge_path: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": str(self.component_id),
            "sku": self.sku,
            "name": self.name,
            "hop": self.hop,
            "attenuated_exposure": round(self.attenuated_exposure, 6),
            "edge_path": list(self.edge_path),
        }


@dataclass(frozen=True)
class AffectedProduct:
    product_id: UUID
    sku: str
    name: str
    component_id: UUID  # the bottleneck component tying this product to the blast
    qty_needed_per_unit: float
    hop: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": str(self.product_id),
            "sku": self.sku,
            "name": self.name,
            "component_id": str(self.component_id),
            "qty_needed_per_unit": self.qty_needed_per_unit,
            "hop": self.hop,
        }


@dataclass(frozen=True)
class AffectedOrder:
    order_id: UUID
    customer_id: UUID
    product_id: UUID
    quantity: int
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": str(self.order_id),
            "customer_id": str(self.customer_id),
            "product_id": str(self.product_id),
            "quantity": self.quantity,
            "status": self.status,
        }


@dataclass(frozen=True)
class AffectedWarehouse:
    warehouse_id: UUID
    component_id: UUID
    quantity: int
    safety_stock: int
    daily_usage: int
    coverage_days: float  # inf if no usage

    def to_dict(self) -> dict[str, Any]:
        return {
            "warehouse_id": str(self.warehouse_id),
            "component_id": str(self.component_id),
            "quantity": self.quantity,
            "safety_stock": self.safety_stock,
            "daily_usage": self.daily_usage,
            "coverage_days": None
            if self.coverage_days == float("inf")
            else round(self.coverage_days, 4),
        }


@dataclass(frozen=True)
class PropagationResult:
    """Deterministic blast-radius from a supplier disruption.

    BFS over ``supplier --supplies--> component --[stored_in]--> warehouse``
    plus ``factory --consumes--> component`` and ``factory --makes--> product``
    plus ``component --in--> product`` (via BOM). Inventory is folded in to mark
    components whose stock buffers the disruption.
    """

    source_supplier_id: UUID
    affected_components: tuple[AffectedComponent, ...]
    affected_products: tuple[AffectedProduct, ...]
    affected_warehouses: tuple[AffectedWarehouse, ...]
    open_orders_at_risk: tuple[AffectedOrder, ...]
    max_hop: int
    traversed_edge_types: tuple[str, ...]

    @property
    def component_ids(self) -> tuple[UUID, ...]:
        return tuple(c.component_id for c in self.affected_components)

    @property
    def product_ids(self) -> tuple[UUID, ...]:
        return tuple(p.product_id for p in self.affected_products)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_supplier_id": str(self.source_supplier_id),
            "affected_components": [c.to_dict() for c in self.affected_components],
            "affected_products": [p.to_dict() for p in self.affected_products],
            "affected_warehouses": [w.to_dict() for w in self.affected_warehouses],
            "open_orders_at_risk": [o.to_dict() for o in self.open_orders_at_risk],
            "max_hop": self.max_hop,
            "traversed_edge_types": list(self.traversed_edge_types),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Business impact outputs (6 components)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BusinessImpactScore:
    """Aggregate Business Impact Score in 0..100 plus its 6 components.

    Per Conflict B resolution the brief NEVER surfaces "revenue at risk" alone;
    six named components roll into a single executive score via a fixed,
    documented, deterministic formula.
    """

    revenue_risk_usd: float
    margin_risk_usd: float
    penalty_exposure_usd: float
    working_capital_impact_usd: float
    customer_impact_score: float  # 0..1
    operational_impact_score: float  # 0..1
    overall_score: float  # 0..100 deterministic aggregate
    formula: str  # human-readable description of how overall_score was computed

    def to_dict(self) -> dict[str, Any]:
        return {
            "revenue_risk_usd": round(self.revenue_risk_usd, 2),
            "margin_risk_usd": round(self.margin_risk_usd, 2),
            "penalty_exposure_usd": round(self.penalty_exposure_usd, 2),
            "working_capital_impact_usd": round(self.working_capital_impact_usd, 2),
            "customer_impact_score": round(self.customer_impact_score, 4),
            "operational_impact_score": round(self.operational_impact_score, 4),
            "overall_score": round(self.overall_score, 4),
            "formula": self.formula,
            "components": [d.value for d in ImpactDomain],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Decision confidence outputs (5 sub-scores)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConfidenceScores:
    """Decision Confidence — derived only from 5 documented inputs.

    No magical confidence. ``overall`` is a fixed weighted mean of the five
    sub-scores; the weights and the per-component formulas are recorded in
    ``formula`` for full traceability.
    """

    completeness: float  # 0..1 fraction of required fields populated
    freshness: float  # 0..1 decay from data recency
    agreement: float  # 0..1 cross-source / cross-row consistency
    conflict_density: float  # 0..1 (1 = low conflict, high trust)
    overall: float  # 0..1 fixed weighted aggregate
    formula: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "completeness": round(self.completeness, 4),
            "freshness": round(self.freshness, 4),
            "agreement": round(self.agreement, 4),
            "conflict_density": round(self.conflict_density, 4),
            "historical_validation": 1.0 if self.evidence.get("historically_validated") else 0.0,
            "overall": round(self.overall, 4),
            "formula": self.formula,
            "evidence": dict(self.evidence),
            "components": [d.value for d in ConfidenceComponent],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation outputs (7 visible dimensions ranked by net_benefit)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationScores:
    """The 7 fixed, visible dimensions for a mitigation action.

    All clinical/economic scores are 0..1 (higher is better except where noted);
    cost/time are raw units. ``net_benefit`` is the single deterministic rank
    key — no AI ranking, no reinforcement learning.
    """

    business_impact_reduction: float  # 0..1 fraction of impact mitigated
    execution_cost_usd: float  # raw USD cost of taking the action
    execution_time_hours: float  # raw hours until the action takes effect
    operational_risk: float  # 0..1 (higher = more operational risk)
    customer_impact_protected: float  # 0..1 fraction of customer impact saved
    confidence: float  # 0..1 confidence in the action's effectiveness
    dependency_readiness: float  # 0..1 readiness of required dependencies
    net_benefit: float  # deterministic single rank key
    formula: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "business_impact_reduction": round(self.business_impact_reduction, 4),
            "execution_cost_usd": round(self.execution_cost_usd, 2),
            "execution_time_hours": round(self.execution_time_hours, 4),
            "operational_risk": round(self.operational_risk, 4),
            "customer_impact_protected": round(self.customer_impact_protected, 4),
            "confidence": round(self.confidence, 4),
            "dependency_readiness": round(self.dependency_readiness, 4),
            "net_benefit": round(self.net_benefit, 4),
            "formula": self.formula,
        }


@dataclass(frozen=True)
class Recommendation:
    action: RecommendAction
    name: str
    scores: RecommendationScores
    explanation: str
    evidence: tuple[str, ...]  # traceable evidence identifiers
    rank: int
    applicable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "name": self.name,
            "scores": self.scores.to_dict(),
            "explanation": self.explanation,
            "evidence": list(self.evidence),
            "rank": self.rank,
            "applicable": self.applicable,
        }


@dataclass(frozen=True)
class RecommendationSet:
    recommendations: tuple[Recommendation, ...]
    ranking_formula: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendations": [r.to_dict() for r in self.recommendations],
            "ranking_formula": self.ranking_formula,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Timeline outputs (fixed buckets)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimelineEvent:
    bucket: TimelineBucket
    hours_from_start: int
    title: str
    description: str
    stockout_status: StockoutStatus
    affected_component_ids: tuple[UUID, ...]
    affected_product_ids: tuple[UUID, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket.value,
            "hours_from_start": self.hours_from_start,
            "title": self.title,
            "description": self.description,
            "stockout_status": self.stockout_status.value,
            "affected_component_ids": [str(c) for c in self.affected_component_ids],
            "affected_product_ids": [str(p) for p in self.affected_product_ids],
        }


@dataclass(frozen=True)
class Timeline:
    """The fixed 0/12/24/48/72h bucketed timeline for a disruption.

    Deadlines executives understand, not a graph.
    """

    bucket_zero: datetime
    events: tuple[TimelineEvent, ...]
    stockout_deadline_at: datetime | None  # earliest projected stockout, if any

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_zero": self.bucket_zero.isoformat(),
            "events": [e.to_dict() for e in self.events],
            "stockout_deadline_at": self.stockout_deadline_at.isoformat()
            if self.stockout_deadline_at
            else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Top-level Morning Brief (orchestrator output)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MorningBrief:
    """The single executive brief persisted to ``analytics.impact_reports``."""

    workspace_id: UUID
    scenario: DisruptionScenario
    propagation: PropagationResult
    business_impact: BusinessImpactScore
    confidence: ConfidenceScores
    recommendations: RecommendationSet
    timeline: Timeline
    generated_at: datetime
    computation_run_id: UUID
    evidence_keys: tuple[str, ...]
    failures: tuple[str, ...] = ()  # soft failures (e.g., missing rows), never fatal

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "scenario": self.scenario.to_dict(),
            "propagation": self.propagation.to_dict(),
            "business_impact": self.business_impact.to_dict(),
            "confidence": self.confidence.to_dict(),
            "recommendations": self.recommendations.to_dict(),
            "timeline": self.timeline.to_dict(),
            "generated_at": self.generated_at.isoformat(),
            "computation_run_id": str(self.computation_run_id),
            "evidence_keys": list(self.evidence_keys),
            "failures": list(self.failures),
        }


__all__ = [
    "AffectedComponent",
    "AffectedOrder",
    "AffectedProduct",
    "AffectedWarehouse",
    "BomData",
    "BriefScenarioType",
    "BusinessImpactScore",
    "ComponentData",
    "ConfidenceComponent",
    "ConfidenceScores",
    "CustomerData",
    "DisruptionKind",
    "DisruptionScenario",
    "EdgeData",
    "FactoryData",
    "ImpactDomain",
    "InventoryData",
    "MorningBrief",
    "OrderData",
    "ProductData",
    "PropagationResult",
    "RecommendAction",
    "Recommendation",
    "RecommendationScores",
    "RecommendationSet",
    "StockoutStatus",
    "SupplierData",
    "SupplyChainSnapshot",
    "Timeline",
    "TimelineBucket",
    "TimelineEvent",
    "WarehouseData",
]
