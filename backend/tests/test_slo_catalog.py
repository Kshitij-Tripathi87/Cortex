"""F1 — P50 / P95 / P99 SLO catalog and evaluator (Phase 15 gate).

Pins the wire contract for the latency SLO subsystem:

- The frozen route families in ``ROUTE_FAMILIES`` and the frozen
  P50/P95/P99 targets in ``LATENCY_TARGETS``. Changing these
  values invalidates the SLO error budget for the 28-day window —
  this test makes the change a release-gating decision, not a
  one-line config edit.
- The histogram bucket schema in ``LATENCY_HISTOGRAM_BUCKETS``
  matches the actual Prometheus histogram in
  ``app/infrastructure/metrics.py``. A mismatch would silently
  corrupt ``histogram_quantile()`` in Grafana.
- ``classify_route()`` correctly maps request paths to families,
  including the /api/v1/ vs /api/v2/ version-agnostic case and
  the non-versioned /healthz, /readyz, /metrics case.
- ``evaluate_observation()`` returns the right within/outside
  answer for representative values.
- ``compliance_from_buckets()`` correctly computes the within-P99
  fraction from a cumulative bucket-count snapshot.

The test is hermetic — no Prometheus, no Grafana, no network.
"""

from __future__ import annotations

import pytest

from app.infrastructure import metrics, slo

# ─────────────────────────────────────────────────────────────────────────────
# 1. Route classification — every family is reachable and the version
#    prefix is stripped
# ─────────────────────────────────────────────────────────────────────────────


