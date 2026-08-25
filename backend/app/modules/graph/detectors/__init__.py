"""Signal detectors — pure functions that produce SignalInstance objects.

Each detector:
  - Consumes EnrichedSnapshot (features + operational context)
  - Returns list[SignalInstance] (may be empty if no signals detected)
  - Is deterministic: same enriched state → same signals
  - Never raises: missing features/context → empty list

Detectors are registered in the SignalEngine and called in priority order.
The engine aggregates all signals, deduplicates by (signal_name, affected_node_ids),
and returns a SignalSnapshot.

Operational context adjusts severity and confidence:
  - Fresh inventory coverage can reduce SPOF severity
  - Stale data degrades confidence
  - Missing required context blocks signal generation
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedNodeState, EnrichedSnapshot
from app.modules.graph.signal_models import (
    SignalCategory as SignalCategory,
)
from app.modules.graph.signal_models import (
    SignalDefinition,
    SignalInstance,
    SignalSeverity,
)
from app.modules.graph.signal_registry import compute_signal_severity, format_explanation


def _adjust_severity_with_context(
    base_severity: SignalSeverity,
    enriched: EnrichedNodeState,
) -> SignalSeverity:
    """Adjust signal severity based on operational context.

    Rules:
    - Fresh inventory coverage can reduce severity by one level
    - Stale operational state degrades confidence (not severity)
    - Critical customer flag can increase severity by one level
    """
    # If fresh inventory with good coverage, reduce severity
    _reduce_map = {0: SignalSeverity.INFO, 1: SignalSeverity.WARNING, 2: SignalSeverity.CRITICAL}
    inv = enriched.inventory if enriched.has_fresh_operational_state else None
    if inv is not None and inv.coverage_days is not None and inv.coverage_days >= 30:
        # Reduce severity by one level
        severity_order = {"blocking": 3, "critical": 2, "warning": 1, "info": 0}
        current_level = severity_order.get(base_severity.value, 0)
        if current_level > 0:
            new_level = current_level - 1
            return _reduce_map[new_level]

    # If critical customer, increase severity
    _increase_map = {
        1: SignalSeverity.WARNING,
        2: SignalSeverity.CRITICAL,
        3: SignalSeverity.BLOCKING,
    }
    biz = enriched.business
    if biz is not None and biz.critical_customer_flag:
        severity_order = {"info": 0, "warning": 1, "critical": 2, "blocking": 3}
        current_level = severity_order.get(base_severity.value, 0)
        new_level = min(3, current_level + 1)
        return _increase_map[new_level]

    return base_severity


def _adjust_confidence_with_context(
    base_confidence: float,
    enriched: EnrichedNodeState,
) -> float:
    """Adjust confidence based on operational context freshness.

    Rules:
    - Fresh operational state: confidence unchanged
    - Degraded freshness: reduce confidence by 20%
    - Stale operational state: reduce confidence by 50%
    - No operational state: reduce confidence by 30%
    """
    if enriched.operational_state is None:
        return max(0.3, base_confidence * 0.7)

    if enriched.has_fresh_operational_state:
        return base_confidence
    elif enriched.has_degraded_operational_state:
        return max(0.3, base_confidence * 0.8)
    elif enriched.has_stale_operational_state:
        return max(0.2, base_confidence * 0.5)

    return base_confidence


def detect_spof_signals(
    snapshot: EnrichedSnapshot,
    definition: SignalDefinition,
) -> list[SignalInstance]:
    """Detect single-point-of-failure signals.

    Triggers when a node's SPOF score exceeds thresholds.
    Severity scales with SPOF score and downstream reach.
    Operational context (inventory coverage, critical customer) adjusts severity.
    """
    signals: list[SignalInstance] = []

    for node_id, enriched in snapshot.by_node.items():
        features = enriched.features
        spof = features.single_point_of_failure
        if spof < 0.3:  # Below info threshold
            continue

        feature_evidence = {
            "single_point_of_failure": spof,
            "downstream_reach": features.downstream_reach,
        }
        base_severity = compute_signal_severity(definition.name, feature_evidence)
        severity = _adjust_severity_with_context(base_severity, enriched)

        # Confidence: SPOF scaled by downstream impact, adjusted for context
        confidence = min(1.0, spof * (1.0 + features.downstream_reach / 10.0))
        confidence = _adjust_confidence_with_context(confidence, enriched)

        explanation = format_explanation(
            definition.explanation_template,
            entity_id=features.entity_id,
            entity_type=features.entity_type,
            spof=spof,
            downstream_reach=features.downstream_reach,
        )

        # Add context note if available
        if enriched.inventory is not None and enriched.inventory.coverage_days is not None:
            explanation += f" Inventory coverage: {enriched.inventory.coverage_days:.1f} days."

        signals.append(
            SignalInstance(
                signal_id=uuid7(),
                signal_name=definition.name,
                signal_version=definition.version,
                workspace_id=snapshot.workspace_id,
                snapshot_version=snapshot.snapshot_version,
                snapshot_hash=snapshot.snapshot_hash,
                severity=severity,
                confidence=round(confidence, 4),
                category=definition.category,
                affected_node_ids=[node_id],
                affected_entity_types=[features.entity_type],
                affected_entity_ids=[features.entity_id],
                propagation_scope=definition.propagation_scope,
                feature_evidence=feature_evidence,
                explanation=explanation,
            )
        )

    return signals


def detect_concentration_signals(
    snapshot: EnrichedSnapshot,
    definition: SignalDefinition,
) -> list[SignalInstance]:
    """Detect concentration risk signals (single-source dependency)."""
    signals: list[SignalInstance] = []

    for node_id, enriched in snapshot.by_node.items():
        features = enriched.features
        risk = features.concentration_risk
        in_deg = features.in_degree

        if risk < 0.5:  # Below info threshold
            continue

        feature_evidence = {
            "concentration_risk": risk,
            "in_degree": in_deg,
        }
        base_severity = compute_signal_severity(definition.name, feature_evidence)
        severity = _adjust_severity_with_context(base_severity, enriched)

        # Confidence: high if concentration is high AND only 1 upstream source
        confidence = risk * (1.0 if in_deg == 1 else 0.5)
        confidence = _adjust_confidence_with_context(confidence, enriched)

        explanation = format_explanation(
            definition.explanation_template,
            entity_id=features.entity_id,
            entity_type=features.entity_type,
            risk=risk,
            in_degree=in_deg,
        )

        signals.append(
            SignalInstance(
                signal_id=uuid7(),
                signal_name=definition.name,
                signal_version=definition.version,
                workspace_id=snapshot.workspace_id,
                snapshot_version=snapshot.snapshot_version,
                snapshot_hash=snapshot.snapshot_hash,
                severity=severity,
                confidence=round(confidence, 4),
                category=definition.category,
                affected_node_ids=[node_id],
                affected_entity_types=[features.entity_type],
                affected_entity_ids=[features.entity_id],
                propagation_scope=definition.propagation_scope,
                feature_evidence=feature_evidence,
                explanation=explanation,
            )
        )

    return signals


def detect_bottleneck_signals(
    snapshot: EnrichedSnapshot,
    definition: SignalDefinition,
) -> list[SignalInstance]:
    """Detect bottleneck signals (high betweenness nodes)."""
    signals: list[SignalInstance] = []

    # Compute max degree across all enriched nodes
    max_degree = (
        max(
            (enriched.features.total_degree for enriched in snapshot.by_node.values()),
            default=1,
        )
        or 1
    )

    for node_id, enriched in snapshot.by_node.items():
        features = enriched.features
        betweenness = features.betweenness
        if betweenness < 0.3:
            continue

        feature_evidence = {
            "betweenness": betweenness,
            "total_degree": features.total_degree,
        }
        base_severity = compute_signal_severity(definition.name, feature_evidence)
        severity = _adjust_severity_with_context(base_severity, enriched)

        # Confidence: betweenness scaled by degree centrality
        confidence = betweenness * (features.total_degree / max_degree)
        confidence = _adjust_confidence_with_context(confidence, enriched)

        explanation = format_explanation(
            definition.explanation_template,
            entity_id=features.entity_id,
            entity_type=features.entity_type,
            betweenness=betweenness,
            degree=features.total_degree,
            upstream_count=features.upstream_reach,
            downstream_count=features.downstream_reach,
        )

        signals.append(
            SignalInstance(
                signal_id=uuid7(),
                signal_name=definition.name,
                signal_version=definition.version,
                workspace_id=snapshot.workspace_id,
                snapshot_version=snapshot.snapshot_version,
                snapshot_hash=snapshot.snapshot_hash,
                severity=severity,
                confidence=round(confidence, 4),
                category=definition.category,
                affected_node_ids=[node_id],
                affected_entity_types=[features.entity_type],
                affected_entity_ids=[features.entity_id],
                propagation_scope=definition.propagation_scope,
                feature_evidence=feature_evidence,
                explanation=explanation,
            )
        )

    return signals


def detect_isolation_signals(
    snapshot: EnrichedSnapshot,
    definition: SignalDefinition,
) -> list[SignalInstance]:
    """Detect isolated nodes (degree == 0)."""
    signals: list[SignalInstance] = []

    for node_id, enriched in snapshot.by_node.items():
        features = enriched.features
        if features.total_degree > 0:
            continue

        feature_evidence = {
            "total_degree": 0,
        }

        # Base severity based on entity type
        if features.entity_type in ("Supplier", "Customer"):
            base_severity = SignalSeverity.CRITICAL
        elif features.entity_type == "Facility":
            base_severity = SignalSeverity.WARNING
        else:
            base_severity = SignalSeverity.INFO

        # Adjust with context
        severity = _adjust_severity_with_context(base_severity, enriched)
        confidence = 1.0  # Certain: degree is exactly 0
        confidence = _adjust_confidence_with_context(confidence, enriched)

        explanation = format_explanation(
            definition.explanation_template,
            entity_id=features.entity_id,
            entity_type=features.entity_type,
        )

        signals.append(
            SignalInstance(
                signal_id=uuid7(),
                signal_name=definition.name,
                signal_version=definition.version,
                workspace_id=snapshot.workspace_id,
                snapshot_version=snapshot.snapshot_version,
                snapshot_hash=snapshot.snapshot_hash,
                severity=severity,
                confidence=round(confidence, 4),
                category=definition.category,
                affected_node_ids=[node_id],
                affected_entity_types=[features.entity_type],
                affected_entity_ids=[features.entity_id],
                propagation_scope=definition.propagation_scope,
                feature_evidence=feature_evidence,
                explanation=explanation,
            )
        )

    return signals


def detect_criticality_signals(
    snapshot: EnrichedSnapshot,
    definition: SignalDefinition,
) -> list[SignalInstance]:
    """Detect high-criticality nodes (broad operational impact)."""
    signals: list[SignalInstance] = []

    for node_id, enriched in snapshot.by_node.items():
        features = enriched.features
        crit = features.criticality
        if crit < 0.3:
            continue

        feature_evidence = {
            "criticality": crit,
            "downstream_reach": features.downstream_reach,
            "upstream_reach": features.upstream_reach,
        }
        base_severity = compute_signal_severity(definition.name, feature_evidence)
        severity = _adjust_severity_with_context(base_severity, enriched)
        confidence = crit  # Direct mapping
        confidence = _adjust_confidence_with_context(confidence, enriched)

        explanation = format_explanation(
            definition.explanation_template,
            entity_id=features.entity_id,
            entity_type=features.entity_type,
            criticality=crit,
            downstream_reach=features.downstream_reach,
            upstream_reach=features.upstream_reach,
        )

        # Add business context if available
        if enriched.business is not None:
            if enriched.business.revenue_at_risk is not None:
                explanation += f" Revenue at risk: ${enriched.business.revenue_at_risk:,.0f}."
            if enriched.business.critical_customer_flag:
                explanation += " Critical customer."

        signals.append(
            SignalInstance(
                signal_id=uuid7(),
                signal_name=definition.name,
                signal_version=definition.version,
                workspace_id=snapshot.workspace_id,
                snapshot_version=snapshot.snapshot_version,
                snapshot_hash=snapshot.snapshot_hash,
                severity=severity,
                confidence=round(confidence, 4),
                category=definition.category,
                affected_node_ids=[node_id],
                affected_entity_types=[features.entity_type],
                affected_entity_ids=[features.entity_id],
                propagation_scope=definition.propagation_scope,
                feature_evidence=feature_evidence,
                explanation=explanation,
            )
        )

    return signals


# Registry of detector functions
DETECTORS: dict[str, callable] = {
    "single_point_of_failure_alert": detect_spof_signals,
    "concentration_risk_alert": detect_concentration_signals,
    "bottleneck_alert": detect_bottleneck_signals,
    "isolation_alert": detect_isolation_signals,
    "criticality_alert": detect_criticality_signals,
}


def get_detector(signal_name: str) -> callable | None:
    """Retrieve a detector function by signal name."""
    return DETECTORS.get(signal_name)
