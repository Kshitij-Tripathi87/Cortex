"""Dataset Registry Module — Versioned, validated, exportable datasets."""

from app.modules.datasets.exports import DatasetExporter, export_dataset
from app.modules.datasets.models import (
    DatasetChecksum,
    DatasetExportRequest,
    DatasetListResponse,
    DatasetMetadata,
    DatasetRegistrationRequest,
    DatasetSearchFilters,
    DatasetSize,
    DatasetStatistics,
    DatasetStatus,
    DatasetUpdateRequest,
    LabelCoverage,
    ScenarioMetadata,
    ScenarioType,
    SchemaVersion,
)
from app.modules.datasets.registry import DatasetRecord, DatasetRegistry
from app.modules.datasets.statistics import StatisticsComputer, compute_statistics
from app.modules.datasets.validation import (
    DatasetValidator,
    ValidationIssue,
    ValidationResult,
    compute_checksums,
    compute_combined_checksum,
    validate_dataset,
)

__all__ = [
    # Models
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
    # Registry
    "DatasetRecord",
    "DatasetRegistry",
    # Validation
    "ValidationIssue",
    "ValidationResult",
    "DatasetValidator",
    "validate_dataset",
    "compute_checksums",
    "compute_combined_checksum",
    # Statistics
    "StatisticsComputer",
    "compute_statistics",
    # Exports
    "DatasetExporter",
    "export_dataset",
]
