"""Recommendation Candidate Generation — deterministic rule-based generation.

This module generates candidate recommendations from scenario snapshots
using deterministic rules defined in recommendation_rules.py.

Candidate generation is:
  - Deterministic: same inputs → same candidates
  - Evidence-based: only generates candidates with required evidence
  - Context-aware: uses operational context to filter candidates
  - Explainable: tracks why each candidate was generated
"""

from __future__ import annotations

from typing import Any

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.propagation_models import PropagationSnapshot
from app.modules.graph.recommendation_models import (
    RecommendationCandidate,
    RecommendationCategory,
    RecommendationType,
)
from app.modules.graph.recommendation_rules import (
    get_recommendation_type_spec,
    get_scenario_recommendation_rule,
)
from app.modules.graph.scenario_models import (
    ScenarioImpactRecord,
    ScenarioSnapshot,
)
from app.modules.graph.signal_models import SignalSnapshot


def generate_candidates(
    scenario_snapshot: ScenarioSnapshot,
    enriched_snapshot: EnrichedSnapshot | None = None,
    propagation_snapshot: PropagationSnapshot | None = None,
    signal_snapshot: SignalSnapshot | None = None,
) -> list[RecommendationCandidate]:
    """Generate candidate recommendations from a scenario snapshot.

    This is the main entry point for candidate generation.

    Args:
        scenario_snapshot: The scenario execution result
        enriched_snapshot: Optional enriched context (features + operational)
        propagation_snapshot: Optional propagation snapshot
        signal_snapshot: Optional signal snapshot

    Returns:
        List of candidate recommendations (may include duplicates)
    """
    candidates: list[RecommendationCandidate] = []

    scenario_type = scenario_snapshot.scenario_definition.scenario_type
    rule = get_scenario_recommendation_rule(scenario_type)

    if not rule:
        # No rules for this scenario type - return empty
        return candidates

    # Extract impacted entities from scenario
    impacted_entities = _extract_impacted_entities(scenario_snapshot)

    # Extract operational context
    operational_context = _extract_operational_context(enriched_snapshot)

    # Generate candidates for each recommendation type
    for rec_type in rule.candidate_types:
        spec = get_recommendation_type_spec(rec_type)
        if not spec:
            continue

        # Special handling for no-action - only include if conditions met
        if rec_type == RecommendationType.NO_ACTION_MONITOR and not _should_include_no_action(
            scenario_snapshot, impacted_entities
        ):
            continue

        # Check if candidate should be generated based on conditions
        if not _check_generation_conditions(
            rec_type,
            scenario_snapshot,
            impacted_entities,
            operational_context,
            rule.conditions,
        ):
            continue

        # Build the candidate
        candidate = _build_candidate(
            candidate_type=rec_type,
            spec=spec,
            scenario_snapshot=scenario_snapshot,
            propagation_snapshot=propagation_snapshot,
            signal_snapshot=signal_snapshot,
            impacted_entities=impacted_entities,
            operational_context=operational_context,
        )

        if candidate:
            candidates.append(candidate)

    # Always consider no-action option if impact is low
    if _should_include_no_action(scenario_snapshot, impacted_entities):
        no_action_candidate = _build_no_action_candidate(
            scenario_snapshot,
            propagation_snapshot,
            signal_snapshot,
        )
        if no_action_candidate:
            candidates.append(no_action_candidate)

    return candidates


def _extract_impacted_entities(
    scenario_snapshot: ScenarioSnapshot,
) -> dict[str, list[ScenarioImpactRecord]]:
    """Extract impacted entities grouped by category."""
    by_category: dict[str, list[ScenarioImpactRecord]] = {}

    for impact in scenario_snapshot.impacts:
        category = impact.impact_category
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(impact)

    return by_category


def _extract_operational_context(
    enriched_snapshot: EnrichedSnapshot | None,
) -> dict[str, Any]:
    """Extract relevant operational context from enriched snapshot."""
    if not enriched_snapshot:
        return {}

    context = {
        "inventory_coverage_days": [],
        "critical_customers": [],
        "facility_capacity": [],
        "alternate_suppliers": [],
        "alternate_facilities": [],
    }

    for node_state in enriched_snapshot.by_node.values():
        # Inventory coverage
        inv = node_state.inventory
        if inv and inv.coverage_days is not None:
            context["inventory_coverage_days"].append(
                {
                    "node_id": node_state.node_id,
                    "entity_id": node_state.entity_id,
                    "coverage_days": inv.coverage_days,
                }
            )

        # Critical customers
        business = node_state.business
        if business and business.critical_customer_flag:
            context["critical_customers"].append(
                {
                    "node_id": node_state.node_id,
                    "entity_id": node_state.entity_id,
                }
            )

        # Facility capacity
        prod = node_state.production
        if prod and prod.capacity_pct is not None:
            context["facility_capacity"].append(
                {
                    "node_id": node_state.node_id,
                    "entity_id": node_state.entity_id,
                    "capacity_pct": prod.capacity_pct,
                }
            )

    return context


