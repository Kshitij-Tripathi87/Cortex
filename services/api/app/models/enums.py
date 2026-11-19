"""Controlled vocabularies of the domain.

Plain string enumerations with no dependency on SQLAlchemy or FastAPI, so
models, schemas and the pure ingestion modules can all share them. The
allowed values are part of the frozen contract (docs/architecture/domain-model.md).
"""

from enum import StrEnum


class WorkspaceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class ProjectStatus(StrEnum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SupplierStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EquipmentCategory(StrEnum):
    TRANSFORMER = "TRANSFORMER"
    SWITCHGEAR = "SWITCHGEAR"
    GENERATOR = "GENERATOR"
    UPS = "UPS"
    COOLING = "COOLING"
    OTHER = "OTHER"


class Criticality(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ProcurementStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    RFQ = "RFQ"
    QUOTED = "QUOTED"
    ORDERED = "ORDERED"
    IN_PRODUCTION = "IN_PRODUCTION"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    CANCELLED = "CANCELLED"


class PurchaseOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class MilestoneType(StrEnum):
    """Milestone types, declared in their lifecycle order."""

    PO_ACKNOWLEDGEMENT = "PO_ACKNOWLEDGEMENT"
    DRAWING_SUBMISSION = "DRAWING_SUBMISSION"
    DRAWING_APPROVAL = "DRAWING_APPROVAL"
    MANUFACTURING_START = "MANUFACTURING_START"
    FACTORY_ACCEPTANCE_TEST = "FACTORY_ACCEPTANCE_TEST"
    DISPATCH = "DISPATCH"
    DELIVERY = "DELIVERY"
    INSTALLATION = "INSTALLATION"


class MilestoneStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SourceFormat(StrEnum):
    CSV = "CSV"
    XLSX = "XLSX"


class IngestionEntityType(StrEnum):
    """What a source file describes."""

    PROJECT = "project"
    SUPPLIER = "supplier"
    EQUIPMENT = "equipment"
    PURCHASE_ORDER = "purchase_order"
    PURCHASE_ORDER_ITEM = "purchase_order_item"
    MILESTONE = "milestone"
    SUPPLIER_COMMITMENT = "supplier_commitment"


class CanonicalEntityType(StrEnum):
    """The kinds of canonical record a source row can result in."""

    PROJECT = "project"
    SUPPLIER = "supplier"
    EQUIPMENT = "equipment"
    PURCHASE_ORDER = "purchase_order"
    PURCHASE_ORDER_ITEM = "purchase_order_item"
    MILESTONE = "milestone"
    SUPPLIER_COMMITMENT_VERSION = "supplier_commitment_version"


class BatchStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PREVIEWED = "PREVIEWED"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class RowStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    COMMITTED = "COMMITTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class PlannedAction(StrEnum):
    """What a commit would do with a row, as assessed at preview."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    NO_CHANGE = "NO_CHANGE"


class RowOutcome(StrEnum):
    """What the commit did with a row."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    DUPLICATE_ROW = "DUPLICATE_ROW"
    ROLLED_BACK = "ROLLED_BACK"
    REJECTED = "REJECTED"


class QualityDimension(StrEnum):
    COMPLETENESS = "COMPLETENESS"
    VALIDITY = "VALIDITY"
    CONSISTENCY = "CONSISTENCY"
    UNIQUENESS = "UNIQUENESS"
    REFERENTIAL_INTEGRITY = "REFERENTIAL_INTEGRITY"
