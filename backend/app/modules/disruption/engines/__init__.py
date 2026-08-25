"""Disruption engines — pure-functional computation for the Morning Brief.

Each engine takes typed input data and returns typed output dataclasses
(see :mod:`app.modules.disruption.engines.types`). No database access happens
in the engines themselves; the orchestrator (``brief.py``) loads graph data
from repositories and feeds it to the engines. This keeps every engine
trivially unit-testable without DB and fully replay-deterministic (ADR-0003).

Pipeline::

    SupplyChainSnapshot + DisruptionScenario
        └─ propagation.propagate(...)        -> PropagationResult   (BFS + BOM + inventory)
           ├─ impact.compute_business_impact(...) -> BusinessImpactScore (6 components)
           ├─ confidence.compute_confidence(...)   -> ConfidenceScores     (5 sub-scores)
           ├─ recommendations.recommend(...)        -> RecommendationSet    (7 dims, net_benefit rank)
           └─ timeline.build_timeline(...)          -> Timeline             (0/12/24/48/72h)
        └─ brief.run_morning_brief(...)       -> MorningBrief        (persisted to ImpactReport)

Public surface:

    from app.modules.disruption.engines import (
        PropagationResult,
        BusinessImpactScore,
        ConfidenceScores,
        RecommendationSet,
        Timeline,
        MorningBrief,
    )
"""

from __future__ import annotations

from app.modules.disruption.engines.brief import run_morning_brief
from app.modules.disruption.engines.confidence import compute_confidence
from app.modules.disruption.engines.impact import compute_business_impact
from app.modules.disruption.engines.propagation import propagate
from app.modules.disruption.engines.recommendations import recommend
from app.modules.disruption.engines.timeline import build_timeline
from app.modules.disruption.engines.types import (
    AffectedComponent,
    AffectedOrder,
    AffectedProduct,
    AffectedWarehouse,
    BomData,
    BriefScenarioType,
    BusinessImpactScore,
    ComponentData,
    ConfidenceComponent,
    ConfidenceScores,
    CustomerData,
    DisruptionKind,
    DisruptionScenario,
    EdgeData,
    FactoryData,
    ImpactDomain,
    InventoryData,
    MorningBrief,
    OrderData,
    ProductData,
    PropagationResult,
    RecommendAction,
    Recommendation,
    RecommendationScores,
    RecommendationSet,
    StockoutStatus,
    SupplierData,
    SupplyChainSnapshot,
    Timeline,
    TimelineBucket,
    TimelineEvent,
    WarehouseData,
)

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
    "build_timeline",
    "compute_business_impact",
    "compute_confidence",
    "propagate",
    "recommend",
    "run_morning_brief",
]
