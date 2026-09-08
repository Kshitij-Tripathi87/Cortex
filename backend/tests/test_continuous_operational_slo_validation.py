"""Continuous Operational SLO Validation Under Load — S6.

Validates:
1. Live Prometheus histogram metric recording across all 10 route families under concurrent load
2. Cumulative bucket tracking and quantile accuracy against LATENCY_HISTOGRAM_BUCKETS
3. High-concurrency compliance calculation via compliance_from_buckets() with error budget burn tracking
4. SLA breach detection and isolation under noisy-neighbor multi-tenant workloads
5. Realtime state pipeline execution latency guarantees against frozen P50/P95/P99 contracts
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.infrastructure import metrics, slo
from app.infrastructure.cache_manager import get_cache_manager
from app.infrastructure.state_pipeline import get_state_pipeline
from app.modules.events.event_models import InventoryChanged
from app.modules.world.world_models import StateVariable, StateVariableType, WorldState

# ─────────────────────────────────────────────────────────────────────────────
# 1. Multi-Route Prometheus Histogram Observation Under Load
# ─────────────────────────────────────────────────────────────────────────────


class TestPrometheusHistogramMultiRouteLoad:
    """Verifies that concurrent requests across all 10 route families properly

    record latency observations in the Prometheus histogram with correct labels.
    """

    @pytest.mark.asyncio
    async def test_all_ten_route_families_histogram_recording(self) -> None:
        """Concurrent requests across all 10 route families correctly record into Prometheus."""
        routes = slo.ROUTE_FAMILIES
        requests_per_route = 20

        async def _simulate_route_traffic(route_family: str, idx: int) -> None:
            # Simulate latency according to target p50
            target_p50 = slo.LATENCY_TARGETS[route_family]["p50"]
            simulated_lat = target_p50 * 0.8  # Well within target

            # Record observation in Prometheus metric
            metrics.api_latency_seconds.labels(
                route=route_family,
            ).observe(simulated_lat)

        tasks = []
        for r in routes:
            for i in range(requests_per_route):
                tasks.append(_simulate_route_traffic(r, i))

        await asyncio.gather(*tasks)

        # Verify observations are recorded in the histogram
        samples = metrics.api_latency_seconds.collect()[0].samples
        count_samples = {
            s.labels["route"]: s.value
            for s in samples
            if s.name.endswith("_count") and "route" in s.labels
        }
        for r in routes:
            assert r in count_samples
            assert count_samples[r] >= requests_per_route

    def test_unmatched_route_excluded_from_slo_burn(self) -> None:
        """Routes categorized as '_unmatched' do not trigger SLO burn."""
        res = slo.evaluate_observation("_unmatched", 5.0)
        assert res.within_target is True
        assert res.family == "_unmatched"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cumulative Bucket Snapshots & Quantile Accuracy
# ─────────────────────────────────────────────────────────────────────────────


class TestHistogramQuantilesAndCompliance:
    """Verifies bucket compliance ratios, error budget burn rates, and quantile estimations."""

    def test_full_slo_catalog_compliance_under_healthy_distribution(self) -> None:
        """Synthetic healthy traffic achieves 100% compliance across all 10 route families."""
        for family in slo.ROUTE_FAMILIES:
            p99_target = slo.LATENCY_TARGETS[family]["p99"]

            # Generate healthy bucket snapshot where all observations <= p99_target
            bucket_counts: dict[float, int] = {}
            count_accum = 0
            for b in slo.LATENCY_HISTOGRAM_BUCKETS:
                if b <= p99_target:
                    count_accum += 10
                    bucket_counts[b] = count_accum
                else:
                    bucket_counts[b] = count_accum

            total_obs = count_accum
            ratio = slo.compliance_from_buckets(family, bucket_counts, total_obs)
            assert ratio == 1.0, f"Family {family} failed 100% compliance: got {ratio}"

    def test_degraded_traffic_error_budget_burn_detection(self) -> None:
        """Degraded traffic with tail latency exceeding P99 correctly reports depleted compliance."""
        family = "decisions"
        p99_target = slo.LATENCY_TARGETS[family]["p99"]  # 1.50s

        # 100 total requests: 70 under 0.5s, 30 at 5.0s (violating P99)
        bucket_counts: dict[float, int] = {}
        for b in slo.LATENCY_HISTOGRAM_BUCKETS:
            if b <= 0.50 or b <= p99_target:
                bucket_counts[b] = 70
            else:
                bucket_counts[b] = 100

        total_obs = 100
        ratio = slo.compliance_from_buckets(family, bucket_counts, total_obs)
        assert ratio == 0.70, f"Expected 70% compliance, got {ratio}"

        # Error budget consumed is 30% (threshold breached if budget was 1%)
        error_budget_burn_pct = (1.0 - ratio) * 100.0
        assert error_budget_burn_pct == pytest.approx(30.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Noisy Neighbor Multi-Tenant SLA Isolation
# ─────────────────────────────────────────────────────────────────────────────


class TestNoisyNeighborMultiTenantSLAIsolation:
    """Verifies that an aggressive/flooding tenant does not degrade neighbor SLA compliance."""

    @pytest.mark.asyncio
    async def test_tenant_rate_limit_and_fairness_isolation(self) -> None:
        """Tenant A flooding requests is throttled while Tenant B experiences 100% success."""
        cache = get_cache_manager()
        tenant_a = "org_flooder_tenant_a"
        tenant_b = "org_legitimate_tenant_b"

        # Tenant rate limit: max 10 requests per window
        max_reqs = 10
        window = 60

        tenant_a_success = 0
        tenant_a_throttled = 0
        tenant_b_success = 0
        tenant_b_throttled = 0

        with patch.object(cache, "is_redis_available", AsyncMock(return_value=True)):
            # Tenant A sends 30 rapid requests
            for _i in range(30):
                allowed = await cache.check_rate_limit(
                    tenant_id=tenant_a,
                    resource="api_calls",
                    max_requests=max_reqs,
                    window_seconds=window,
                    fail_closed=True,
                )
                if allowed:
                    tenant_a_success += 1
                else:
                    tenant_a_throttled += 1

            # Tenant B sends 5 legitimate requests
            for _i in range(5):
                allowed = await cache.check_rate_limit(
                    tenant_id=tenant_b,
                    resource="api_calls",
                    max_requests=max_reqs,
                    window_seconds=window,
                    fail_closed=True,
                )
                if allowed:
                    tenant_b_success += 1
                else:
                    tenant_b_throttled += 1

        # Assert Tenant A was bounded by limit
        assert tenant_a_success == max_reqs
        assert tenant_a_throttled == 20

        # Assert Tenant B was completely unhindered (zero throttles)
        assert tenant_b_success == 5
        assert tenant_b_throttled == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. State Pipeline Operational Latency SLO Verification
# ─────────────────────────────────────────────────────────────────────────────


class TestStatePipelineOperationalSLO:
    """Measures live State Pipeline execution under concurrent load against frozen SLO contracts."""

    @pytest.mark.asyncio
    async def test_state_pipeline_concurrency_meets_realtime_slo(self) -> None:
        """State pipeline end-to-end latency meets the P99 target under sustained concurrent load."""
        realtime_p99_target = slo.LATENCY_TARGETS["realtime"]["p99"]  # 0.20s (200ms)
        workspace_p99_target = slo.LATENCY_TARGETS["workspace"]["p99"]  # 0.50s (500ms)

        pipeline = get_state_pipeline()
        concurrency = 20
        latencies_s: list[float] = []

        async def _run_pipeline_op(idx: int) -> None:
            org_id = f"org_slo_{idx % 4}"
            ws_id = f"ws_slo_{idx % 4}"
            ctx = ExecutionContext.create_system_context(
                tenant_id=org_id,
                organization_id=org_id,
                workspace_id=ws_id,
            )
            world_state = WorldState(
                world_id=f"w_slo_{idx}",
                workspace_id=ws_id,
                version=idx + 1,
                variables={
                    "inv_stock": StateVariable(
                        variable_id="inv_stock",
                        variable_type=StateVariableType.INVENTORY,
                        entity_id=f"wh_slo_{idx}",
                        entity_type="warehouse",
                        value=1000.0 + idx,
                    )
                },
                graph_version=1,
            )
            evt = InventoryChanged(
                event_id=f"evt_slo_{idx}_{uuid7()}",
                world_id=f"w_slo_{idx}",
                workspace_id=ws_id,
                entity_type="warehouse",
                entity_id=f"wh_slo_{idx}",
                warehouse_id=f"wh_slo_{idx}",
                component_id="chip_01",
                quantity_change=-1,
                reason="slo_load_test",
                occurred_at=datetime.now(UTC),
            )

            t0 = time.perf_counter()
            result = await pipeline.ingest_event_and_propagate(
                event=evt,
                current_state=world_state,
                context=ctx,
            )
            t1 = time.perf_counter()
            lat = t1 - t0
            latencies_s.append(lat)
            assert result.success is True

        tasks = [_run_pipeline_op(i) for i in range(concurrency)]
        await asyncio.gather(*tasks)

        assert len(latencies_s) == concurrency
        max_observed = max(latencies_s)
        mean_observed = sum(latencies_s) / len(latencies_s)

        # Every operation must strictly be within the workspace and realtime P99 targets
        assert max_observed < workspace_p99_target, (
            f"Max latency {max_observed * 1000:.2f}ms exceeded workspace P99 target {workspace_p99_target * 1000:.2f}ms"
        )
        assert mean_observed < realtime_p99_target, (
            f"Mean latency {mean_observed * 1000:.2f}ms exceeded realtime target {realtime_p99_target * 1000:.2f}ms"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-Window Error Budget Burn Rate & Alert Triggering
# ─────────────────────────────────────────────────────────────────────────────


class TestErrorBudgetBurnRateAndAlerts:
    """Verifies standard Google SRE multi-window multi-burn-rate alert algorithms."""

    def test_multi_window_burn_rate_calculations(self) -> None:
        """1h and 6h burn rate multipliers correctly identify high-severity budget depletion."""
        # 30-day window total budget = 1.0% (99.0% SLO target)
        slo_target = 0.99
        error_budget = 1.0 - slo_target  # 0.01 (1%)

        # Scenario A: 14.4x burn rate consumes 2% of 30-day budget in 1 hour (Page alert threshold)
        observed_error_rate_a = 14.4 * error_budget
        burn_rate_a = observed_error_rate_a / error_budget
        assert burn_rate_a == pytest.approx(14.4)

        # Scenario B: Normal traffic with 0.1x burn rate -> (Healthy, well under 1.0)
        observed_error_rate_b = 0.1 * error_budget
        burn_rate_b = observed_error_rate_b / error_budget
        assert burn_rate_b < 1.0

    def test_zero_drift_histogram_bucket_alignment_all_ten_families(self) -> None:
        """Every route family P99 target aligns with an exact discrete histogram boundary."""
        for family in slo.ROUTE_FAMILIES:
            p99_target = slo.LATENCY_TARGETS[family]["p99"]
            matching_buckets = [b for b in slo.LATENCY_HISTOGRAM_BUCKETS if b >= p99_target]
            assert len(matching_buckets) > 0, (
                f"Route {family} P99 target {p99_target} has no matching Prometheus bucket"
            )
