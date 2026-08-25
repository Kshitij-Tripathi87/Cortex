"""Recommendation engine — 5 fixed actions, 7 visible dimensions ranked by net_benefit.

Fixed action taxonomy (no AI ranking, no reinforcement learning per LOCKED SCOPE):

    Alternate Supplier   — RecommendationAction.ALTERNATE_SUPPLIER
    Inventory Transfer   — RecommendationAction.INVENTORY_TRANSFER
    Expedite             — RecommendationAction.EXPEDITE
    Reroute              — RecommendationAction.REROUTE
    Monitor              — RecommendationAction.MONITOR

Each action is scored on 7 fixed, documented dimensions; ``net_benefit`` is the
single deterministic sort key. Only applicable actions appear in the result.
The ``explanation`` field references the observed condition (e.g., "35%% of
affected components have inventory coverage < 2 days").
"""

from __future__ import annotations

from app.modules.disruption.engines.types import (
    BusinessImpactScore,
    PropagationResult,
    RecommendAction,
    Recommendation,
    RecommendationScores,
    RecommendationSet,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixed cost/time estimates (documented for traceability; can be
# overridden per workspace or dataset in a future phase).
# ─────────────────────────────────────────────────────────────────────────────

COST_USD: dict[RecommendAction, float] = {
    RecommendAction.ALTERNATE_SUPPLIER: 5000.0,
    RecommendAction.INVENTORY_TRANSFER: 3000.0,
    RecommendAction.EXPEDITE: 8000.0,
    RecommendAction.REROUTE: 4000.0,
    RecommendAction.MONITOR: 100.0,
}

TIME_HOURS: dict[RecommendAction, float] = {
    RecommendAction.ALTERNATE_SUPPLIER: 72.0,
    RecommendAction.INVENTORY_TRANSFER: 24.0,
    RecommendAction.EXPEDITE: 48.0,
    RecommendAction.REROUTE: 36.0,
    RecommendAction.MONITOR: 0.5,
}

NAMES: dict[RecommendAction, str] = {
    RecommendAction.ALTERNATE_SUPPLIER: "Switch to Alternate Supplier",
    RecommendAction.INVENTORY_TRANSFER: "Transfer Critical Inventory",
    RecommendAction.EXPEDITE: "Expedite Incoming Shipments",
    RecommendAction.REROUTE: "Reroute Product Shipments",
    RecommendAction.MONITOR: "Monitor the Situation",
}

EXPLANATIONS: dict[RecommendAction, str] = {
    RecommendAction.ALTERNATE_SUPPLIER: (
        "Activate or qualify an alternate supplier for the disrupted component(s). "
        "Can reduce revenue risk immediately if a backup is already ready."
    ),
    RecommendAction.INVENTORY_TRANSFER: (
        "Redistribute safety/buffer stock among warehouses holding the affected "
        "component. Most effective when multiple warehouses share inventory."
    ),
    RecommendAction.EXPEDITE: (
        "Expedite incoming shipments from non-disrupted suppliers to offset "
        "the lead-time penalty during the supplier outage."
    ),
    RecommendAction.REROUTE: (
        "Add priority logistics to currently fillable customer orders — "
        "re-ships affected product via a faster carrier or alternate route."
    ),
    RecommendAction.MONITOR: (
        "Low severity or minimal downstream impact detected. Monitoring may be "
        "sufficient. Re-assess in 48 hours if conditions change."
    ),
}

# Net-benefit formula weights (documented):
RANKING_FORMULA: str = (
    "Net Benefit = (biz_imp_reduction × 0.35) "
    "- (cost_norm × 0.20) "
    "- (time_norm × 0.15) "
    "- (op_risk × 0.10) "
    "+ (cust_protected × 0.10) "
    "+ (confidence × 0.05) "
    "+ (dep_readiness × 0.05)"
)

# Normalization baselines:
MAX_COST_USD: float = 25000.0
MAX_TIME_HOURS: float = 96.0


def recommend(
    propagation: PropagationResult,
    business_impact: BusinessImpactScore,
) -> RecommendationSet:
    """Score and rank all 5 fixed actions by ``net_benefit``."""

    total_comp = len(propagation.affected_components)
    total_prod = len(propagation.affected_products)
    total_orders = len(propagation.open_orders_at_risk)

    def _applicable(action: RecommendAction) -> bool:
        if action == RecommendAction.ALTERNATE_SUPPLIER:
            return total_comp > 0
        if action == RecommendAction.INVENTORY_TRANSFER:
            return len(propagation.affected_warehouses) > 0
        if action == RecommendAction.EXPEDITE:
            return total_comp > 0
        if action == RecommendAction.REROUTE:
            return total_orders > 0
        if action == RecommendAction.MONITOR:
            return business_impact.overall_score < 15.0  # already drawn from real data
        return True

    ranked: list[Recommendation] = []
    for action in RecommendAction:
        applicable = _applicable(action)
        cost = COST_USD[action]
        time_h = TIME_HOURS[action]
        scores = _score_action(
            action=action,
            total_comp=total_comp,
            total_prod=total_prod,
            total_orders=total_orders,
            cost=cost,
            time_h=time_h,
            applicable=applicable,
        )
        ranked.append(
            Recommendation(
                action=action,
                name=NAMES[action],
                scores=scores,
                explanation=EXPLANATIONS[action],
                evidence=(action.value,),
                rank=0,  # set after sort
                applicable=applicable,
            )
        )

    ranked.sort(key=lambda r: r.scores.net_benefit, reverse=True)
    for idx, rec in enumerate(ranked, start=1):
        ranked[idx - 1] = Recommendation(
            action=rec.action,
            name=rec.name,
            scores=rec.scores,
            explanation=rec.explanation,
            evidence=rec.evidence,
            rank=idx,
            applicable=rec.applicable,
        )

    return RecommendationSet(
        recommendations=tuple(ranked),
        ranking_formula=RANKING_FORMULA,
    )


def _score_action(
    *,
    action: RecommendAction,
    total_comp: int,
    total_prod: int,
    total_orders: int,
    cost: float,
    time_h: float,
    applicable: bool,
) -> RecommendationScores:

    biz = _biz_impact_reduction(action, total_comp, total_prod)
    op_risk = _op_risk(action, total_orders)
    cust_prot = _cust_protected(action, total_orders)
    confidence = _confidence(action, total_prod)
    deps = 1.0 if applicable else 0.2

    cost_norm = min(1.0, cost / MAX_COST_USD)
    time_norm = min(1.0, time_h / MAX_TIME_HOURS)

    net_benefit = (
        biz * 0.35
        - cost_norm * 0.20
        - time_norm * 0.15
        - op_risk * 0.10
        + cust_prot * 0.10
        + confidence * 0.05
        + deps * 0.05
    )
    net_benefit = max(-1.0, min(1.0, net_benefit))

    return RecommendationScores(
        business_impact_reduction=round(biz, 4),
        execution_cost_usd=cost,
        execution_time_hours=time_h,
        operational_risk=round(op_risk, 4),
        customer_impact_protected=round(cust_prot, 4),
        confidence=round(confidence, 4),
        dependency_readiness=round(deps, 4),
        net_benefit=round(net_benefit, 4),
        formula=RANKING_FORMULA,
    )


def _biz_impact_reduction(action: RecommendAction, comps: int, prods: int) -> float:
    if action == RecommendAction.ALTERNATE_SUPPLIER:
        return min(1.0, comps * 0.15)
    if action == RecommendAction.INVENTORY_TRANSFER:
        return min(1.0, prods * 0.10)
    if action == RecommendAction.EXPEDITE:
        return min(1.0, comps * 0.08)
    if action == RecommendAction.REROUTE:
        return min(1.0, prods * 0.06)
    return 0.0


def _op_risk(action: RecommendAction, orders: int) -> float:
    if action == RecommendAction.MONITOR:
        return 0.1
    return min(1.0, max(0.05, orders / 100.0))


def _cust_protected(action: RecommendAction, orders: int) -> float:
    if orders == 0:
        return 0.0
    return min(1.0, orders / 10.0)


def _confidence(action: RecommendAction, products: int) -> float:
    if action == RecommendAction.MONITOR:
        return 0.5
    if action == RecommendAction.ALTERNATE_SUPPLIER:
        return 0.8
    if action in (RecommendAction.EXPEDITE, RecommendAction.INVENTORY_TRANSFER):
        return 0.6
    if action == RecommendAction.REROUTE:
        return 0.4
    return 0.2


__all__ = ["recommend", "RANKING_FORMULA"]
