"""RC-1 module unit tests — events, quality, errors, budgets, security, ids.

These tests run without a database or external dependencies. They verify the
core invariants of every subsystem that RC-1 hardens:

* DomainEvents dispatch to handlers with at-least-once + dedup semantics
* DataQualityReport contains all six dimensions and stays in [0.0, 1.0]
* Error taxonomy maps every error class to its frozen code + HTTP status
* Performance budget checker returns ok/alert/breach correctly
* Secrets scanner detects AWS/GitHub/openai keys without false positives
* uuid7 is monotonic increasing within a process

These tests are intentionally pure — no fixtures, no DB, no network. They
exist to (a) keep coverage high on the hardening surface and (b) provide
a fast signal when an invariant is broken.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.common.errors import (
    AuthenticationError,
    CortexError,
    DatabaseError,
    DuplicateConflictError,
    EvidenceError,
    SecurityError,
)
from app.common.ids import uuid7
from app.modules.events.domain_events import (
    DomainEvent,
    DomainEventDispatcher,
    DomainEventTypes,
    emit_domain_event,
)
from app.modules.performance.budgets import (
    BUDGETS,
    check_budget,
    format_budget_report,
)
from app.modules.quality.service import (
    DIMENSION_WEIGHTS,
    compute_quality_report,
)
from app.modules.security.hardening import scan_for_secrets

# ─────────────────────────────────────────────────────────────────────────────
# IDs — UUIDv7 monotonicity
# ─────────────────────────────────────────────────────────────────────────────


def test_uuid7_is_monotonic_increasing() -> None:
    """Successive uuid7() calls within the same millisecond must be monotonic."""
    ids = [uuid7() for _ in range(100)]
    for prev, cur in zip(ids, ids[1:], strict=False):
        assert prev <= cur, f"{prev} > {cur} — uuid7 is not monotonic"


def test_uuid7_format() -> None:
    """uuid7 must be a 36-char hyphenated UUID string."""
    val = uuid7()
    assert len(val) == 36
    assert val.count("-") == 4


# ─────────────────────────────────────────────────────────────────────────────
# Error taxonomy — frozen codes and HTTP status
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "err,expected_code,expected_status",
    [
        (AuthenticationError("x"), "unauthenticated", 401),
        (SecurityError("x"), "forbidden", 403),
        (EvidenceError("x"), "validation_error", 422),
        (DuplicateConflictError("x"), "conflict", 409),
        (DatabaseError("x"), "unavailable", 503),
    ],
)
def test_error_codes_and_statuses(
    err: CortexError, expected_code: str, expected_status: int
) -> None:
    assert err.code == expected_code
    assert err.http_status == expected_status
    assert err.to_wire()["error"]["code"] == expected_code


def test_error_wire_format_has_all_fields() -> None:
    """Wire envelope must follow docs/05-api-standards §6."""
    err = SecurityError("test", details=[{"k": "v"}], target="user.42", request_id="req-1")
    wire = err.to_wire()["error"]
    for key in ("code", "message", "details", "target", "request_id"):
        assert key in wire


# ─────────────────────────────────────────────────────────────────────────────
# Domain events — dispatcher dispatches with dedup
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_domain_event_dispatched_to_registered_handler() -> None:
    """emit_domain_event must dispatch to all registered handlers."""
    received: list[DomainEvent] = []

    async def handler(event: DomainEvent) -> None:
        received.append(event)

    dispatcher = DomainEventDispatcher()
    dispatcher.register(DomainEventTypes.EVIDENCE_CLAIM_CREATED, handler)

    event = DomainEvent(
        event_type=DomainEventTypes.EVIDENCE_CLAIM_CREATED,
        workspace_id="ws-1",
        payload={"claim_id": "c-1"},
    )
    await dispatcher.dispatch(event)
    assert len(received) == 1
    assert received[0].event_type == DomainEventTypes.EVIDENCE_CLAIM_CREATED


@pytest.mark.asyncio
async def test_domain_event_dedup_prevents_double_dispatch() -> None:
    """The same event dispatched twice must only invoke a handler once."""
    invocations = 0

    async def handler(event: DomainEvent) -> None:
        nonlocal invocations
        invocations += 1

    dispatcher = DomainEventDispatcher()
    dispatcher.register(DomainEventTypes.CONFLICT_DETECTED, handler)

    event = DomainEvent(
        event_type=DomainEventTypes.CONFLICT_DETECTED,
        workspace_id="ws-1",
        payload={"conflict_id": "k-1"},
    )
    await dispatcher.dispatch(event)
    await dispatcher.dispatch(event)  # dedup should suppress
    assert invocations == 1


@pytest.mark.asyncio
async def test_domain_event_handler_failure_is_isolated() -> None:
    """One handler raising must not block other handlers."""

    async def bad_handler(event: DomainEvent) -> None:
        raise RuntimeError("boom")

    ok_calls: list[str] = []

    async def ok_handler(event: DomainEvent) -> None:
        ok_calls.append(event.event_type)

    dispatcher = DomainEventDispatcher()
    dispatcher.register("test.isolated", bad_handler)
    dispatcher.register("test.isolated", ok_handler)

    await dispatcher.dispatch(DomainEvent(event_type="test.isolated", workspace_id="ws-1"))
    assert ok_calls, "good handler was not invoked because bad handler ran first"


@pytest.mark.asyncio
async def test_emit_domain_event_validates_required_fields() -> None:
    """emit_domain_event must reject empty event_type or workspace_id."""
    with pytest.raises(ValueError):
        await emit_domain_event("", "ws-1", {})
    with pytest.raises(ValueError):
        await emit_domain_event("test.event", "", {})


# ─────────────────────────────────────────────────────────────────────────────
# Performance budgets — check_budget returns correct status
# ─────────────────────────────────────────────────────────────────────────────


def test_budget_ok_when_value_under_alert() -> None:
    r = check_budget("upload", "http_handling_p95_ms", 500)
    assert r.status == "ok"
    assert r.target == 1000


def test_budget_alert_in_80_to_100_pct_range() -> None:
    r = check_budget("upload", "http_handling_p95_ms", 900)
    assert r.status == "alert"


def test_budget_breach_when_value_exceeds_target() -> None:
    r = check_budget("upload", "http_handling_p95_ms", 1500)
    assert r.status == "breach"


def test_budget_unknown_metric_returns_unknown() -> None:
    r = check_budget("upload", "nonexistent", 1.0)
    assert r.status == "unknown"


def test_budget_report_format_lists_every_metric() -> None:
    results = [check_budget("upload", "http_handling_p95_ms", 100)]
    report = format_budget_report(results)
    assert "upload.http_handling_p95_ms" in report
    assert "ok" in report.lower() or "✅" in report


def test_all_budget_subsystems_have_entries() -> None:
    for sub in ["upload", "profiling", "graph", "audit", "frontend"]:
        assert sub in BUDGETS, f"missing budget subsystem: {sub}"


# ─────────────────────────────────────────────────────────────────────────────
# Data quality — report shape and weighted scoring
# ─────────────────────────────────────────────────────────────────────────────


def _mock_file(
    file_id: str = "f-1",
    workspace_id: str = "ws-1",
    created_at: datetime | None = None,
    row_count: int | None = 100,
) -> Any:
    return SimpleNamespace(
        file_id=file_id,
        workspace_id=workspace_id,
        created_at=created_at or datetime.now(UTC),
        row_count=row_count,
    )


def _mock_profile(
    name: str,
    inferred_type: str = "string",
    null_ratio: float = 0.0,
    distinct_count: int = 100,
    samples: list[str] | None = None,
) -> Any:
    return SimpleNamespace(
        profile_id=f"p-{name}",
        file_id="f-1",
        workspace_id="ws-1",
        column_name=name,
        column_index=0,
        inferred_type=inferred_type,
        null_ratio=null_ratio,
        distinct_count=distinct_count,
        sample_values=samples or [],
    )


def test_quality_dimension_weights_sum_to_one() -> None:
    """Dimension weights must sum to 1.0 so the trust score is normalized."""
    assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9


def test_quality_dimensions_count_is_six() -> None:
    assert len(DIMENSION_WEIGHTS) == 6


def test_quality_report_contains_all_dimensions() -> None:
    file = _mock_file()
    profiles = [
        _mock_profile("supplier_id", "string", 0.0, 50),
        _mock_profile("name", "string", 0.0, 50),
        _mock_profile("country", "string", 0.05, 5),
    ]
    report = compute_quality_report(file, profiles)
    names = {d.name for d in report.dimensions}
    assert names == {
        "completeness",
        "consistency",
        "uniqueness",
        "timeliness",
        "validity",
        "integrity",
    }


def test_quality_report_overall_score_is_weighted_average() -> None:
    file = _mock_file()
    profiles = [
        _mock_profile("supplier_id", "string", 0.0, 100),
        _mock_profile("name", "string", 0.0, 100),
    ]
    report = compute_quality_report(file, profiles)
    expected = sum(DIMENSION_WEIGHTS[d.name] * d.score for d in report.dimensions)
    assert abs(report.overall_score - round(expected, 4)) < 1e-6


def test_quality_report_generates_recommendations_for_low_scores() -> None:
    file = _mock_file(row_count=100)
    profiles = [
        _mock_profile("id", "mixed", 0.6, 5),  # low completeness + low integrity
    ]
    report = compute_quality_report(file, profiles)
    assert report.recommendations, "expected recommendations for low-score dimensions"


def test_quality_stale_dates_reduce_timeliness() -> None:
    """A file with a 7-day-old business date must score < 1.0 on timeliness."""
    old_business_date = "2020-01-01T00:00:00Z"
    file = _mock_file(row_count=1)
    profiles = [
        _mock_profile("as_of", "datetime", 0.0, 1, samples=[old_business_date]),
    ]
    report = compute_quality_report(file, profiles)
    timeliness = next(d.score for d in report.dimensions if d.name == "timeliness")
    assert timeliness < 1.0, f"stale dates should reduce timeliness (got {timeliness})"


def test_quality_duplicate_ids_reduce_integrity() -> None:
    """An id column with distinct_count < row_count must drop integrity."""
    file = _mock_file(row_count=100)
    profiles = [
        _mock_profile("supplier_id", "string", 0.0, 50),  # 50 distinct in 100 rows
        _mock_profile("name", "string", 0.0, 100),
    ]
    report = compute_quality_report(file, profiles)
    integrity = next(d.score for d in report.dimensions if d.name == "integrity")
    assert integrity < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Security — secrets scanner
# ─────────────────────────────────────────────────────────────────────────────


def test_secrets_scanner_detects_aws_key(tmp_path) -> None:
    f = tmp_path / "config.txt"
    f.write_text("AWS_KEY = AKIAIOSFODNN7EXAMPLE\n")
    findings = scan_for_secrets(f)
    assert findings, "AWS key not detected"
    assert findings[0][0] == "AWS Access Key"


def test_secrets_scanner_detects_github_token(tmp_path) -> None:
    f = tmp_path / "script.py"
    # ghp_ followed by 36 chars
    f.write_text('TOKEN = "ghp_0123456789abcdefghijklmnopqrstuvwxyz0000"\n')
    findings = scan_for_secrets(f)
    assert findings, "GitHub token not detected"


def test_secrets_scanner_no_false_positive_on_plain_text(tmp_path) -> None:
    f = tmp_path / "notes.md"
    f.write_text("# Notes\nThis is just regular text with no secrets.\n")
    findings = scan_for_secrets(f)
    assert findings == [], f"false positive: {findings}"
