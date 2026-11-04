"""Deterministic manufacturing material-planning domain services.

The package is deliberately ORM-free. Persistence adapters must assemble
snapshot-bound inputs from the canonical workspace state before calling it.
"""

from app.modules.planning.bom import explode_production_order
from app.modules.planning.inventory import project_inventory
from app.modules.planning.models import (
    BOMLine,
    BOMRevision,
    DemandContribution,
    ExplicitMaterialRequirement,
    InventoryBalanceInput,
    InventoryProjection,
    ItemType,
    MaterialReceipt,
    ProductionOrder,
    ProjectionStatus,
    QuantityBasis,
    UOMConverter,
)

__all__ = [
    "BOMLine",
    "BOMRevision",
    "DemandContribution",
    "ExplicitMaterialRequirement",
    "InventoryBalanceInput",
    "InventoryProjection",
    "ItemType",
    "MaterialReceipt",
    "ProductionOrder",
    "ProjectionStatus",
    "QuantityBasis",
    "UOMConverter",
    "explode_production_order",
    "project_inventory",
]
