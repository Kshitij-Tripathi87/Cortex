"""Feature Store Models — Feature definitions and metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class FeatureType(StrEnum):
    """Types of features."""

    NUMERICAL = "numerical"
    CATEGORICAL = "categorical"
    EMBEDDING = "embedding"
    TEXT = "text"
    TEMPORAL = "temporal"
    GRAPH_STRUCTURAL = "graph_structural"


class FeatureStatus(StrEnum):
    """Feature lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class FeatureGroup(BaseModel):
    """A group of related features."""

    group_id: UUID = Field(default_factory=uuid7)
    name: str
    description: str = ""
    feature_names: list[str] = []
    version: str = "1.0.0"
    created_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = {}

    def add_feature(self, feature_name: str) -> None:
        if feature_name not in self.feature_names:
            self.feature_names.append(feature_name)

    def remove_feature(self, feature_name: str) -> None:
        if feature_name in self.feature_names:
            self.feature_names.remove(feature_name)


class FeatureDefinition(BaseModel):
    """Definition of a single feature."""

    feature_id: UUID = Field(default_factory=uuid7)
    name: str
    feature_type: FeatureType
    description: str = ""
    group_id: UUID | None = None

    # Data specification
    dtype: str = "float32"  # float32, float64, int32, int64, string, bool
    shape: tuple[int, ...] = ()  # scalar=(), vector=(dim,), matrix=(dim1, dim2)

    # Statistics
    min_value: float | None = None
    max_value: float | None = None
    mean: float | None = None
    std: float | None = None
    null_ratio: float = 0.0

    # Validation
    min_allowed: float | None = None
    max_allowed: float | None = None
    allowed_categories: list[str] | None = None

    # Metadata
    source: str = "computed"  # "raw", "computed", "external"
    computation_logic: str = ""  # SQL, Python, SQL expression
    dependencies: list[str] = []  # other feature names this depends on
    tags: list[str] = []

    # Lifecycle
    status: FeatureStatus = FeatureStatus.DRAFT
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    deprecated_at: datetime | None = None

    def validate_value(self, value: Any) -> bool:
        """Validate a value against this feature's constraints."""
        if value is None:
            return self.null_ratio > 0 or self.dtype == "string"  # allow null if nullable

        if self.dtype in ("float32", "float64", "int32", "int64"):
            try:
                val = float(value)
                if self.min_allowed is not None and val < self.min_allowed:
                    return False
                if self.max_allowed is not None and val > self.max_allowed:
                    return False
            except (ValueError, TypeError):
                return False
        elif self.dtype == "categorical" and self.allowed_categories:  # noqa: SIM102
            if str(value) not in self.allowed_categories:
                return False

        return True


class FeatureVector(BaseModel):
    """A feature vector for a single entity."""

    entity_id: str
    entity_type: str  # "supplier", "component", "warehouse", etc.
    workspace_id: str
    snapshot_version: int
    features: dict[str, Any] = {}
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = {}


class FeatureSnapshot(BaseModel):
    """A versioned snapshot of features for a workspace."""

    snapshot_id: UUID = Field(default_factory=uuid7)
    workspace_id: str
    version: int
    snapshot_hash: str
    feature_vectors: list[FeatureVector] = []
    feature_definitions: dict[str, dict] = {}  # feature_name -> definition
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = {}

    def get_vector(self, entity_id: str, entity_type: str) -> dict | None:
        for fv in self.feature_vectors:
            if fv.entity_id == entity_id and fv.entity_type == entity_type:
                return fv.features
        return None


class FeatureStatistics(BaseModel):
    """Statistics for a feature across a dataset."""

    feature_name: str
    count: int = 0
    null_count: int = 0
    null_ratio: float = 0.0

    # For numerical
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    percentiles: dict[str, float] = {}  # p25, p50, p75, p90, p99

    # For categorical
    categories: dict[str, int] = {}  # category -> count
    unique_count: int | None = None

    # Quality
    missing_ratio: float = 0.0
    outlier_count: int = 0
    outlier_ratio: float = 0.0


class FeatureLineage(BaseModel):
    """Tracks feature derivation lineage."""

    feature_name: str
    source_features: list[str] = []  # direct dependencies
    transformation: str = ""  # description of transformation
    transformation_code: str = ""  # SQL, Python, etc.
    parameters: dict = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None


__all__ = [
    "FeatureType",
    "FeatureStatus",
    "FeatureGroup",
    "FeatureDefinition",
    "FeatureVector",
    "FeatureSnapshot",
    "FeatureStatistics",
    "FeatureLineage",
]
