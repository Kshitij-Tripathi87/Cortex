"""Model registry.

Importing this package imports every ORM model, which registers every table on
``Base.metadata``. Alembic imports it for exactly that reason; a model that is
not imported here does not exist as far as migrations are concerned.
"""

from app.models.equipment import Equipment
from app.models.ingestion import IngestionBatch, IngestionRow
from app.models.milestone import Milestone
from app.models.milestone_plan_version import MilestonePlanVersion
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier import Supplier
from app.models.supplier_commitment_version import SupplierCommitmentVersion
from app.models.workspace import Workspace

__all__ = [
    "Equipment",
    "IngestionBatch",
    "IngestionRow",
    "Milestone",
    "MilestonePlanVersion",
    "Project",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "Supplier",
    "SupplierCommitmentVersion",
    "Workspace",
]
