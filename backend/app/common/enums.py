"""Snimalized enums for the evidence pipeline (Phase 2 scope only)."""

from __future__ import annotations

from enum import StrEnum


class SourceBatchStatus(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    VALIDATED = "validated"
    REJECTED = "rejected"
    PROFILING = "profiling"
    PROFILED = "profiled"
    FAILED = "failed"


class SourceSystemHint(StrEnum):
    ERP = "erp"
    WMS = "wms"
    TMS = "tms"
    OMS = "oms"
    MES = "mes"
    SCM_PLANNING = "scm_planning"
    SPREADSHEET = "spreadsheet"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class ColumnInferredType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    STRING = "string"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    EMPTY = "empty"
    MIXED = "mixed"


class ClaimState(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    CONFLICTED = "conflicted"


class ConflictSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    MAJOR = "major"
    CRITICAL = "critical"


class ConflictResolutionAction(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPPRESSED = "suppressed"
    ESCALATED = "escalated"


class ReadinessState(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"
    READY_WITH_ASSUMPTIONS = "ready_with_assumptions"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ─────────────────────────────────────────────────────────────────────────────
# MVP wedge enums (ADR-0003 — Deterministic MVP, cortex-mvp-execution-plan §1.2)
# ─────────────────────────────────────────────────────────────────────────────


class MvpDatasetType(StrEnum):
    """Permitted values for `dataset_type` in the CSV ingestion endpoint."""

    SUPPLIERS = "suppliers"
    COMPONENTS = "components"
    WAREHOUSES = "warehouses"
    FACTORIES = "factories"
    PRODUCTS = "products"
    CUSTOMERS = "customers"
    EDGES = "edges"
    INVENTORY = "inventory"
    BOM = "bom"
    ORDERS = "orders"


class SupplierStatus(StrEnum):
    ACTIVE = "active"
    DISRUPTED = "disrupted"
    DISABLED = "disabled"


class SupplierTier(StrEnum):
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class EdgeType(StrEnum):
    """Supply-chain relationship directions per MVP §3.2 propagation algorithm.

    Edge types that BFS walks: supplier--supplies-->component,
    component--stored_in-->warehouse, factory--consumes-->component,
    factory--makes-->product, customer--orders-->product.
    """

    SUPPLIES = "supplies"
    STORED_IN = "stored_in"
    CONSUMES = "consumes"
    MAKES = "makes"
    SHIPS_FROM = "ships_from"
    ORDERS = "orders"


class NodeType(StrEnum):
    """Polymorphic discriminator for the `from_type`/`to_type` on `edges`."""

    SUPPLIER = "supplier"
    COMPONENT = "component"
    WAREHOUSE = "warehouse"
    FACTORY = "factory"
    PRODUCT = "product"
    CUSTOMER = "customer"


class DisruptionStatus(StrEnum):
    """Lifecyle status for a disruption event (ADR-0007 default)."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class DisruptionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    MAJOR = "major"
    CRITICAL = "critical"


class DisruptionEventType(StrEnum):
    """The type of upstream failure that triggered a disruption."""

    SUPPLIER_FAILURE = "supplier_failure"
    LOGISTICS_DISRUPTION = "logistics_disruption"
    QUALITY_RECALL = "quality_recall"
    GEOPOLITICAL = "geopolitical"
    NATURAL_DISASTER = "natural_disaster"
    LABOR_DISPUTE = "labor_dispute"
    OTHER = "other"


class ImpactStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionStatus(StrEnum):
    RECEIVED = "received"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class DecisionOutcome(StrEnum):
    ACCEPTED_RECOMMENDATION = "accepted_recommendation"
    REJECTED_RECOMMENDATION = "rejected_recommendation"
    MODIFIED_RECOMMENDATION = "modified_recommendation"
    DEFERRED = "deferred"


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    ANALYST = "analyst"
    VIEWER = "viewer"


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_PRODUCTION = "in_production"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    DELAYED = "delayed"
