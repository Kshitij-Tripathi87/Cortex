"""Dataset Registry Models — Core data structures for dataset management."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.common.ids import uuid7


class DatasetSize(StrEnum):
    """Predefined dataset sizes."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    CUSTOM = "custom"


class ScenarioType(StrEnum):
    """Types of disruption scenarios."""

    SUPPLIER_FAILURE = "supplier_failure"
    SUPPLIER_DELAY = "supplier_delay"
    DEMAND_SPIKE = "demand_spike"
    FACTORY_OUTAGE = "factory_outage"
    LOGISTICS_DISRUPTION = "logistics_disruption"
    QUALITY_ISSUE = "quality_issue"


class DatasetStatus(StrEnum):
    """Lifecycle status of a dataset."""

    GENERATING = "generating"
    VALIDATING = "validating"
    READY = "ready"
    ARCHIVED = "archived"
    FAILED = "failed"


class SchemaVersion(StrEnum):
    """Supported schema versions."""

    V1 = "1.0"
    V2 = "2.0"  # with ground truth


class LabelCoverage(BaseModel):
    """Summary of label coverage in dataset."""

    total_entities: int = 0
    labeled_entities: int = 0
    coverage_ratio: float = 0.0
    missing_labels: list[str] = Field(default_factory=list)
    scenario_coverage: dict[str, float] = Field(default_factory=dict)


class ScenarioMetadata(BaseModel):
    """Metadata for a single disruption scenario."""

    scenario_id: str
    scenario_type: ScenarioType
    severity: str
    supplier_name: str
    delay_hours: float
    recovery_hours: float
    affected_counts: dict[str, int] = Field(default_factory=dict)
    has_ground_truth: bool = True
    generation_params: dict[str, Any] = Field(default_factory=dict)


class DatasetStatistics(BaseModel):
    """Statistical summary of dataset contents."""

    total_entities: int = 0
    suppliers: int = 0
    components: int = 0
    warehouses: int = 0
    factories: int = 0
    products: int = 0
    customers: int = 0
    edges: int = 0
    inventory_records: int = 0
    bom_records: int = 0
    orders: int = 0
    disruption_scenarios: int = 0
    avg_supplier_degree: float = 0.0
    avg_component_degree: float = 0.0
    supplier_tier_distribution: dict[str, int] = Field(default_factory=dict)
    component_category_distribution: dict[str, int] = Field(default_factory=dict)
    inventory_by_tier: dict[str, int] = Field(default_factory=dict)
    order_status_distribution: dict[str, int] = Field(default_factory=dict)
    scenario_type_distribution: dict[str, int] = Field(default_factory=dict)


class DatasetChecksum(BaseModel):
    """Checksums for dataset integrity verification."""

    files: dict[str, str] = Field(default_factory=dict)  # filename -> sha256
    ground_truth: str | None = None
    combined: str | None = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DatasetMetadata(BaseModel):
    """Complete metadata for a registered dataset."""

    dataset_id: UUID = Field(default_factory=uuid7)
    version: int = 1
    name: str
    description: str = ""
    size: DatasetSize = DatasetSize.CUSTOM
    seed: int
    schema_version: SchemaVersion = SchemaVersion.V2
    status: DatasetStatus = DatasetStatus.GENERATING

    # Generation params
    generation_params: dict[str, Any] = Field(default_factory=dict)
    generation_duration_seconds: float | None = None
    generated_by: str | None = None
    generator_version: str = "1.0"

    # Content
    statistics: DatasetStatistics = Field(default_factory=DatasetStatistics)
    scenarios: list[ScenarioMetadata] = Field(default_factory=list)
    label_coverage: LabelCoverage = Field(default_factory=LabelCoverage)

    # Integrity
    checksums: DatasetChecksum = Field(default_factory=DatasetChecksum)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_validated_at: datetime | None = None
    archived_at: datetime | None = None

    # Storage
    storage_path: str | None = None
    storage_size_bytes: int = 0

    # Lineage
    parent_dataset_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, v: int) -> int:
        if v < 0:
            raise ValueError("seed must be non-negative")
        return v

    def bump_version(self) -> DatasetMetadata:
        """Create a new version of this dataset."""
        self.version += 1
        self.updated_at = datetime.now(UTC)
        return self


class DatasetRegistrationRequest(BaseModel):
    """Request to register a new dataset."""

    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    size: DatasetSize = DatasetSize.CUSTOM
    seed: int
    schema_version: SchemaVersion = SchemaVersion.V2
    generation_params: dict[str, Any] = Field(default_factory=dict)
    parent_dataset_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)


class DatasetUpdateRequest(BaseModel):
    """Request to update dataset metadata."""

    name: str | None = None
    description: str | None = None
    status: DatasetStatus | None = None
    tags: list[str] | None = None


class DatasetListResponse(BaseModel):
    """Paginated list of datasets."""

    items: list[DatasetMetadata]
    total: int
    page: int
    page_size: int
    has_more: bool


class DatasetExportRequest(BaseModel):
    """Request to export a dataset."""

    dataset_id: UUID
    format: str = "json"  # json, csv, parquet, arrow
    include_ground_truth: bool = True
    include_statistics: bool = True


class DatasetSearchFilters(BaseModel):
    """Filters for searching datasets."""

    name: str | None = None
    size: DatasetSize | None = None
    status: DatasetStatus | None = None
    seed: int | None = None
    schema_version: SchemaVersion | None = None
    tags: list[str] = Field(default_factory=list)
    created_after: datetime | None = None
    created_before: datetime | None = None


__all__ = [
    "DatasetSize",
    "ScenarioType",
    "DatasetStatus",
    "SchemaVersion",
    "LabelCoverage",
    "ScenarioMetadata",
    "DatasetStatistics",
    "DatasetChecksum",
    "DatasetMetadata",
    "DatasetRegistrationRequest",
    "DatasetUpdateRequest",
    "DatasetListResponse",
    "DatasetExportRequest",
    "DatasetSearchFilters",
]
