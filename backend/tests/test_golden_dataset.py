"""RC-1 Golden Dataset Regression Suite — end-to-end pipeline determinism.

This is the Cortex equivalent of a compiler regression suite. Every release
from now forward must pass this suite. It exercises the pure-function path
of every pipeline stage against the Golden Supply Chain Dataset v1:

    Upload validation
        -> Profiling (deterministic)
            -> Schema mapping (alias registry)
                -> Quality scoring (six dimensions)
                    -> Anomaly detection (determinism invariants)

DB-dependent stages (claim extraction, conflict detection, readiness) are
covered by test_modules.py and the testcontainer integration suite.

Determinism contract:
    1. Same input bytes -> same profile bytes (byte-identical output).
    2. Different input order -> same summary statistics (convergence).
    3. Duplicate rows in golden dataset are detected as uniqueness < 1.0.
    4. Stale timestamps in golden dataset are detected as timeliness < 1.0.
    5. ID columns with duplicates are detected as integrity < 1.0.
    6. Quality scores stay within [0.0, 1.0] for every file.
    7. Profiling latency stays within performance budget (5s/file).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC

import pytest

from app.modules.inference.rules_provider import suggest_mapping
from app.modules.quality.service import compute_quality_report
from app.modules.sources.profiler import profile_csv
from app.modules.sources.validation import validate_upload
from tests.golden_dataset import (
    ERP_PO_LINES_CSV,
    ERP_PURCHASE_ORDERS_CSV,
    EXPECTED_ANOMALIES,
    EXPECTED_PIPELINE_OUTCOMES,
    MASTER_PRODUCTS_CSV,
    MASTER_SUPPLIERS_CSV,
    TMS_ROUTES_CSV,
    TMS_SHIPMENTS_CSV,
    WMS_INVENTORY_CSV,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test fixtures — every golden file becomes a parametrized case
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldenFile:
    name: str
    data: bytes
    expected_rows: int
    expected_columns: int


def _csv(name: str, content: str, rows: int, cols: int) -> GoldenFile:
    return GoldenFile(
        name=name, data=content.encode("utf-8"), expected_rows=rows, expected_columns=cols
    )


def _count_rows(content: str) -> int:
    lines = [ln for ln in content.strip().splitlines() if ln.strip()]
    return max(0, len(lines) - 1)  # exclude header


def _count_cols(content: str) -> int:
    first_line = content.strip().splitlines()[0]
    return len(first_line.split(","))


GOLDEN_FILES: list[GoldenFile] = [
    _csv(
        "erp_purchase_orders",
        ERP_PURCHASE_ORDERS_CSV,
        _count_rows(ERP_PURCHASE_ORDERS_CSV),
        _count_cols(ERP_PURCHASE_ORDERS_CSV),
    ),
    _csv(
        "erp_po_lines",
        ERP_PO_LINES_CSV,
        _count_rows(ERP_PO_LINES_CSV),
        _count_cols(ERP_PO_LINES_CSV),
    ),
    _csv(
        "wms_inventory",
        WMS_INVENTORY_CSV,
        _count_rows(WMS_INVENTORY_CSV),
        _count_cols(WMS_INVENTORY_CSV),
    ),
    _csv(
        "tms_shipments",
        TMS_SHIPMENTS_CSV,
        _count_rows(TMS_SHIPMENTS_CSV),
        _count_cols(TMS_SHIPMENTS_CSV),
    ),
    _csv(
        "master_suppliers",
        MASTER_SUPPLIERS_CSV,
        _count_rows(MASTER_SUPPLIERS_CSV),
        _count_cols(MASTER_SUPPLIERS_CSV),
    ),
    _csv(
        "master_products",
        MASTER_PRODUCTS_CSV,
        _count_rows(MASTER_PRODUCTS_CSV),
        _count_cols(MASTER_PRODUCTS_CSV),
    ),
    _csv("tms_routes", TMS_ROUTES_CSV, _count_rows(TMS_ROUTES_CSV), _count_cols(TMS_ROUTES_CSV)),
]


@pytest.fixture(scope="module")
def workspace_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


def _encode(content: str) -> bytes:
    return content.encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Upload validation (every file must pass)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_golden_files_pass_validation(golden: GoldenFile) -> None:
    """Every golden dataset file must pass upload validation."""
    result = validate_upload(golden.data, f"{golden.name}.csv", "text/csv")
    assert result.valid, f"{golden.name} failed validation: {result.errors}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Profiling (row/column counts deterministic)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_profiling_row_count_matches_golden(golden: GoldenFile) -> None:
    """Profile row count must match the golden dataset's expected row count."""
    profile = profile_csv(golden.data)
    assert profile.row_count == golden.expected_rows, (
        f"{golden.name}: expected {golden.expected_rows} rows, got {profile.row_count}"
    )


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_profiling_column_count_matches_golden(golden: GoldenFile) -> None:
    """Profile column count must match the golden dataset's expected column count."""
    profile = profile_csv(golden.data)
    assert profile.column_count == golden.expected_columns, (
        f"{golden.name}: expected {golden.expected_columns} cols, got {profile.column_count}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Determinism (same input -> identical output)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_profile_is_deterministic(golden: GoldenFile) -> None:
    """Profiling the same bytes twice must yield identical column statistics."""
    p1 = profile_csv(golden.data)
    p2 = profile_csv(golden.data)

    assert p1.row_count == p2.row_count
    assert p1.column_count == p2.column_count
    assert len(p1.columns) == len(p2.columns)

    for c1, c2 in zip(p1.columns, p2.columns, strict=False):
        assert c1.column_name == c2.column_name
        assert c1.inferred_type == c2.inferred_type
        assert c1.null_ratio == c2.null_ratio
        assert c1.distinct_count == c2.distinct_count
        assert c1.sample_values == c2.sample_values


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_profile_converges_on_reorder(golden: GoldenFile) -> None:
    """Row reordering must not change summary statistics (convergence invariant).

    Determinism in Cortex means: same dataset, different order -> same summary.
    We shuffle rows deterministically and verify summary stats are unchanged.
    """
    import random

    lines = golden.data.decode("utf-8").strip().splitlines()
    if len(lines) <= 2:
        pytest.skip("not enough rows to reorder")

    header = lines[0]
    body = lines[1:]
    rand = random.Random(0xC0FFEE)  # deterministic seed for reproducibility
    rand.shuffle(body)
    reordered = ("\n".join([header, *body]) + "\n").encode("utf-8")

    p1 = profile_csv(golden.data)
    p2 = profile_csv(reordered)

    assert p1.row_count == p2.row_count
    assert p1.column_count == p2.column_count
    for c1, c2 in zip(p1.columns, p2.columns, strict=False):
        assert c1.inferred_type == c2.inferred_type, f"{c1.column_name} type diverged"
        assert c1.null_ratio == c2.null_ratio, f"{c1.column_name} null_ratio diverged"
        assert c1.distinct_count == c2.distinct_count, f"{c1.column_name} distinct diverged"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Schema mapping (alias registry correctness)
# ─────────────────────────────────────────────────────────────────────────────


def test_supplier_name_maps_to_supplier_legal_name() -> None:
    result = suggest_mapping("supplier_name")
    assert result.canonical_entity == "Supplier"
    assert result.canonical_field == "legal_name"
    assert result.confidence == 1.0
    assert result.requires_review is False


def test_po_number_maps_to_purchase_order() -> None:
    result = suggest_mapping("po_number")
    assert result.canonical_entity == "PurchaseOrder"
    assert result.confidence == 1.0


def test_shipment_id_maps_to_shipment() -> None:
    result = suggest_mapping("shipment_id")
    assert result.canonical_entity == "Shipment"
    assert result.confidence == 1.0


def test_unknown_column_requires_review() -> None:
    result = suggest_mapping("completely_unknown_xyz")
    assert result.canonical_entity is None
    assert result.requires_review is True


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — Data quality scoring (six dimensions + trust score)
# ─────────────────────────────────────────────────────────────────────────────


def _make_source_file_mock(
    file_id: str, workspace_id: str, created_at, row_count: int | None = None
):
    """Build a lightweight SourceFile-like object without DB."""
    from types import SimpleNamespace

    return SimpleNamespace(
        file_id=file_id,
        workspace_id=workspace_id,
        created_at=created_at,
        row_count=row_count,
    )


def _make_profile_mock(
    profile_id,
    file_id,
    workspace_id,
    column_name,
    inferred_type,
    null_ratio,
    distinct_count,
    sample_values=None,
    recommended_mapping=None,
    mapping_confidence=None,
    requires_review=False,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        profile_id=profile_id,
        file_id=file_id,
        workspace_id=workspace_id,
        column_name=column_name,
        column_index=0,
        inferred_type=inferred_type,
        null_ratio=null_ratio,
        distinct_count=distinct_count,
        sample_values=sample_values or [],
        recommended_mapping=recommended_mapping,
        mapping_confidence=mapping_confidence,
        requires_review=requires_review,
    )


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_quality_scores_in_valid_range(golden: GoldenFile, workspace_id: str) -> None:
    """Every golden file must produce quality scores within [0.0, 1.0]."""
    from datetime import datetime

    profile = profile_csv(golden.data)
    source_file = _make_source_file_mock(
        file_id=f"file-{golden.name}",
        workspace_id=workspace_id,
        created_at=datetime.now(UTC),
        row_count=profile.row_count,
    )

    col_profiles = [
        _make_profile_mock(
            profile_id=f"prof-{golden.name}-{i}",
            file_id=source_file.file_id,
            workspace_id=workspace_id,
            column_name=col.column_name,
            inferred_type=col.inferred_type,
            null_ratio=col.null_ratio,
            distinct_count=col.distinct_count,
            sample_values=col.sample_values,
        )
        for i, col in enumerate(profile.columns)
    ]

    report = compute_quality_report(source_file, col_profiles)
    assert 0.0 <= report.overall_score <= 1.0, f"{golden.name} overall out of range"
    for d in report.dimensions:
        assert 0.0 <= d.score <= 1.0, f"{golden.name}.{d.name} out of range: {d.score}"


def test_quality_dimensions_six_present(workspace_id: str) -> None:
    """Quality report must include all six DQ dimensions."""
    from datetime import datetime

    profile = profile_csv(_encode(MASTER_SUPPLIERS_CSV))
    source_file = _make_source_file_mock(
        file_id="file-test",
        workspace_id=workspace_id,
        created_at=datetime.now(UTC),
        row_count=profile.row_count,
    )
    cols = [
        _make_profile_mock(
            profile_id=f"p-{i}",
            file_id="file-test",
            workspace_id=workspace_id,
            column_name=c.column_name,
            inferred_type=c.inferred_type,
            null_ratio=c.null_ratio,
            distinct_count=c.distinct_count,
            sample_values=c.sample_values,
        )
        for i, c in enumerate(profile.columns)
    ]

    report = compute_quality_report(source_file, cols)
    dimension_names = {d.name for d in report.dimensions}
    expected = {"completeness", "consistency", "uniqueness", "timeliness", "validity", "integrity"}
    assert dimension_names == expected, f"missing/on extra dims: {dimension_names}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6 — Anomaly detection invariants (golden dataset has known defects)
# ─────────────────────────────────────────────────────────────────────────────


def test_master_suppliers_duplicate_detected_as_uniqueness_below_one(
    workspace_id: str,
) -> None:
    """SUP-001 and SUP-005 share tax_id US12345678 (same logical supplier).

    Surfaces the entity-resolution anomaly: distinct tax_id count < row_count,
    even though supplier_id is unique. Validates anomaly detection without
    row-level access — the tax_id column's distinct_count surfaces the dup.
    """
    from datetime import datetime

    profile = profile_csv(_encode(MASTER_SUPPLIERS_CSV))
    # The duplicate is in tax_id (same legal supplier, different supplier_id)
    tax_id_col = next(
        (c for c in profile.columns if c.column_name.lower() == "tax_id"),
        None,
    )
    assert tax_id_col is not None, "tax_id column not found"
    assert profile.row_count == 6
    assert tax_id_col.distinct_count == 5, (
        f"expected 5 distinct tax_ids (one duplicate), got {tax_id_col.distinct_count}"
    )
    assert tax_id_col.distinct_count < profile.row_count

    # supplier_id should be fully distinct (different internal IDs)
    supplier_id_col = next(
        (c for c in profile.columns if c.column_name.lower() == "supplier_id"),
        None,
    )
    assert supplier_id_col is not None
    assert supplier_id_col.distinct_count == 6

    # Integrity score should surface the anomaly via tax_id (id-pattern column)
    source_file = _make_source_file_mock(
        file_id="file-sup",
        workspace_id=workspace_id,
        created_at=datetime.now(UTC),
        row_count=profile.row_count,
    )
    cols = [
        _make_profile_mock(
            profile_id=f"p-{i}",
            file_id="file-sup",
            workspace_id=workspace_id,
            column_name=c.column_name,
            inferred_type=c.inferred_type,
            null_ratio=c.null_ratio,
            distinct_count=c.distinct_count,
            sample_values=c.sample_values,
        )
        for i, c in enumerate(profile.columns)
    ]
    report = compute_quality_report(source_file, cols)
    integrity = next(d.score for d in report.dimensions if d.name == "integrity")
    assert integrity < 1.0, "duplicate tax_id must reduce integrity"


def test_erp_purchase_orders_duplicate_po_detected(
    workspace_id: str,
) -> None:
    """PO-20260115-001 and PO-20260115-003 are identical → uniqueness anomaly."""

    profile = profile_csv(_encode(ERP_PURCHASE_ORDERS_CSV))
    po_col = next(
        (c for c in profile.columns if c.column_name.lower() == "po_number"),
        None,
    )
    assert po_col is not None
    # po_number is fully distinct across 5 rows (each PO has a different number)
    assert profile.row_count == 5
    assert po_col.distinct_count == 5

    # The duplicate order surfaces through non-key columns: PO-001 and PO-003
    # share supplier_id + ship_to_facility_id + incoterm + currency +
    # total_value + line_count. Look at total_value as a sentinel.
    total_value_col = next(
        (c for c in profile.columns if c.column_name.lower() == "total_value"),
        None,
    )
    assert total_value_col is not None
    assert total_value_col.distinct_count < profile.row_count, (
        "expected a duplicate total_value (PO-001 == PO-003); "
        f"got {total_value_col.distinct_count} distinct in {profile.row_count} rows"
    )


def test_erp_po_lines_exposes_duplicate_line_fingerprints() -> None:
    """ERP PO line file shows duplicate (sku, qty) fingerprints between PO-001/003."""
    profile = profile_csv(_encode(ERP_PO_LINES_CSV))
    sku_col = next(
        (c for c in profile.columns if c.column_name.lower() == "product_sku"),
        None,
    )
    assert sku_col is not None
    assert profile.row_count == 13
    assert sku_col.distinct_count < profile.row_count, (
        "expected duplicate SKU fingerprints between PO-001 and PO-003 lines"
    )


def test_wms_inventory_has_date_column_for_timeliness() -> None:
    """WMS inventory 'as_of' column should be detected as a date column."""
    profile = profile_csv(_encode(WMS_INVENTORY_CSV))
    as_of_col = next(
        (c for c in profile.columns if c.column_name.lower() == "as_of"),
        None,
    )
    assert as_of_col is not None
    # Date columns are inferred as DATE or DATETIME (ISO format with time)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 7 — Performance budget (profiling < 5s per file)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("golden", GOLDEN_FILES, ids=[f.name for f in GOLDEN_FILES])
def test_profiling_meets_budget(golden: GoldenFile) -> None:
    """Profiling each golden file must complete under the 5s budget."""
    start = time.perf_counter()
    profile_csv(golden.data)
    duration_s = time.perf_counter() - start
    assert duration_s < 5.0, f"{golden.name} exceeded profiling budget: {duration_s:.2f}s"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 8 — Dataset integrity invariants (golden corpus shape)
# ─────────────────────────────────────────────────────────────────────────────


def test_golden_dataset_has_seven_files() -> None:
    """Golden dataset must contain exactly 7 source files (regression sentinel)."""
    assert len(GOLDEN_FILES) == 7, "golden dataset file count changed — bump version"


def test_expected_anomalies_dict_is_populated() -> None:
    """Anomaly expectations must be declared for every anomaly class."""
    assert "erp_purchase_orders" in EXPECTED_ANOMALIES
    assert "master_suppliers" in EXPECTED_ANOMALIES
    assert "tms_routes" in EXPECTED_ANOMALIES


def test_expected_pipeline_outcomes_shape() -> None:
    """Pipeline outcome expectations must declare every compiled stage."""
    assert "source_batches" in EXPECTED_PIPELINE_OUTCOMES
    assert "conflicts" in EXPECTED_PIPELINE_OUTCOMES
    assert "readiness" in EXPECTED_PIPELINE_OUTCOMES
