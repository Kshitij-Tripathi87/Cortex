"""Performance Budgets — CI-enforced latency/throughput targets per subsystem.

Budgets are from docs/21-performance-budgets.md and enforced in CI.
"""

from __future__ import annotations

from dataclasses import dataclass

# Subsystem budgets (p95 unless noted)
BUDGETS = {
    "upload": {
        "http_handling_p95_ms": 1000,
        "validation_throughput_mbps": 5.0,
        "job_duration_max_s": 30,
        "file_size_limit_mb": 200,
    },
    "profiling": {
        "throughput_rows_per_sec": 3000,
        "claim_write_p95_ms": 50,
        "evidence_hash_compute_p95_ms": 4000,
    },
    "canonicalization": {
        "attribute_promotion_p95_ms": 50,
        "entity_resolution_10k_s": 30,
        "conflict_detection_10k_s": 20,
    },
    "graph": {
        "node_read_p95_ms": 100,
        "neighbors_2hop_10k_p95_ms": 300,
        "paths_p95_ms": 500,
        "impact_p95_ms": 600,
        "history_p95_ms": 250,
        "diff_p95_ms": 2000,
        "snapshot_build_100k_s": 15,
        "snapshot_seal_verify_p95_ms": 3000,
        "readiness_decision_p95_ms": 5000,
    },
    "intelligence": {
        "signal_detection_500k_s": 30,
        "ml_candidate_lookup_s": 10,
    },
    "scenarios": {
        "creation_p95_ms": 5000,
        "branch_snapshot_recompute_s": 10,
        "compare_p95_ms": 3000,
    },
    "recommendations": {
        "single_policy_p95_ms": 2000,
        "full_sweep_500k_s": 45,
    },
    "decisions": {
        "record_p95_ms": 200,
        "outcome_eval_1k_s": 60,
    },
    "audit": {
        "event_insert_p95_ms": 5,
        "chain_verify_24h_s": 30,
        "batch_append_1k_ms": 250,
    },
    "frontend": {
        "api_read_p95_ms": 300,
        "api_write_p95_ms": 150,
        "tti_ms": 1800,
        "graph_render_10k_ms": 2000,
        "route_transition_ms": 400,
    },
    "storage": {
        "put_200mb_s": 10,
        "snapshot_artifact_500mb_s": 20,
        "backup_daily_incremental_min": 30,
    },
    "capacity": {
        "entities_per_workspace": 1_000_000,
        "edges_per_workspace": 5_000_000,
        "open_conflicts_per_workspace": 5000,
        "snapshots_retention_days": 90,
        "api_rpm_per_tenant": 10_000,
    },
}


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of a budget check."""

    subsystem: str
    metric: str
    value: float
    target: float
    alert: float
    breach: float
    status: str  # ok | alert | breach


def check_budget(subsystem: str, metric: str, value: float) -> BudgetCheckResult:
    """Check a measured value against its budget."""
    subsystem_budgets = BUDGETS.get(subsystem, {})
    if metric not in subsystem_budgets:
        return BudgetCheckResult(
            subsystem=subsystem,
            metric=metric,
            value=value,
            target=0.0,
            alert=0.0,
            breach=0.0,
            status="unknown",
        )

    target = subsystem_budgets[metric]
    # Alert at 80% of target, breach at 100%
    alert = target * 0.8
    breach = target

    if value > breach:
        status = "breach"
    elif value > alert:
        status = "alert"
    else:
        status = "ok"

    return BudgetCheckResult(
        subsystem=subsystem,
        metric=metric,
        value=value,
        target=target,
        alert=alert,
        breach=breach,
        status=status,
    )


def format_budget_report(results: list[BudgetCheckResult]) -> str:
    """Format budget check results for CI output."""
    lines = ["# Performance Budget Report\n"]
    for r in results:
        icon = "✅" if r.status == "ok" else "⚠️" if r.status == "alert" else "❌"
        lines.append(
            f"{icon} {r.subsystem}.{r.metric}: {r.value:.2f} (target: {r.target:.2f}, alert: {r.alert:.2f}, breach: {r.breach:.2f})"
        )

    breaches = [r for r in results if r.status == "breach"]
    if breaches:
        lines.append(f"\n🚨 {len(breaches)} budget breach(es) — release blocked")

    return "\n".join(lines)