class TestRouteClassification:
    """``classify_route()`` is the gateway between the histogram label
    ``route`` and the SLO target. If it returns the wrong family,
    the alert rule applies the wrong budget. Pins all reachable
    paths."""

    def test_api_v1_routes_strip_version(self):
        # The convention: /api/<version>/<family>/...
        assert slo.classify_route("/api/v1/workspace/state") == "workspace"
        assert slo.classify_route("/api/v1/workspace/stream") == "workspace"
        assert slo.classify_route("/api/v1/ingest/raw") == "ingest"
        assert slo.classify_route("/api/v1/graph/subgraph") == "graph"
        assert slo.classify_route("/api/v1/decisions") == "decisions"
        assert slo.classify_route("/api/v1/decisions/evidence") == "decisions"
        assert slo.classify_route("/api/v1/realtime/ws") == "realtime"
        assert slo.classify_route("/api/v1/agents/run") == "agents"
        assert slo.classify_route("/api/v1/workflow/jobs") == "workflow"
        assert slo.classify_route("/api/v1/twin/run") == "twin"
        assert slo.classify_route("/api/v1/admin/audit") == "admin"

    def test_api_v2_routes_strip_version(self):
        # Version-agnostic — when /api/v2/ lands, family is the same.
        assert slo.classify_route("/api/v2/workspace/state") == "workspace"
        assert slo.classify_route("/api/v2/graph/critical") == "graph"

    def test_non_versioned_health_routes(self):
        # /healthz, /readyz, /metrics are not under /api/v1/.
        assert slo.classify_route("/healthz") == "health"
        assert slo.classify_route("/readyz") == "health"
        assert slo.classify_route("/metrics") == "health"

    def test_unknown_routes_return_unmatched(self):
        # _unmatched means "do not apply SLO burn".
        assert slo.classify_route("/api/v1/foobar") == "_unmatched"
        assert slo.classify_route("/api/v1/workspacex") == "_unmatched"
        # A path that looks like /api/v1/<family>/ but the family
        # has been deprecated must not silently match.
        assert slo.classify_route("/api/v1/legacy") == "_unmatched"

    def test_empty_path_returns_unmatched(self):
        assert slo.classify_route("") == "_unmatched"
        assert slo.classify_route("/") == "_unmatched"
        assert slo.classify_route("//") == "_unmatched"

    def test_trailing_slash_does_not_change_family(self):
        # Defensive: a path with a trailing slash should classify
        # identically to the same path without one.
        assert slo.classify_route("/api/v1/workspace/state/") == slo.classify_route(
            "/api/v1/workspace/state"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Latency targets — the frozen SLO table
# ─────────────────────────────────────────────────────────────────────────────


class TestLatencyTargets:
    """The P50/P95/P99 values are the contract. Any change requires
    a release-gating decision documented in
    docs/architecture/F1_SLO_CATALOG.md. The test pins the exact
    values that ship."""

    def test_every_route_family_has_targets(self):
        for family in slo.ROUTE_FAMILIES:
            assert family in slo.LATENCY_TARGETS, (
                f"Route family {family!r} is missing from LATENCY_TARGETS"
            )

    def test_every_target_has_p50_p95_p99(self):
        for family, targets in slo.LATENCY_TARGETS.items():
            assert "p50" in targets, f"{family} missing p50"
            assert "p95" in targets, f"{family} missing p95"
            assert "p99" in targets, f"{family} missing p99"

    def test_p50_le_p95_le_p99_monotonic(self):
        # p50 ≤ p95 ≤ p99 for every family. Violations would mean
        # the histogram buckets are mis-bucketed or the targets
        # were copy-pasted in the wrong order.
        for family, targets in slo.LATENCY_TARGETS.items():
            assert targets["p50"] <= targets["p95"], (
                f"{family}: p50={targets['p50']} > p95={targets['p95']}"
            )
            assert targets["p95"] <= targets["p99"], (
                f"{family}: p95={targets['p95']} > p99={targets['p99']}"
            )

    def test_all_targets_strictly_positive(self):
        # A 0-second P99 would be vacuous; a negative target is a
        # copy-paste bug.
        for family, targets in slo.LATENCY_TARGETS.items():
            for percentile, value in targets.items():
                assert value > 0, f"{family}.{percentile} must be > 0, got {value}"

    def test_pinned_realtime_targets(self):
        # Sanity check: realtime must be the tightest SLO.
        # Hard-coded because the contract is "realtime is hot-path".
        assert slo.LATENCY_TARGETS["realtime"]["p99"] == 0.20
        assert slo.LATENCY_TARGETS["realtime"]["p95"] == 0.05

    def test_pinned_health_targets(self):
        # Health endpoints must be the tightest of all — they're
        # polled by the load balancer.
        assert slo.LATENCY_TARGETS["health"]["p99"] == 0.05

    def test_pinned_agents_targets(self):
        # Agents is the slow path (multi-agent deliberation).
        assert slo.LATENCY_TARGETS["agents"]["p99"] == 3.00


# ─────────────────────────────────────────────────────────────────────────────
# 3. Histogram bucket schema — the histogram and the SLO module agree
# ─────────────────────────────────────────────────────────────────────────────


class TestHistogramBucketSchema:
    """The bucket list in LATENCY_HISTOGRAM_BUCKETS MUST match the
    actual Prometheus histogram in metrics.py. A mismatch silently
    corrupts ``histogram_quantile()`` in Grafana — the resulting
    P99 is mathematically valid but measures the wrong thing."""

    def test_slo_module_buckets_match_prometheus_histogram(self):
        # The metrics module exposes the histogram via
        # metrics.api_latency_seconds; the bucket list is on
        # ._upper_bounds for prometheus_client Histogram objects.
        # The list includes a sentinel +inf at the end representing
        # the implicit "everything fits" overflow bucket; that
        # sentinel is part of the prometheus_client contract and
        # not part of our SLO target list.
        prom_buckets = tuple(metrics.api_latency_seconds._upper_bounds)
        # Filter out the +inf overflow bucket that prometheus_client
        # always appends.
        finite_prom = tuple(b for b in prom_buckets if b != float("inf"))
        assert tuple(slo.LATENCY_HISTOGRAM_BUCKETS) == tuple(finite_prom), (
            f"LATENCY_HISTOGRAM_BUCKETS in slo.py must match the "
            f"Prometheus histogram in metrics.py. "
            f"slo={slo.LATENCY_HISTOGRAM_BUCKETS}, "
            f"prometheus={finite_prom}"
        )

    def test_bucket_boundaries_are_strictly_ascending(self):
        buckets = slo.LATENCY_HISTOGRAM_BUCKETS
        for prev, curr in zip(buckets, buckets[1:], strict=False):
            assert curr > prev, f"Bucket boundaries must be strictly ascending: {prev} -> {curr}"

    def test_bucket_count_is_reasonable(self):
        # The Prometheus default is ~12 buckets; we ship 10. Less
        # than 6 means P99 quantile math is too coarse; more than
        # 20 means the histogram is too expensive to update on
        # every request.
        n = len(slo.LATENCY_HISTOGRAM_BUCKETS)
        assert 6 <= n <= 20, (
            f"Expected 6-20 buckets, got {n}. Coarser P99 math is "
            f"inaccurate; finer is high-cardinality overhead."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Observation evaluator — single-shot within/outside decision
# ─────────────────────────────────────────────────────────────────────────────


class TestObservationEvaluator:
    """``evaluate_observation()`` is what a unit test would call to
    assert a synthetic request was within the SLO budget. The
    production alert path uses the histogram directly, but this
    function powers the unit-test contract."""

    def test_within_target_workspace(self):
        # 0.30s on /workspace — within the 0.50s P99 target.
        r = slo.evaluate_observation("workspace", 0.30)
        assert r.family == "workspace"
        assert r.percentile == "p99"
        assert r.target_seconds == 0.50
        assert r.observed_seconds == 0.30
        assert r.within_target is True

    def test_outside_target_workspace(self):
        # 0.75s on /workspace — over the 0.50s P99 target.
        r = slo.evaluate_observation("workspace", 0.75)
        assert r.within_target is False
        assert r.observed_seconds == 0.75

    def test_boundary_equals_target_within(self):
        # An observation at exactly the target is within (≤, not <).
        r = slo.evaluate_observation("graph", 1.00)
        assert r.within_target is True
        assert r.target_seconds == 1.00

    def test_realtime_observation(self):
        # 0.05s on /realtime — within the 0.20s P99 target.
        r = slo.evaluate_observation("realtime", 0.05)
        assert r.within_target is True

    def test_health_observation(self):
        # 0.001s on /healthz — well within the 0.05s P99 target.
        r = slo.evaluate_observation("health", 0.001)
        assert r.within_target is True

    def test_unmatched_observation_is_vacuously_within(self):
        # _unmatched is not subject to SLO burn; always "within".
        r = slo.evaluate_observation("_unmatched", 999.0)
        assert r.within_target is True
        assert r.target_seconds == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Bucket-snapshot evaluator — used by the scheduled job
# ─────────────────────────────────────────────────────────────────────────────


class TestBucketSnapshotEvaluator:
    """``compliance_from_buckets()`` is what a scheduled job calls
    to publish ``cortex_slo_compliance{route,percentile}`` gauges.
    It takes a cumulative bucket-count snapshot and returns the
    fraction of observations within the P99 target."""

    def test_all_within_target(self):
        # 100 observations, all in the 0.01..0.05 bucket range.
        # workspace P99 is 0.50, so 100% within.
        bucket_counts = {
            0.01: 0,
            0.025: 10,
            0.05: 50,
            0.10: 100,  # cumulative
        }
        ratio = slo.compliance_from_buckets("workspace", bucket_counts, 100)
        assert ratio == 1.0, f"all-100% should give 1.0, got {ratio}"

    def test_all_outside_target(self):
        # 100 observations, all in the >2.5 bucket. workspace P99
        # is 0.50, so 0% within.
        bucket_counts = {
            0.01: 0,
            0.025: 0,
            0.05: 0,
            0.10: 0,
            0.25: 0,
            0.50: 0,
            1.0: 0,
            2.5: 0,
            5.0: 0,
            10.0: 100,
        }
        ratio = slo.compliance_from_buckets("workspace", bucket_counts, 100)
        assert ratio == 0.0, f"all-0% should give 0.0, got {ratio}"

    def test_partial_compliance(self):
        # 100 observations, 80 within the 0.50s boundary, 20 over.
        # Cumulative count at le=0.50 should be 80.
        bucket_counts = {
            0.01: 30,
            0.025: 50,
            0.05: 60,
            0.10: 70,
            0.25: 75,
            0.50: 80,  # 80 within
            1.0: 90,
            2.5: 100,
            5.0: 100,
            10.0: 100,
        }
        ratio = slo.compliance_from_buckets("workspace", bucket_counts, 100)
        assert ratio == pytest.approx(0.8), (
            f"Expected 0.8, got {ratio}. The boundary used is the largest le ≤ P99 target."
        )

    def test_realtime_tight_compliance(self):
        # realtime P99 is 0.20. Same data, different family.
        bucket_counts = {
            0.01: 30,
            0.025: 50,
            0.05: 60,
            0.10: 70,
            0.25: 100,  # all within 0.20 boundary... no, 0.20 is the target
        }
        # The largest le <= 0.20 is 0.10 → 70/100 = 0.7
        ratio = slo.compliance_from_buckets("realtime", bucket_counts, 100)
        assert ratio == pytest.approx(0.7)

    def test_empty_buckets_returns_one(self):
        # No traffic = no burn = vacuously compliant.
        bucket_counts = {}
        ratio = slo.compliance_from_buckets("workspace", bucket_counts, 0)
        assert ratio == 1.0

    def test_unknown_family_returns_one(self):
        # A family not in LATENCY_TARGETS is not subject to burn.
        ratio = slo.compliance_from_buckets("_unmatched", {0.50: 0}, 100)
        assert ratio == 1.0

    def test_compliance_bounded_zero_to_one(self):
        # Defensive: even if the caller passes a > total bucket
        # count (which would be a bug in the snapshot reader), the
        # function must not return a value outside [0, 1].
        bucket_counts = {0.50: 200}  # corrupt: cumulative > total
        ratio = slo.compliance_from_buckets("workspace", bucket_counts, 100)
        assert 0.0 <= ratio <= 1.0
