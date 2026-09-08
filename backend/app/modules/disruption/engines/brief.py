"""Morning Brief orchestrator — runs all engines and persists an ImpactReport.

This is the single entry-point that ties together the five pure-functional
engines (propagation, impact, confidence, recommendations, timeline) and
converts the raw inputs (``SupplyChainSnapshot`` + ``DisruptionScenario``)
into an immutable, serializable ``MorningBrief`` ready for persistence as
``analytics.impact_reports``.

Design (ADR-0003: Deterministic MVP):
  * ``run_morning_brief`` accepts only data — no session, no DI, no async.
  * The caller (API endpoint / backtest runner) owns DB access.
  * Each engine runs in sequence; the output of propagation feeds impact and
    confidence, etc.
  * ``failures`` records soft failures (e.g., missing supplier lookup) without
    aborting the run — the Brief always returns, and failures are surfaced
    to the operator.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.common.ids import uuid7
from app.modules.disruption.engines.confidence import compute_confidence
from app.modules.disruption.engines.impact import compute_business_impact
from app.modules.disruption.engines.propagation import propagate
from app.modules.disruption.engines.recommendations import recommend
from app.modules.disruption.engines.timeline import build_timeline
from app.modules.disruption.engines.types import (
    DisruptionScenario,
    MorningBrief,
    SupplyChainSnapshot,
)


def run_morning_brief(
    snapshot: SupplyChainSnapshot,
    scenario: DisruptionScenario,
) -> MorningBrief:
    """Run all five engines sequentially and return a MorningBrief."""
    failures: list[str] = []
    computation_run_id = UUID(uuid7())

    supplier = snapshot.supplier_by_id(scenario.supplier_id)
    if supplier is None:
        failures.append(f"Supplier {scenario.supplier_id} not found in workspace snapshot.")

    # 1. Propagation
    propagation = propagate(snapshot, scenario.supplier_id)

    # 2. Business Impact
    biz_impact = compute_business_impact(snapshot, propagation)

    # 3. Decision Confidence
    confidence = compute_confidence(snapshot, propagation)

    # 4. Recommendations
    rec_set = recommend(propagation, biz_impact)

    # 5. Timeline
    timeline = build_timeline(propagation, scenario)

    evidence_keys = tuple(
        sorted(
            set(str(c.component_id) for c in propagation.affected_components)
            | set(str(p.product_id) for p in propagation.affected_products)
            | set(str(o.order_id) for o in propagation.open_orders_at_risk)
        )
    )

    return MorningBrief(
        workspace_id=scenario.workspace_id,
        scenario=scenario,
        propagation=propagation,
        business_impact=biz_impact,
        confidence=confidence,
        recommendations=rec_set,
        timeline=timeline,
        generated_at=datetime.now(UTC),
        computation_run_id=computation_run_id,
        evidence_keys=evidence_keys,
        failures=tuple(failures),
    )


__all__ = ["run_morning_brief"]
