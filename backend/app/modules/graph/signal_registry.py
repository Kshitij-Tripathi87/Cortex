"""Signal Registry — frozen signal definitions with thresholds and logic.

The Signal Registry formalizes every signal type before any detector is written.
This keeps the Signal Engine consistent, versioned, and auditable.

Each SignalDefinition specifies:
  - Required input features (from Feature Registry)
  - Severity thresholds (what feature values trigger warning/critical/blocking)
  - Confidence formula (how to compute 0..1 confidence score)
  - Explanation template (human-readable description with placeholders)
  - Propagation scope (which direction impacts flow)

Program D detectors are pure functions that consume FeatureSnapshot + SignalDefinition
→ produce SignalInstance objects. The registry makes detectors swappable and testable.
"""

from __future__ import annotations

from app.modules.graph.signal_models import SignalCategory, SignalDefinition, SignalSeverity

# Frozen Signal Registry for Phase 3 v1
SIGNAL_REGISTRY: dict[str, SignalDefinition] = {
    "single_point_of_failure_alert": SignalDefinition(
        name="single_point_of_failure_alert",
        version="1.0.0",
        category=SignalCategory.SUPPLIER_RISK,
        description="Detects nodes that are single points of failure in the supply chain",
        required_features=["single_point_of_failure", "downstream_reach", "entity_type"],
        severity_thresholds={
            SignalSeverity.INFO.value: 0.3,
            SignalSeverity.WARNING.value: 0.5,
            SignalSeverity.CRITICAL.value: 0.7,
            SignalSeverity.BLOCKING.value: 0.9,
        },
        confidence_formula="min(1.0, spof_score * (1 + downstream_reach / 10))",
        explanation_template="Node {entity_id} ({entity_type}) is a single point of failure with SPOF score {spof:.2f}. "
        "Removing this node would disrupt {downstream_reach} downstream entities.",
        propagation_scope="downstream",
        algorithm_reference="app.modules.graph.detectors.spof:detect_spof_signals",
    ),
    "concentration_risk_alert": SignalDefinition(
        name="concentration_risk_alert",
        version="1.0.0",
        category=SignalCategory.CONCENTRATION,
        description="Detects nodes relying on a single upstream source (no redundancy)",
        required_features=["concentration_risk", "in_degree", "entity_type"],
        severity_thresholds={
            SignalSeverity.INFO.value: 0.5,
            SignalSeverity.WARNING.value: 0.75,
            SignalSeverity.CRITICAL.value: 0.9,
            SignalSeverity.BLOCKING.value: 1.0,
        },
        confidence_formula="concentration_risk * (1 if in_degree == 1 else 0.5)",
        explanation_template="Node {entity_id} ({entity_type}) has concentration risk {risk:.2f} with only {in_degree} upstream source(s). "
        "This creates supply chain vulnerability.",
        propagation_scope="upstream",
        algorithm_reference="app.modules.graph.detectors.concentration:detect_concentration_signals",
    ),
    "bottleneck_alert": SignalDefinition(
        name="bottleneck_alert",
        version="1.0.0",
        category=SignalCategory.BOTTLENECK,
        description="Detects high-betweenness nodes that control flow between graph regions",
        required_features=["betweenness", "total_degree", "entity_type"],
        severity_thresholds={
            SignalSeverity.INFO.value: 0.3,
            SignalSeverity.WARNING.value: 0.5,
            SignalSeverity.CRITICAL.value: 0.7,
            SignalSeverity.BLOCKING.value: 0.9,
        },
        confidence_formula="betweenness * (total_degree / max_degree_in_graph)",
        explanation_template="Node {entity_id} ({entity_type}) is a bottleneck with betweenness {betweenness:.2f} and degree {degree}. "
        "This node controls flow between {upstream_count} upstream and {downstream_count} downstream entities.",
        propagation_scope="both",
        algorithm_reference="app.modules.graph.detectors.bottleneck:detect_bottleneck_signals",
    ),
    "isolation_alert": SignalDefinition(
        name="isolation_alert",
        version="1.0.0",
        category=SignalCategory.ISOLATION,
        description="Detects isolated nodes with no connections (data quality or structural issue)",
        required_features=["total_degree", "entity_type"],
        severity_thresholds={
            SignalSeverity.INFO.value: 0.0,  # any isolation is noteworthy
            SignalSeverity.WARNING.value: 0.0,
            SignalSeverity.CRITICAL.value: 0.0,
            SignalSeverity.BLOCKING.value: 0.0,  # severity determined by entity type
        },
        confidence_formula="1.0 if total_degree == 0 else 0.0",
        explanation_template="Node {entity_id} ({entity_type}) is isolated with no connections. "
        "This may indicate missing data or a structural supply chain gap.",
        propagation_scope="none",
        algorithm_reference="app.modules.graph.detectors.isolation:detect_isolation_signals",
    ),
    "criticality_alert": SignalDefinition(
        name="criticality_alert",
        version="1.0.0",
        category=SignalCategory.DEPENDENCY,
        description="Detects nodes with high operational criticality (broad impact if disrupted)",
        required_features=["criticality", "downstream_reach", "upstream_reach", "entity_type"],
        severity_thresholds={
            SignalSeverity.INFO.value: 0.3,
            SignalSeverity.WARNING.value: 0.5,
            SignalSeverity.CRITICAL.value: 0.7,
            SignalSeverity.BLOCKING.value: 0.9,
        },
        confidence_formula="criticality",
        explanation_template="Node {entity_id} ({entity_type}) has criticality score {criticality:.2f}. "
        "Disruption would affect {downstream_reach} downstream and {upstream_reach} upstream entities.",
        propagation_scope="both",
        algorithm_reference="app.modules.graph.detectors.criticality:detect_criticality_signals",
    ),
}


