"""F1 — P50 / P95 / P99 latency SLO catalog and evaluator (Phase 15 gate).

Pins the frozen SLO target values and the route-classification logic
that Grafana / Alertmanager alert rules use. The values in
``LATENCY_TARGETS`` are not configurable — they are the
release-gating SLO contract for the pilot. Changing any of them is
a release-gating decision, not a one-line config edit; see
``docs/architecture/F1_SLO_CATALOG.md``.

Three things this module does:

1. ``classify_route(path)`` — given a request path like
   ``/api/v1/workspace/stream``, returns the ``route_family`` key
   (e.g. ``"workspace"``). The first non-empty segment after the
   API version. Routes that don't match a known family return
   ``"_unmatched"`` and are excluded from SLO burn.

2. ``LATENCY_TARGETS`` — frozen dict of route family → P50, P95,
   P99 targets in seconds. The P99 value is the binding alert
   target. P50 and P95 are informational.

3. ``compliance_from_buckets(family, bucket_counts, total_count)`` —
   given a snapshot of ``cortex_api_latency_seconds_bucket`` for a
   family (a mapping of ``le`` boundary → cumulative count),
   returns the fraction of observations that fell within the P99
   target. Used by a scheduled job to publish
   ``cortex_slo_compliance{route,percentile}``.

The bucket boundaries here MUST match the histogram in
``app/infrastructure/metrics.py``. The regression test in
``tests/test_slo_catalog.py::TestHistogramBucketSchema`` pins that.
"""

from __future__ import annotations

from dataclasses import dataclass

# Frozen route families. The first non-empty path segment after the
# API version (i.e. /api/v1/<family>/...) is the family. Any path
# that doesn't match returns "_unmatched" and is not subject to SLO
# burn.
ROUTE_FAMILIES: tuple[str, ...] = (
    "workspace",
    "ingest",
    "graph",
    "decisions",
    "realtime",
    "agents",
    "workflow",
    "twin",
    "admin",
    "health",
)


# Frozen SLO targets (seconds). P99 is the binding alert target;
# P50 and P95 are informational. See docs/architecture/F1_SLO_CATALOG.md.
LATENCY_TARGETS: dict[str, dict[str, float]] = {
    "workspace": {"p50": 0.05, "p95": 0.20, "p99": 0.50},
    "ingest":    {"p50": 0.20, "p95": 0.80, "p99": 2.00},
    "graph":     {"p50": 0.10, "p95": 0.40, "p99": 1.00},
    "decisions": {"p50": 0.15, "p95": 0.60, "p99": 1.50},
    "realtime":  {"p50": 0.01, "p95": 0.05, "p99": 0.20},
    "agents":    {"p50": 0.30, "p95": 1.50, "p99": 3.00},
    "workflow":  {"p50": 0.20, "p95": 1.00, "p99": 2.50},
    "twin":      {"p50": 0.10, "p95": 0.50, "p99": 1.50},
    "admin":     {"p50": 0.20, "p95": 1.00, "p99": 2.00},
    "health":    {"p50": 0.005, "p95": 0.02, "p99": 0.05},
}


# Frozen bucket schema for cortex_api_latency_seconds. This list MUST
# stay in sync with the histogram definition in
# app/infrastructure/metrics.py. The regression test pins both.
LATENCY_HISTOGRAM_BUCKETS: tuple[float, ...] = (
    0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 1.0, 2.5, 5.0, 10.0,
)


@dataclass(frozen=True)
class ComplianceResult:
    """Result of evaluating one observation (or a bucket snapshot)
    against the SLO target for a family."""

    family: str
    percentile: str  # "p50" | "p95" | "p99"
    target_seconds: float
    observed_seconds: float | None  # None for bucket-snapshot eval
    within_target: bool
    compliance_ratio: float | None  # 0.0..1.0, set by compliance_from_buckets


def classify_route(path: str) -> str:
    """Map a request path to a route family.

    Examples:
        /api/v1/workspace/state         -> "workspace"
        /api/v1/workspace/stream        -> "workspace"
        /api/v1/graph/subgraph          -> "graph"
        /api/v1/agents/run              -> "agents"
        /api/v2/workspace/state         -> "workspace"  (version-agnostic)
        /healthz                        -> "health"
        /readyz                         -> "health"
        /metrics                        -> "health"
        /api/v1/foobar                   -> "_unmatched"
        ""                              -> "_unmatched"
    """
    if not path:
        return "_unmatched"
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "_unmatched"

    # Non-versioned health endpoints: /healthz, /readyz, /metrics
    # map to the "health" family even though their first path
    # segment is not literally "health".
    if parts[0] in ("healthz", "readyz", "metrics"):
        return "health"

    # Skip the API version segment ("v1", "v2", etc.) when present.
    # Convention: /api/<version>/<family>/...
    if parts[0] == "api" and len(parts) >= 3 and parts[1].startswith("v"):
        family = parts[2]
    else:
        # Non-versioned path (e.g. /healthz, /readyz, /metrics).
        family = parts[0]

    if family in ROUTE_FAMILIES:
        return family
    return "_unmatched"


def evaluate_observation(family: str, observed_seconds: float) -> ComplianceResult:
    """Evaluate a single observation against the family's P99 target.

    Used in unit tests; production alert rules compute percentiles
    from the histogram directly. A family of ``_unmatched`` is
    always within-target (not subject to SLO burn) — the caller
    should filter those before calling this."""
    if family == "_unmatched" or family not in LATENCY_TARGETS:
        return ComplianceResult(
            family=family,
            percentile="p99",
            target_seconds=0.0,
            observed_seconds=observed_seconds,
            within_target=True,
            compliance_ratio=None,
        )
    target = LATENCY_TARGETS[family]["p99"]
    return ComplianceResult(
        family=family,
        percentile="p99",
        target_seconds=target,
        observed_seconds=observed_seconds,
        within_target=observed_seconds <= target,
        compliance_ratio=None,
    )


def compliance_from_buckets(
    family: str,
    bucket_counts: dict[float, int],
    total_count: int,
) -> float:
    """Given a snapshot of cumulative bucket counts for one family
    and the total observation count, return the fraction of
    observations that fell within the P99 target.

    ``bucket_counts`` maps each ``le`` boundary to its cumulative
    observation count (i.e. the value Prometheus publishes for
    ``cortex_api_latency_seconds_bucket{le="0.5",...}``). The
    largest ``le`` at or above the P99 target is used as the
    numerator; ``total_count`` is the denominator.

    If the family is unknown or the total is zero, returns 1.0
    (vacuously compliant — no traffic means no burn).
    """
    if family not in LATENCY_TARGETS or total_count <= 0:
        return 1.0
    target = LATENCY_TARGETS[family]["p99"]
    # Pick the smallest bucket boundary that is >= the P99 target.
    # The cumulative count at that boundary is "how many
    # observations were at or below this le". A simple
    # implementation picks the largest le at-or-below target;
    # that gives the count of observations that are STRICTLY
    # within the P99 budget (rather than at the boundary).
    candidates = sorted(le for le in bucket_counts if le <= target)
    if not candidates:
        return 0.0
    boundary = candidates[-1]
    within = bucket_counts[boundary]
    return max(0.0, min(1.0, within / total_count))
