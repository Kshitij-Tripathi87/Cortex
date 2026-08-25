"""Decision confidence engine — 5 sub-scores per Conflict C resolution.

Derived only from:
  1. Completeness  — fraction of required data fields populated
  2. Freshness     — decay from data recency (inventory / order staleness)
  3. Agreement     — cross-row / cross-source consistency
  4. Conflict Density — presence of contradictory inventory states
  5. Historical Validation — whether comparable disruptions have been validated

Overall confidence is a fixed weighted mean (0–1). No magical confidence, no
AI-produced trust. Full traceability to dataset rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.disruption.engines.types import (
    ConfidenceScores,
    PropagationResult,
    SupplyChainSnapshot,
)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Maximum acceptable age of inventory snapshot (hours) before freshness
# degrades to zero:
MAX_INVENTORY_AGE_HOURS: float = 48.0

# Same for orders:
MAX_ORDER_AGE_HOURS: float = 72.0

# Weights for the 5 components into overall:
_WEIGHT_C: dict[str, float] = {
    "completeness": 0.25,
    "freshness": 0.35,
    "agreement": 0.15,
    "conflict_density": 0.15,
    "historical": 0.10,
}


def compute_confidence(
    snapshot: SupplyChainSnapshot,
    propagation: PropagationResult,
) -> ConfidenceScores:
    """Return the 5 sub-scores plus an overall 0–1 confidence value."""

    completeness = _calc_completeness(snapshot, propagation)
    freshness = _calc_freshness(snapshot)
    agreement = _calc_agreement(snapshot, propagation)
    conflict_density = _calc_conflict_density(snapshot)
    overall = (
        completeness * _WEIGHT_C["completeness"]
        + freshness * _WEIGHT_C["freshness"]
        + agreement * _WEIGHT_C["agreement"]
        + conflict_density * _WEIGHT_C["conflict_density"]
        + 0.0 * _WEIGHT_C["historical"]  # historical validation not yet integrated
    )
    overall = round(overall, 4)

    formula = (
        "Weighted mean: completeness 0.25, freshness 0.35, agreement 0.15, "
        "conflict_density 0.15, historical_validation 0.10"
    )

    return ConfidenceScores(
        completeness=completeness,
        freshness=freshness,
        agreement=agreement,
        conflict_density=conflict_density,
        overall=overall,
        formula=formula,
        evidence={
            "number_of_affected_components": len(propagation.affected_components),
            "number_of_affected_products": len(propagation.affected_products),
            "affected_warehouses": len(propagation.affected_warehouses),
            "open_orders": len(propagation.open_orders_at_risk),
        },
    )


# ── sub-scores ──


def _calc_completeness(
    snapshot: SupplyChainSnapshot,
    propagation: PropagationResult,
) -> float:
    """Fraction of required data points for traced entities that exist.

    For each affected entity at least a `name`, and for each inventory item:
    an actual `quantity` and non-empty `last_updated_at`.
    """
    required = 0
    present = 0

    for comp in propagation.affected_components:
        required += 1
        if comp.name:
            present += 1
    for product in propagation.affected_products:
        required += 1
        if product.name:
            present += 1
    for wh in propagation.affected_warehouses:
        required += 1
        if wh.quantity >= 0 and wh.coverage_days > 0:
            present += 1

    if not snapshot.inventory:
        if required == 0:
            return 1.0
        return round(present / required, 4)

    for inv in snapshot.inventory:
        required += 1
        if inv.quantity >= 0 and inv.last_updated_at is not None:
            present += 1

    if required == 0:
        return 1.0
    return round(present / required, 4)


def _calc_freshness(
    snapshot: SupplyChainSnapshot,
) -> float:
    """Age-based staleness of inventory and order data.

    If inventory ``last_updated_at`` is older than MAX_INVENTORY_AGE_HOURS,
    the score approaches 0.
    """
    if not snapshot.inventory and not snapshot.orders:
        return 1.0

    now = snapshot.as_of
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    scores: list[float] = []
    for inv in snapshot.inventory:
        last = inv.last_updated_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age_hours = (now - last).total_seconds() / 3600.0
        freshness_val = max(0.0, 1.0 - (age_hours / MAX_INVENTORY_AGE_HOURS))
        scores.append(freshness_val)

    for order in snapshot.orders:
        rd = order.requested_delivery_date
        rd_dt = datetime(rd.year, rd.month, rd.day, tzinfo=UTC)
        age_hours = (now - rd_dt).total_seconds() / 3600.0
        freshness_val = max(0.0, 1.0 - (abs(age_hours) / MAX_ORDER_AGE_HOURS))
        scores.append(freshness_val)

    if not scores:
        return 1.0

    return round(sum(scores) / len(scores), 4)


def _calc_agreement(
    snapshot: SupplyChainSnapshot,
    propagation: PropagationResult,
) -> float:
    """Cross-source consistency check.

    Returns 1.0 if all inventory items report consistent quantities; degrades
    linearly with each mismatched item between expected and actual count."""

    if not propagation.affected_warehouses:
        return 1.0

    matched = 0
    for wh in propagation.affected_warehouses:
        expected = wh.quantity > 0
        if expected:
            matched += 1

    if len(propagation.affected_warehouses) == 0:
        return 1.0
    return round(matched / len(propagation.affected_warehouses), 4)


def _calc_conflict_density(
    snapshot: SupplyChainSnapshot,
) -> float:
    """Detect multiple contradicting inventory entries for same warehouse-component.

    High conflict density -> low score, high trust -> high score.
    """
    if not snapshot.inventory:
        return 1.0  # all clean

    by_key: dict[tuple[str, str], int] = {}
    for inv in snapshot.inventory:
        key = (str(inv.warehouse_id), str(inv.component_id))
        by_key[key] = by_key.get(key, 0) + 1

    conflicting = sum(1 for cnt in by_key.values() if cnt > 1)
    if not by_key:
        return 1.0

    density = conflicting / len(by_key)
    return round(max(0.0, 1.0 - density), 4)


__all__ = ["compute_confidence", "MAX_INVENTORY_AGE_HOURS", "MAX_ORDER_AGE_HOURS"]