def get_signal_definition(signal_name: str) -> SignalDefinition | None:
    """Retrieve a signal definition by name. Returns None if not found."""
    return SIGNAL_REGISTRY.get(signal_name)


def validate_signal_evidence(signal_name: str, feature_evidence: dict[str, float]) -> bool:
    """Validate that a signal has all required feature evidence."""
    defn = get_signal_definition(signal_name)
    if defn is None:
        return False
    required = set(defn.required_features)
    provided = set(feature_evidence.keys())
    return required.issubset(provided)


def compute_signal_severity(signal_name: str, feature_evidence: dict[str, float]) -> SignalSeverity:
    """Determine severity level based on feature evidence and thresholds."""
    defn = get_signal_definition(signal_name)
    if defn is None:
        return SignalSeverity.INFO

    # For Phase 3 v1, use the primary feature (first in required_features) for severity
    primary_feature = defn.required_features[0] if defn.required_features else None
    if primary_feature is None or primary_feature not in feature_evidence:
        return SignalSeverity.INFO

    value = feature_evidence[primary_feature]
    thresholds = defn.severity_thresholds

    # Check from highest to lowest severity
    if value >= thresholds.get(SignalSeverity.BLOCKING.value, 1.0):
        return SignalSeverity.BLOCKING
    if value >= thresholds.get(SignalSeverity.CRITICAL.value, 0.7):
        return SignalSeverity.CRITICAL
    if value >= thresholds.get(SignalSeverity.WARNING.value, 0.5):
        return SignalSeverity.WARNING
    if value >= thresholds.get(SignalSeverity.INFO.value, 0.3):
        return SignalSeverity.INFO
    return SignalSeverity.INFO


def format_explanation(template: str, **kwargs) -> str:
    """Format an explanation template with given values.

    Safely handles missing keys and formats floats to 2 decimal places.
    """
    try:
        return template.format(**kwargs)
    except KeyError:
        # Missing placeholder - return template as-is
        return template
    except (ValueError, TypeError):
        # Format error - return template as-is
        return template
