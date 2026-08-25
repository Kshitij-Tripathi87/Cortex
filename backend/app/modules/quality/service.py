"""Data Quality Framework — automated quality scoring for every uploaded dataset.

Computes six standard quality dimensions per DAMA/DQM:
1. Completeness — non-null ratio per required field
2. Consistency — cross-field and cross-table agreement
3. Uniqueness — duplicate detection
4. Timeliness — data freshness relative to business SLA
5. Validity — conformance to type, format, and domain constraints
6. Integrity — referential and foreign key integrity

Each dataset receives an Overall Data Trust Score (0.0–1.0) that feeds
into readiness and downstream operational reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.enums import ColumnInferredType
from app.modules.sources.models import SourceColumnProfile, SourceFile


@dataclass(frozen=True)
class QualityDimensionScore:
    """Score for a single quality dimension."""

    name: str
    score: float  # 0.0–1.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataQualityReport:
    """Complete data quality assessment for a source file."""

    file_id: str
    workspace_id: str
    overall_score: float  # weighted average
    dimensions: list[QualityDimensionScore]
    recommendations: list[str] = field(default_factory=list)
    passed_threshold: bool = True


# Weights per dimension (configurable via settings in Phase 3+)
DIMENSION_WEIGHTS = {
    "completeness": 0.20,
    "consistency": 0.20,
    "uniqueness": 0.15,
    "timeliness": 0.10,
    "validity": 0.20,
    "integrity": 0.15,
}


def compute_quality_report(
    file: SourceFile,
    profiles: list[SourceColumnProfile],
) -> DataQualityReport:
    """Compute full quality report for a profiled source file."""
    dimensions = []

    # 1. Completeness — non-null ratio weighted by column importance
    completeness = _compute_completeness(profiles)
    dimensions.append(QualityDimensionScore("completeness", completeness))

    # 2. Consistency — cross-field agreement (Phase 2: intra-file only)
    consistency = _compute_consistency(profiles)
    dimensions.append(QualityDimensionScore("consistency", consistency))

    # 3. Uniqueness — duplicate row detection
    uniqueness = _compute_uniqueness(file, profiles)
    dimensions.append(QualityDimensionScore("uniqueness", uniqueness))

    # 4. Timeliness — data freshness relative to business SLA
    timeliness = _compute_timeliness(file, profiles)
    dimensions.append(QualityDimensionScore("timeliness", timeliness))

    # 5. Validity — conformance to declared types and formats
    validity = _compute_validity(profiles)
    dimensions.append(QualityDimensionScore("validity", validity))

    # 6. Integrity — referential integrity (intra-file heuristics from profiles)
    integrity = _compute_integrity(file, profiles)
    dimensions.append(QualityDimensionScore("integrity", integrity))

    # Weighted overall score
    overall = sum(DIMENSION_WEIGHTS[d.name] * d.score for d in dimensions)

    # Threshold from config (default 0.75)
    passed = overall >= 0.75

    recommendations = _generate_recommendations(dimensions)

    return DataQualityReport(
        file_id=file.file_id,
        workspace_id=file.workspace_id,
        overall_score=round(overall, 4),
        dimensions=dimensions,
        recommendations=recommendations,
        passed_threshold=passed,
    )


def _compute_completeness(profiles: list[SourceColumnProfile]) -> float:
    """Weighted average of (1 - null_ratio) across columns."""
    if not profiles:
        return 1.0
    # Weight by inverse null ratio (columns with more data matter more)
    total_weight = 0.0
    weighted_sum = 0.0
    for p in profiles:
        weight = 1.0 - p.null_ratio
        total_weight += weight
        weighted_sum += weight * (1.0 - p.null_ratio)
    return weighted_sum / total_weight if total_weight > 0 else 1.0


def _compute_consistency(profiles: list[SourceColumnProfile]) -> float:
    """Intra-file cross-field consistency.

    Phase 2: checks for obvious contradictions (e.g., qty < 0, date after now).
    Phase 3+: cross-file, cross-table, business rule consistency.
    """
    # Placeholder: full implementation needs row-level data
    # For now, return high score if no obvious type mismatches
    mismatch_count = sum(1 for p in profiles if p.inferred_type == ColumnInferredType.MIXED.value)
    return max(0.5, 1.0 - (mismatch_count / max(len(profiles), 1)) * 0.5)


def _compute_uniqueness(file: SourceFile, profiles: list[SourceColumnProfile]) -> float:
    """Uniqueness score based on distinct counts vs row count.

    Phase 2: uses column-level distinct counts. Phase 3+: row-level dedup.
    """
    if file.row_count is None or file.row_count == 0:
        return 1.0

    # Find columns that should be unique (e.g., IDs, SKUs)
    # For Phase 2, heuristic: columns with high distinct ratio
    candidate_cols = [p for p in profiles if p.distinct_count / max(file.row_count, 1) > 0.95]
    if not candidate_cols:
        return 1.0  # no uniqueness constraints detected

    # Score based on how close distinct count is to row count
    avg_ratio = sum(p.distinct_count / file.row_count for p in candidate_cols) / len(candidate_cols)
    return min(1.0, avg_ratio)


def _compute_timeliness(
    file: SourceFile,
    profiles: list[SourceColumnProfile],
    *,
    freshness_window_hours: float = 24.0,
) -> float:
    """Data freshness relative to business SLA.

    Two signals combined:
    1. Snapshot recency — age of file.created_at relative to now, scored against
       a freshness window (default 24h). Score decays linearly from 1.0 → 0.5 over
       2x the window, then floors at 0.5.
    2. Business-date staleness — scan date/datetime columns for sample values,
       parse the most recent business timestamp, and penalize if older than the
       freshness window. This detects stale source data even in a fresh upload.

    Phase 3+ will replace heuristics with business-date column configuration.
    """
    from datetime import datetime

    snapshot_score = 1.0
    if file.created_at is not None:
        now = datetime.now(UTC)
        if file.created_at.tzinfo is None:
            created = file.created_at.replace(tzinfo=UTC)
        else:
            created = file.created_at
        age_hours = (now - created).total_seconds() / 3600.0
        if age_hours <= freshness_window_hours:
            snapshot_score = 1.0
        elif age_hours <= freshness_window_hours * 2:
            # Linear decay 1.0 → 0.5 across [window, 2*window]
            t = (age_hours - freshness_window_hours) / freshness_window_hours
            snapshot_score = 1.0 - 0.5 * t
        else:
            snapshot_score = 0.5

    business_score = 1.0
    date_like = {
        ColumnInferredType.DATE.value,
        ColumnInferredType.DATETIME.value,
    }
    parsed_dates: list[datetime] = []
    for p in profiles:
        if p.inferred_type not in date_like:
            continue
        for sample in p.sample_values:
            parsed = _try_parse_datetime(sample)
            if parsed is not None:
                parsed_dates.append(parsed)
    if parsed_dates:
        most_recent = max(parsed_dates)
        if most_recent.tzinfo is None:
            most_recent = most_recent.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        business_age_hours = (now - most_recent).total_seconds() / 3600.0
        # Allow future dates (promised deliveries) to count as fresh
        if business_age_hours <= 0 or business_age_hours <= freshness_window_hours:
            business_score = 1.0
        elif business_age_hours <= freshness_window_hours * 7:
            # One-week decay window (business data is typically weekly-cadence)
            t = (business_age_hours - freshness_window_hours) / (freshness_window_hours * 6)
            business_score = 1.0 - 0.5 * t
        else:
            business_score = 0.5

    # Weighted: business-date signal matters more when available
    return round(0.4 * snapshot_score + 0.6 * business_score, 4)


_ISO_DT_PATTERNS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
)


def _try_parse_datetime(value: str) -> datetime | None:
    """Best-effort parse of a date-like sample value. Returns None on failure."""
    v = value.strip()
    if not v:
        return None
    from datetime import datetime

    for fmt in _ISO_DT_PATTERNS:
        try:
            parsed = datetime.strptime(v, fmt)
            if fmt.endswith("Z"):
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            continue
    return None


def _compute_validity(profiles: list[SourceColumnProfile]) -> float:
    """Conformance to type, format, and domain constraints."""
    if not profiles:
        return 1.0

    valid_count = 0
    for p in profiles:
        if p.inferred_type != ColumnInferredType.MIXED.value and p.null_ratio < 1.0:
            valid_count += 1
    return valid_count / len(profiles)


def _compute_integrity(
    file: SourceFile,
    profiles: list[SourceColumnProfile],
) -> float:
    """Referential integrity — intra-file heuristics derived from column profiles.

    Signals (no row-level access available in Phase 2):
    1. Required-reference presence — columns ending in `_id`, or named `id`,
       `*_number`, `po_number`, etc. should have a low null_ratio. Missing
       references degrade integrity.
    2. Identity uniqueness — ID-like columns should have distinct_count close
       to row_count; duplicates indicate identity corruption.
    3. Type consistency for keys — ID columns inferred as MIXED type surface
       FK type-mismatch risk.

    Phase 3+ will add true cross-file FK validation against canonical entities.
    """
    if not profiles:
        return 1.0

    id_pattern_endings = ("_id", "_number", "_code")
    id_pattern_exact = {"id", "sku", "po_number", "so_number", "shipment_id", "lot_number"}

    total_rows = file.row_count or 0
    penalties: list[float] = []

    for p in profiles:
        name = (p.column_name or "").strip().lower()
        is_id_like = name in id_pattern_exact or any(
            name.endswith(end) for end in id_pattern_endings
        )
        if not is_id_like:
            continue

        # 1. Presence — null ratio penalizes integrity
        if p.null_ratio > 0:
            penalties.append(min(0.5, p.null_ratio * 0.5))

        # 2. Uniqueness — distinct_count < row_count indicates duplicate IDs
        if total_rows > 0 and p.distinct_count > 0:
            uniqueness = p.distinct_count / total_rows
            if uniqueness < 1.0:
                penalties.append((1.0 - uniqueness) * 0.3)

        # 3. Type consistency — MIXED inferred type on an ID column is a red flag
        if p.inferred_type == ColumnInferredType.MIXED.value:
            penalties.append(0.2)

    if not penalties:
        return 1.0

    # Aggregate: each penalty reduces integrity, floored at 0.0
    score = 1.0
    for pen in penalties:
        score -= pen
    return max(0.0, round(score, 4))


def _generate_recommendations(dimensions: list[QualityDimensionScore]) -> list[str]:
    """Generate actionable recommendations from dimension scores."""
    recs = []
    for d in dimensions:
        if d.score < 0.7:
            if d.name == "completeness":
                recs.append("High null ratio detected — review required fields in source system")
            elif d.name == "validity":
                recs.append("Type/format mismatches found — standardize source data formats")
            elif d.name == "uniqueness":
                recs.append("Potential duplicates detected — review source deduplication logic")
            elif d.name == "consistency":
                recs.append("Cross-field inconsistencies — validate business rules at source")
    return recs
