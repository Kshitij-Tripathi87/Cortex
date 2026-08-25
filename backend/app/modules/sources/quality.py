"""Data Quality Framework — automated quality scoring for uploaded datasets.

Six dimensions per docs/22-observability-model.md:
- Completeness — non-null ratio across required columns
- Consistency — value agreement across sources
- Uniqueness — duplicate rate
- Timeliness — data freshness vs expected update cadence
- Validity — conformance to expected formats/ranges
- Integrity — referential integrity across related entities

Output: Overall Data Trust Score (0.0–1.0)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.sources.models import SourceColumnProfile, SourceFile


@dataclass(frozen=True)
class QualityDimension:
    """Single quality dimension score."""

    name: str
    score: float  # 0.0–1.0
    details: dict[str, Any]


@dataclass(frozen=True)
class DataQualityReport:
    """Full data quality report for a source file."""

    file_id: str
    workspace_id: str
    dimensions: list[QualityDimension]
    overall_score: float
    recommendations: list[str]


def compute_quality(
    file: SourceFile,
    profiles: list[SourceColumnProfile],
    required_columns: list[str] | None = None,
) -> DataQualityReport:
    """Compute data quality scores for a profiled file.

    Phase 2: basic heuristics.
    Phase 3+: ML-assisted anomaly detection.
    """
    dimensions: list[QualityDimension] = []
    recommendations: list[str] = []

    # 1. Completeness — non-null ratio
    if profiles:
        avg_null_ratio = sum(p.null_ratio for p in profiles) / len(profiles)
        completeness = 1.0 - avg_null_ratio
        dimensions.append(
            QualityDimension(
                name="completeness",
                score=round(completeness, 4),
                details={"avg_null_ratio": round(avg_null_ratio, 4)},
            )
        )
        if completeness < 0.8:
            recommendations.append("Increase data completeness — too many missing values")

    # 2. Consistency — type homogeneity
    mixed_types = sum(1 for p in profiles if p.inferred_type == "mixed")
    consistency = 1.0 - (mixed_types / len(profiles)) if profiles else 1.0
    dimensions.append(
        QualityDimension(
            name="consistency",
            score=round(consistency, 4),
            details={"mixed_type_columns": mixed_types},
        )
    )
    if consistency < 0.9:
        recommendations.append("Resolve mixed-type columns for better consistency")

    # 3. Uniqueness — duplicate detection (simplified: distinct count vs row count)
    if file.row_count and profiles:
        avg_distinct_ratio = sum(
            p.distinct_count / file.row_count if file.row_count > 0 else 1.0 for p in profiles
        ) / len(profiles)
        # High distinct ratio in ID columns is good; in categorical columns, less so
        # Simplified: assume >0.9 is good
        uniqueness = min(avg_distinct_ratio / 0.9, 1.0)
        dimensions.append(
            QualityDimension(
                name="uniqueness",
                score=round(uniqueness, 4),
                details={"avg_distinct_ratio": round(avg_distinct_ratio, 4)},
            )
        )
    else:
        uniqueness = 1.0
        dimensions.append(QualityDimension(name="uniqueness", score=1.0, details={}))

    # 4. Timeliness — N/A in Phase 2 (no temporal metadata yet)
    dimensions.append(
        QualityDimension(name="timeliness", score=1.0, details={"note": "Not evaluated in Phase 2"})
    )

    # 5. Validity — format conformance (simplified: encoding success + type inference confidence)
    validity = 1.0 if file.encoding else 0.95
    dimensions.append(
        QualityDimension(
            name="validity",
            score=validity,
            details={"encoding_detected": file.encoding is not None},
        )
    )

    # 6. Integrity — referential checks (N/A in Phase 2 without ontology graph)
    dimensions.append(
        QualityDimension(name="integrity", score=1.0, details={"note": "Not evaluated in Phase 2"})
    )

    # Overall score — weighted average
    weights = {
        "completeness": 0.25,
        "consistency": 0.20,
        "uniqueness": 0.15,
        "timeliness": 0.10,
        "validity": 0.20,
        "integrity": 0.10,
    }
    overall_score = sum(d.score * weights.get(d.name, 0.1) for d in dimensions) / sum(
        weights.values()
    )

    return DataQualityReport(
        file_id=file.file_id,
        workspace_id=file.workspace_id,
        dimensions=dimensions,
        overall_score=round(overall_score, 4),
        recommendations=recommendations,
    )