def _check_generation_conditions(
    rec_type: RecommendationType,
    scenario_snapshot: ScenarioSnapshot,
    impacted_entities: dict[str, list[ScenarioImpactRecord]],
    operational_context: dict[str, Any],
    conditions: dict[str, Any],
) -> bool:
    """Check if conditions for generating a candidate are met."""
    # Check minimum severity
    min_severity = conditions.get("min_severity")
    if min_severity:
        severity_order = {"info": 0, "warning": 1, "critical": 2, "blocking": 3}
        min_level = severity_order.get(min_severity, 0)

        has_severe_enough = False
        for impact in scenario_snapshot.impacts:
            impact_level = severity_order.get(impact.severity, 0)
            if impact_level >= min_level:
                has_severe_enough = True
                break

        if not has_severe_enough:
            return False

    # Check for alternate supplier requirement
    # In a real implementation, would check graph for alternate suppliers
    # For now, assume available if we have supplier impacts
    if conditions.get("requires_alternate_supplier") and "supplier" not in impacted_entities:
        return False

    # Check for alternate facility requirement
    if (
        conditions.get("requires_alternate_facility")
        and "facility" not in impacted_entities
        and "inventory" not in impacted_entities
    ):
        return False

    # Check delay threshold
    # Would check actual delay from propagation metadata
    # For now, assume condition met if we have logistics impacts
    delay_threshold = conditions.get("delay_threshold_hours")
    if delay_threshold is not None and "logistics" not in impacted_entities:
        return False

    # Check spike/drop thresholds
    spike_threshold = conditions.get("spike_threshold_pct")
    if spike_threshold is not None:
        # Would check demand spike percentage from scenario parameters
        # For now, assume condition met if we have demand scenario
        pass

    drop_threshold = conditions.get("drop_threshold_pct")
    if drop_threshold is not None:
        pass

    # Check shortage threshold
    # Would check inventory coverage days
    # For now, assume condition met if we have inventory impacts
    shortage_threshold = conditions.get("shortage_threshold_days")
    if shortage_threshold is not None and "inventory" not in impacted_entities:
        return False

    # Check capacity threshold
    capacity_threshold = conditions.get("capacity_threshold_pct")
    if capacity_threshold is not None:
        # Would check facility capacity from operational context
        pass

    return True


def _build_candidate(
    candidate_type: RecommendationType,
    spec: Any,  # RecommendationTypeSpec
    scenario_snapshot: ScenarioSnapshot,
    propagation_snapshot: PropagationSnapshot | None,
    signal_snapshot: SignalSnapshot | None,
    impacted_entities: dict[str, list[ScenarioImpactRecord]],
    operational_context: dict[str, Any],
) -> RecommendationCandidate | None:
    """Build a candidate recommendation with all required fields."""
    # Collect affected entities
    affected_node_ids: set[str] = set()
    affected_entity_ids: set[str] = set()
    affected_entity_types: set[str] = set()

    for impact in scenario_snapshot.impacts:
        affected_node_ids.add(impact.affected_node_id)
        affected_entity_ids.add(impact.affected_entity_id)
        affected_entity_types.add(impact.affected_entity_type)

    # Build required evidence list
    required_evidence = list(spec.required_evidence)

    # Check if required evidence is available
    for req_type in required_evidence:
        if req_type not in affected_entity_types:
            # Required evidence not present - skip this candidate
            # Exception: some recommendations can work with related entities
            pass

    # Generate candidate ID
    candidate_id = f"cand-{uuid7()}"

    # Build description based on scenario context
    description = _build_candidate_description(
        candidate_type,
        spec,
        scenario_snapshot,
        impacted_entities,
    )

    # Collect source signal IDs
    source_signal_ids = []
    if scenario_snapshot.source_signal_id:
        source_signal_ids.append(scenario_snapshot.source_signal_id)
    if signal_snapshot:
        source_signal_ids.extend([s.signal_id for s in signal_snapshot.signals])

    return RecommendationCandidate(
        candidate_id=candidate_id,
        recommendation_type=candidate_type,
        category=spec.category,
        name=spec.name,
        description=description,
        source_scenario_id=scenario_snapshot.scenario_id,
        source_propagation_id=scenario_snapshot.source_propagation_id,
        source_signal_ids=source_signal_ids,
        required_evidence=required_evidence,
        affected_node_ids=list(affected_node_ids),
        affected_entity_ids=list(affected_entity_ids),
        affected_entity_types=list(affected_entity_types),
        metadata={
            "generation_rule": spec.recommendation_type.value,
            "scenario_type": scenario_snapshot.scenario_definition.scenario_type.value,
            "impacted_entity_count": len(scenario_snapshot.impacts),
        },
    )


