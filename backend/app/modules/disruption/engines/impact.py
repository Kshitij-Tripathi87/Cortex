"""Business impact engine — 6 components per Conflict B resolution.

Calculates the six required business-impact components from a completed
propagation result plus the supply-chain snapshot. Every number is traceable
to a dataset row or explicit formula.

Design rules:
  * Produces exactly 6 named impact components — never "revenue at risk" alone.
  * All aggregations are deterministic; order is controlled via sorted tuples.
  * Overall score (0–100) is a weighted linear combination of normalized
    components.
  * "Revenue impact" is product of affected quantity and unit price.
  * "Margin" is derived from revenue × margin_pct.
  * "Penalty exposure" uses late_delivery_penalty_pct from customer records.
  * "Working capital" is computed from affected inventory units and a
    documented per-unit cost assumption.
"""

from __future__ import annotations

from uuid import UUID

from app.modules.disruption.engines.types import (
    AffectedOrder,
    AffectedProduct,
    AffectedWarehouse,
    BusinessImpactScore,
    CustomerData,
    ProductData,
    PropagationResult,
    SupplyChainSnapshot,
)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration (documented, tunable per pilot)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MARGIN_PCT: float = 0.30  # fallback for products without explicit margin
DEFAULT_UNIT_COST: float = 25.0  # fallback USD cost per component unit
DEFAULT_PENALTY_PCT: float = 0.02  # fallback late-delivery penalty share
DEFAULT_UNIT_PRICE: float = 50.0  # fallback unit price when absent from product

# Weights for the overall Business Impact Score (0–100):
_WEIGHT: dict[str, float] = {
    "revenue": 0.30,
    "margin": 0.20,
    "penalty": 0.15,
    "working": 0.10,
    "customer": 0.15,
    "operational": 0.10,
}

# Normalization baselines — at which a raw value reaches ~0.5:
_NORM_BASELINE_REVENUE: float = 5_000_000.0  # USD
_CUSTOMER_BASELINE: int = 50  # unique affected customers


def compute_business_impact(
    snapshot: SupplyChainSnapshot,
    propagation_result: PropagationResult,
) -> BusinessImpactScore:
    """Return the 6-component Business Impact Score (Conflict B resolution)."""

    product_by_id: dict[UUID, ProductData] = {p.id: p for p in snapshot.products}
    customer_by_id: dict[UUID, CustomerData] = {c.id: c for c in snapshot.customers}

    orders_at_risk = propagation_result.open_orders_at_risk

    revenue = _calc_revenue(orders_at_risk, product_by_id)
    margin = _calc_margin(orders_at_risk, product_by_id)
    penalty = _calc_penalty(orders_at_risk, product_by_id, customer_by_id)
    working = _calc_working_capital(propagation_result.affected_warehouses)
    custom_imp = _calc_customer_impact(orders_at_risk)
    oper_imp = _calc_operational_impact(propagation_result.affected_products)

    overall = _aggregate_overall(revenue, margin, penalty, working, custom_imp, oper_imp)

    formula_text = (
        "Weighted linear mean of 6 normalized components: "
        "revenue 0.30, margin 0.20, penalty 0.15, working_capital 0.10, "
        "customer 0.15, operational 0.10. Scale 0–100."
    )

    return BusinessImpactScore(
        revenue_risk_usd=revenue,
        margin_risk_usd=margin,
        penalty_exposure_usd=penalty,
        working_capital_impact_usd=working,
        customer_impact_score=custom_imp,
        operational_impact_score=oper_imp,
        overall_score=overall,
        formula=formula_text,
    )


# ── individual calculations ──


def _calc_revenue(
    orders: tuple[AffectedOrder, ...],
    product_by_id: dict[UUID, ProductData],
) -> float:
    total = 0.0
    for o in orders:
        pu = _unit_price(o.product_id, product_by_id)
        total += o.quantity * pu
    return round(total, 2)


def _calc_margin(
    orders: tuple[AffectedOrder, ...],
    product_by_id: dict[UUID, ProductData],
) -> float:
    total = 0.0
    for o in orders:
        pu = _unit_price(o.product_id, product_by_id)
        margin_pct = _get_margin(o.product_id, product_by_id)
        total += o.quantity * pu * margin_pct
    return round(total, 2)


def _calc_penalty(
    orders: tuple[AffectedOrder, ...],
    product_by_id: dict[UUID, ProductData],
    customer_by_id: dict[UUID, CustomerData],
) -> float:
    total = 0.0
    for order in orders:
        pu = _unit_price(order.product_id, product_by_id)
        penalty_pct = (
            customer_by_id[order.customer_id].late_delivery_penalty_pct
            if order.customer_id in customer_by_id
            else DEFAULT_PENALTY_PCT
        )
        total += (order.quantity * pu) * penalty_pct
    return round(total, 2)


def _calc_working_capital(
    warehouses: tuple[AffectedWarehouse, ...],
) -> float:
    total = 0.0
    for wh in warehouses:
        total += wh.quantity * DEFAULT_UNIT_COST
    return round(total, 2)


def _calc_customer_impact(
    orders: tuple[AffectedOrder, ...],
) -> float:
    unique = len({c.customer_id for c in orders})
    if unique == 0:
        return 0.0
    return min(1.0, unique / _CUSTOMER_BASELINE)


def _calc_operational_impact(
    products: tuple[AffectedProduct, ...],
) -> float:
    num = len(products)
    if num == 0:
        return 0.0
    return min(1.0, num / 50)


def _aggregate_overall(
    reve: float,
    marg: float,
    pen: float,
    work: float,
    cust: float,
    oper: float,
) -> float:
    normed = (
        _WEIGHT["revenue"] * _norm(reve, _NORM_BASELINE_REVENUE)
        + _WEIGHT["margin"] * _norm(marg, _NORM_BASELINE_REVENUE * 0.5)
        + _WEIGHT["penalty"] * _norm(pen, _NORM_BASELINE_REVENUE * 0.1)
        + _WEIGHT["working"] * _norm(work, _NORM_BASELINE_REVENUE * 0.2)
        + _WEIGHT["customer"] * cust
        + _WEIGHT["operational"] * oper
    ) * 100.0
    return round(min(100.0, max(0.0, normed)), 4)


def _norm(value: float, baseline: float) -> float:
    """Sigmoid-ish value compressor 0-1."""
    ratio = value / baseline if baseline > 0 else 0.0
    if ratio <= 0:
        return 0.0
    return min(1.0, ratio / (1.0 + ratio))


def _unit_price(prod_id: UUID, products: dict[UUID, ProductData]) -> float:
    if prod_id in products and products[prod_id].unit_price is not None:
        return max(0.0, products[prod_id].unit_price)
    return DEFAULT_UNIT_PRICE


def _get_margin(prod_id: UUID, products: dict[UUID, ProductData]) -> float:
    if prod_id in products and products[prod_id].margin_pct > 0:
        return max(0.0, min(1.0, products[prod_id].margin_pct))
    return DEFAULT_MARGIN_PCT


__all__ = ["compute_business_impact", "DEFAULT_MARGIN_PCT", "DEFAULT_UNIT_COST"]
