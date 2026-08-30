"""Supplier Disruption Decision Brief API — the locked MVP product surface.

Contract version 0.3.0 — exposes the full Morning Brief engine outputs so the
frontend can render the executive screen without further round-trips.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.disruption.engines.brief import run_morning_brief
from app.modules.disruption.engines.types import (
    BomData,
    ComponentData,
    CustomerData,
    DisruptionKind,
    DisruptionScenario,
    EdgeData,
    FactoryData,
    InventoryData,
    OrderData,
    ProductData,
    SupplierData,
    SupplyChainSnapshot,
    WarehouseData,
)
from app.modules.intelligence.shadow_dispatcher import dispatch_shadow_models
from app.modules.supply_chain.models import (
    BillOfMaterials,
    Component,
    Customer,
    Edge,
    Factory,
    Inventory,
    Order,
    Product,
    Supplier,
    Warehouse,
)

router = APIRouter()


CONTRACT_VERSION = "0.3.0"


class SupplierFailureRequest(BaseModel):
    workspace_id: UUID
    supplier_id: UUID
    severity: str = "critical"


class BusinessImpactBlock(BaseModel):
    overall_score: float
    revenue_risk_usd: float
    margin_risk_usd: float
    penalty_exposure_usd: float
    working_capital_impact_usd: float
    customer_impact_score: float
    operational_impact_score: float
    formula: str


class ConfidenceBlock(BaseModel):
    overall: float
    completeness: float
    freshness: float
    agreement: float
    conflict_density: float
    formula: str


class AffectedComponentBlock(BaseModel):
    component_id: str
    sku: str
    name: str
    hop: int
    attenuated_exposure: float


class AffectedProductBlock(BaseModel):
    product_id: str
    sku: str
    name: str
    component_id: str
    qty_needed_per_unit: float
    hop: int


class AffectedWarehouseBlock(BaseModel):
    warehouse_id: str
    component_id: str
    quantity: int
    safety_stock: int
    daily_usage: int
    coverage_days: float | None


class AffectedOrderBlock(BaseModel):
    order_id: str
    customer_id: str
    product_id: str
    quantity: int
    status: str


class PropagationBlock(BaseModel):
    source_supplier_id: str
    affected_components: list[AffectedComponentBlock]
    affected_products: list[AffectedProductBlock]
    affected_warehouses: list[AffectedWarehouseBlock]
    open_orders_at_risk: list[AffectedOrderBlock]
    max_hop: int
    traversed_edge_types: list[str]


class RecommendationScoresBlock(BaseModel):
    business_impact_reduction: float
    execution_cost_usd: float
    execution_time_hours: float
    operational_risk: float
    customer_impact_protected: float
    confidence: float
    dependency_readiness: float
    net_benefit: float


class RecommendationBlock(BaseModel):
    rank: int
    action: str
    name: str
    explanation: str
    scores: RecommendationScoresBlock
    applicable: bool


class TimelineEventBlock(BaseModel):
    hour: int
    bucket: str
    title: str
    description: str
    status: str


class TimelineBlock(BaseModel):
    bucket_zero: datetime
    events: list[TimelineEventBlock]
    stockout_deadline_at: datetime | None


class SupplierBlock(BaseModel):
    id: str
    name: str
    country: str
    tier: str
    lead_time_days: int


class ScenarioBlock(BaseModel):
    scenario_type: str
    kind: str
    severity: str
    started_at: datetime
    delay_hours: float
    recovery_hours: float
    description: str | None


class DecisionBriefResponse(BaseModel):
    contract_version: str
    generated_at: datetime
    headline: str
    supplier: SupplierBlock
    scenario: ScenarioBlock
    propagation: PropagationBlock
    business_impact: BusinessImpactBlock
    confidence: ConfidenceBlock
    recommendations: list[RecommendationBlock]
    timeline: TimelineBlock
    deadline_hours: int
    ranking_formula: str
    failures: list[str] = Field(default_factory=list)


def _to_supplier_data(s: Supplier) -> SupplierData:
    return SupplierData(
        id=s.id,
        name=s.name,
        country=s.country,
        tier=str(s.tier.value) if hasattr(s.tier, "value") else str(s.tier),
        lead_time_days=s.lead_time_days,
    )


def _to_component_data(c: Component) -> ComponentData:
    return ComponentData(
        id=c.id,
        sku=c.sku,
        name=c.name,
        category=c.category,
        unit_of_measure=c.unit_of_measure,
    )


def _to_factory_data(f: Factory) -> FactoryData:
    return FactoryData(
        id=f.id,
        code=f.code,
        name=f.name,
        throughput_per_day=f.throughput_per_day,
    )


def _to_product_data(p: Product) -> ProductData:
    return ProductData(
        id=p.id,
        sku=p.sku,
        name=p.name,
        factory_id=p.factory_id,
        unit_price=float(p.unit_price) if p.unit_price else None,
        margin_pct=0.0,
        lead_time_days=p.lead_time_days,
    )


def _to_customer_data(c: Customer) -> CustomerData:
    return CustomerData(
        id=c.id,
        name=c.name,
        country=c.country,
        tier=c.tier,
        contract_value_annual=float(c.contract_value_annual) if c.contract_value_annual else None,
        late_delivery_penalty_pct=0.0,
    )


def _to_edge_data(e: Edge) -> EdgeData:
    return EdgeData(
        from_type=str(e.from_type.value) if hasattr(e.from_type, "value") else str(e.from_type),
        from_id=e.from_id,
        to_type=str(e.to_type.value) if hasattr(e.to_type, "value") else str(e.to_type),
        to_id=e.to_id,
        edge_type=str(e.edge_type.value) if hasattr(e.edge_type, "value") else str(e.edge_type),
        weight=float(e.weight) if e.weight else None,
    )


def _to_inventory_data(i: Inventory) -> InventoryData:
    last_updated = i.last_updated_at
    if last_updated.tzinfo is None:
        from datetime import UTC
        last_updated = last_updated.replace(tzinfo=UTC)
    return InventoryData(
        warehouse_id=i.warehouse_id,
        component_id=i.component_id,
        quantity=i.quantity,
        safety_stock=i.safety_stock,
        daily_usage=0,
        last_updated_at=last_updated,
    )


def _to_bom_data(b: BillOfMaterials) -> BomData:
    return BomData(
        product_id=b.product_id,
        component_id=b.component_id,
        quantity_per_unit=float(b.quantity_per_unit),
    )


def _to_order_data(o: Order, p: Product) -> OrderData:
    return OrderData(
        id=o.id,
        customer_id=o.customer_id,
        product_id=o.product_id,
        quantity=o.quantity,
        status=str(o.status.value) if hasattr(o.status, "value") else str(o.status),
        order_date=o.order_date,
        requested_delivery_date=o.requested_delivery_date,
        actual_delivery_date=o.actual_delivery_date,
        unit_price=float(p.unit_price) if p.unit_price else None,
    )


@router.post(
    "/briefs/supplier-failure",
    response_model=DecisionBriefResponse,
)
async def supplier_failure_brief(
    body: SupplierFailureRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict:
    require_workspace_access(str(body.workspace_id), auth)

    supplier_row = (
        await db.execute(
            select(Supplier).where(
                Supplier.id == body.supplier_id,
                Supplier.workspace_id == body.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if supplier_row is None:
        raise HTTPException(status_code=404, detail="Supplier not found")

    suppliers = list(
        (await db.execute(select(Supplier).where(Supplier.workspace_id == body.workspace_id))).scalars()
    )
    components = list(
        (await db.execute(select(Component).where(Component.workspace_id == body.workspace_id))).scalars()
    )
    warehouses = list(
        (await db.execute(select(Warehouse).where(Warehouse.workspace_id == body.workspace_id))).scalars()
    )
    factories = list(
        (await db.execute(select(Factory).where(Factory.workspace_id == body.workspace_id))).scalars()
    )
    products = list(
        (await db.execute(select(Product).where(Product.workspace_id == body.workspace_id))).scalars()
    )
    customers = list(
        (await db.execute(select(Customer).where(Customer.workspace_id == body.workspace_id))).scalars()
    )
    edges = list(
        (await db.execute(select(Edge).where(Edge.workspace_id == body.workspace_id))).scalars()
    )
    inventory = list(
        (await db.execute(select(Inventory).where(Inventory.workspace_id == body.workspace_id))).scalars()
    )
    boms = list(
        (await db.execute(select(BillOfMaterials).where(BillOfMaterials.workspace_id == body.workspace_id))).scalars()
    )
    orders_with_products = list(
        (
            await db.execute(
                select(Order, Product)
                .join(Product, Product.id == Order.product_id)
                .where(Order.workspace_id == body.workspace_id)
            )
        ).all()
    )

    snapshot = SupplyChainSnapshot(
        workspace_id=body.workspace_id,
        as_of=datetime.utcnow(),
        suppliers=tuple(_to_supplier_data(s) for s in suppliers),
        components=tuple(_to_component_data(c) for c in components),
        warehouses=tuple(WarehouseData(id=w.id, code=w.code, name=w.name) for w in warehouses),
        factories=tuple(_to_factory_data(f) for f in factories),
        products=tuple(_to_product_data(p) for p in products),
        customers=tuple(_to_customer_data(c) for c in customers),
        edges=tuple(_to_edge_data(e) for e in edges),
        inventory=tuple(_to_inventory_data(i) for i in inventory),
        bom=tuple(_to_bom_data(b) for b in boms),
        orders=tuple(_to_order_data(o, p) for o, p in orders_with_products),
    )

    kind = DisruptionKind.DELAY if body.severity == "delay" else DisruptionKind.FAILURE
    scenario = DisruptionScenario(
        workspace_id=body.workspace_id,
        supplier_id=body.supplier_id,
        kind=kind,
        severity=body.severity,
        started_at=datetime.utcnow(),
        delay_hours=120.0 if kind == DisruptionKind.DELAY else 0.0,
        recovery_hours=48.0 if kind == DisruptionKind.DELAY else 0.0,
    )

    brief = run_morning_brief(snapshot, scenario)

    # INTELLIGENCE VALIDATION PHASE: Dispatch shadow models for comparison
    # This runs in the background and NEVER affects the production response
    scenario_id = f"{body.workspace_id}-{body.supplier_id}-{datetime.utcnow().isoformat()}"
    try:
        import asyncio
        asyncio.create_task(
            dispatch_shadow_models(
                db=db,
                workspace_id=body.workspace_id,
                snapshot=snapshot,
                scenario=scenario,
                brief=brief,
                scenario_id=scenario_id,
            )
        )
    except Exception:  # noqa: S110 - shadow inference is best-effort, never break the wedge
        # Shadow inference failures must never affect the deterministic wedge
        pass

    deadline_hours = 72
    if brief.timeline.stockout_deadline_at:
        delta = brief.timeline.stockout_deadline_at - brief.timeline.bucket_zero
        deadline_hours = max(1, int(delta.total_seconds() / 3600))

    headline = (
        f"{supplier_row.name} {body.severity} - "
        f"{len(brief.propagation.affected_components)} components, "
        f"{len(brief.propagation.affected_products)} products, "
        f"{len(brief.propagation.open_orders_at_risk)} orders at risk"
    )

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": brief.generated_at,
        "headline": headline,
        "supplier": {
            "id": str(supplier_row.id),
            "name": supplier_row.name,
            "country": supplier_row.country,
            "tier": str(supplier_row.tier.value) if hasattr(supplier_row.tier, "value") else str(supplier_row.tier),
            "lead_time_days": supplier_row.lead_time_days,
        },
        "scenario": {
            "scenario_type": brief.scenario.scenario_type().value,
            "kind": brief.scenario.kind.value,
            "severity": brief.scenario.severity,
            "started_at": brief.scenario.started_at,
            "delay_hours": brief.scenario.delay_hours,
            "recovery_hours": brief.scenario.recovery_hours,
            "description": brief.scenario.description,
        },
        "propagation": {
            "source_supplier_id": str(brief.propagation.source_supplier_id),
            "affected_components": [
                {
                    "component_id": str(c.component_id),
                    "sku": c.sku,
                    "name": c.name,
                    "hop": c.hop,
                    "attenuated_exposure": round(c.attenuated_exposure, 6),
                }
                for c in brief.propagation.affected_components
            ],
            "affected_products": [
                {
                    "product_id": str(p.product_id),
                    "sku": p.sku,
                    "name": p.name,
                    "component_id": str(p.component_id),
                    "qty_needed_per_unit": p.qty_needed_per_unit,
                    "hop": p.hop,
                }
                for p in brief.propagation.affected_products
            ],
            "affected_warehouses": [
                {
                    "warehouse_id": str(w.warehouse_id),
                    "component_id": str(w.component_id),
                    "quantity": w.quantity,
                    "safety_stock": w.safety_stock,
                    "daily_usage": w.daily_usage,
                    "coverage_days": None if w.coverage_days == float("inf") else round(w.coverage_days, 4),
                }
                for w in brief.propagation.affected_warehouses
            ],
            "open_orders_at_risk": [
                {
                    "order_id": str(o.order_id),
                    "customer_id": str(o.customer_id),
                    "product_id": str(o.product_id),
                    "quantity": o.quantity,
                    "status": o.status,
                }
                for o in brief.propagation.open_orders_at_risk
            ],
            "max_hop": brief.propagation.max_hop,
            "traversed_edge_types": list(brief.propagation.traversed_edge_types),
        },
        "business_impact": {
            "overall_score": round(brief.business_impact.overall_score, 4),
            "revenue_risk_usd": round(brief.business_impact.revenue_risk_usd, 2),
            "margin_risk_usd": round(brief.business_impact.margin_risk_usd, 2),
            "penalty_exposure_usd": round(brief.business_impact.penalty_exposure_usd, 2),
            "working_capital_impact_usd": round(brief.business_impact.working_capital_impact_usd, 2),
            "customer_impact_score": round(brief.business_impact.customer_impact_score, 4),
            "operational_impact_score": round(brief.business_impact.operational_impact_score, 4),
            "formula": brief.business_impact.formula,
        },
        "confidence": {
            "overall": round(brief.confidence.overall, 4),
            "completeness": round(brief.confidence.completeness, 4),
            "freshness": round(brief.confidence.freshness, 4),
            "agreement": round(brief.confidence.agreement, 4),
            "conflict_density": round(brief.confidence.conflict_density, 4),
            "formula": brief.confidence.formula,
        },
        "recommendations": [
            {
                "rank": r.rank,
                "action": r.action.value,
                "name": r.name,
                "explanation": r.explanation,
                "applicable": r.applicable,
                "scores": {
                    "business_impact_reduction": round(r.scores.business_impact_reduction, 4),
                    "execution_cost_usd": round(r.scores.execution_cost_usd, 2),
                    "execution_time_hours": round(r.scores.execution_time_hours, 4),
                    "operational_risk": round(r.scores.operational_risk, 4),
                    "customer_impact_protected": round(r.scores.customer_impact_protected, 4),
                    "confidence": round(r.scores.confidence, 4),
                    "dependency_readiness": round(r.scores.dependency_readiness, 4),
                    "net_benefit": round(r.scores.net_benefit, 4),
                },
            }
            for r in brief.recommendations.recommendations
        ],
        "timeline": {
            "bucket_zero": brief.timeline.bucket_zero,
            "events": [
                {
                    "hour": e.hours_from_start,
                    "bucket": e.bucket.value,
                    "title": e.title,
                    "description": e.description,
                    "status": e.stockout_status.value,
                }
                for e in brief.timeline.events
            ],
            "stockout_deadline_at": brief.timeline.stockout_deadline_at,
        },
        "deadline_hours": deadline_hours,
        "ranking_formula": brief.recommendations.ranking_formula,
        "failures": list(brief.failures),
    }