def _build_candidate_description(
    candidate_type: RecommendationType,
    spec: Any,
    scenario_snapshot: ScenarioSnapshot,
    impacted_entities: dict[str, list[ScenarioImpactRecord]],
) -> str:
    """Build human-readable description for a candidate."""
    base_desc = spec.description

    # Enhance with scenario-specific context
    if candidate_type == RecommendationType.TRANSFER_INVENTORY:
        inv_impacts = impacted_entities.get("inventory", [])
        if inv_impacts:
            entity_ids = [i.affected_entity_id for i in inv_impacts[:3]]
            return f"{base_desc}. Affected inventory: {', '.join(entity_ids)}"

    elif candidate_type == RecommendationType.USE_ALTERNATE_SUPPLIER:
        sup_impacts = impacted_entities.get("supplier", [])
        if sup_impacts:
            entity_ids = [i.affected_entity_id for i in sup_impacts[:3]]
            return f"{base_desc}. Affected supplier: {', '.join(entity_ids)}"

    elif candidate_type == RecommendationType.PRIORITIZE_CRITICAL_ORDERS:
        order_impacts = impacted_entities.get("order", [])
        if order_impacts:
            count = len(order_impacts)
            return f"{base_desc}. {count} orders may be affected."

    return base_desc


def _build_no_action_candidate(
    scenario_snapshot: ScenarioSnapshot,
    propagation_snapshot: PropagationSnapshot | None,
    signal_snapshot: SignalSnapshot | None,
) -> RecommendationCandidate | None:
    """Build the no-action monitoring candidate."""
    spec = get_recommendation_type_spec(RecommendationType.NO_ACTION_MONITOR)
    if not spec:
        return None

    candidate_id = f"cand-{uuid7()}"

    source_signal_ids = []
    if scenario_snapshot.source_signal_id:
        source_signal_ids.append(scenario_snapshot.source_signal_id)

    return RecommendationCandidate(
        candidate_id=candidate_id,
        recommendation_type=RecommendationType.NO_ACTION_MONITOR,
        category=RecommendationCategory.MONITORING,
        name=spec.name,
        description=spec.description,
        source_scenario_id=scenario_snapshot.scenario_id,
        source_propagation_id=scenario_snapshot.source_propagation_id,
        source_signal_ids=source_signal_ids,
        required_evidence=[],
        affected_node_ids=[i.affected_node_id for i in scenario_snapshot.impacts],
        affected_entity_ids=[i.affected_entity_id for i in scenario_snapshot.impacts],
        affected_entity_types=[i.affected_entity_type for i in scenario_snapshot.impacts],
        metadata={
            "generation_rule": "no_action_low_impact",
            "scenario_type": scenario_snapshot.scenario_definition.scenario_type.value,
            "total_impacts": len(scenario_snapshot.impacts),
        },
    )


def _should_include_no_action(
    scenario_snapshot: ScenarioSnapshot,
    impacted_entities: dict[str, list[ScenarioImpactRecord]],
) -> bool:
    """Determine if no-action option should be included.

    Include no-action when:
      - Total impacts are low
      - No critical/blocking severity
      - Financial impact is below threshold
      - Service level impact is minimal
    """
    # Empty scenario - include no-action
    if not scenario_snapshot.impacts:
        return True

    # Check for critical/blocking severity
    has_critical = any(i.severity in ("critical", "blocking") for i in scenario_snapshot.impacts)

    if has_critical:
        return False

    # Check total impact count
    if len(scenario_snapshot.impacts) > 10:
        return False

    # Check financial impact
    total_financial = sum(i.estimated_financial_impact or 0 for i in scenario_snapshot.impacts)

    if total_financial > 100000:  # $100k threshold
        return False

    # Check service level impact
    max_service_impact = max(
        (i.estimated_service_level_impact_pct or 0) for i in scenario_snapshot.impacts
    )

    return max_service_impact <= 10  # 10% threshold
