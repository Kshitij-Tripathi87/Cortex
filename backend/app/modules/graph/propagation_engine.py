"""Propagation Engine — deterministic hop-by-hop impact propagation.

The engine consumes:
  - SignalSnapshot (source signal to propagate from)
  - EnrichedSnapshot (features + operational context per node)
  - InMemoryGraph (graph topology for traversal)
  - PropagationRequest (depth, confidence filters)

And outputs:
  - PropagationSnapshot (tree + summary + affected entities + audit metadata)

Algorithm:
  1. Select PropagationRule matching the source signal
  2. BFS from source node up to min(rule.max_depth, request.max_depth)
  3. At each hop, apply rule attenuation and confidence decay
  4. Adjust severity using operational context (inventory, business state)
  5. Record impact type based on entity type
  6. Stop at stop_at_entity_types
  7. Skip edges that rule doesn't follow
  8. Cycle protection via visited set
  9. Aggregate summary and produce snapshot

Deterministic: same inputs → same outputs. All scoring is explicit.
"""

from __future__ import annotations

import time
from collections import deque

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedNodeState, EnrichedSnapshot
from app.modules.graph.propagation_models import (
    AffectedEntity,
    ImpactSummary,
    ImpactType,
    PropagationDirection,
    PropagationRequest,
    PropagationResult,
    PropagationSnapshot,
    PropagationStep,
    PropagationTree,
    Severity,
)
from app.modules.graph.propagation_rules import PropagationRule, get_rule
from app.modules.graph.signal_models import SignalInstance, SignalSeverity
from app.modules.graph.traversal import InMemoryGraph, neighbors

# ─────────────────────────────────────────────────────────────────────────────
# Severity helpers
# ─────────────────────────────────────────────────────────────────────────────


_SIG_SEV_TO_PROP_SEV = {
    SignalSeverity.INFO: Severity.INFO,
    SignalSeverity.WARNING: Severity.WARNING,
    SignalSeverity.CRITICAL: Severity.CRITICAL,
    SignalSeverity.BLOCKING: Severity.BLOCKING,
}


def _convert_severity(sig_sev: SignalSeverity) -> Severity:
    """Convert SignalSeverity to propagation Severity."""
    return _SIG_SEV_TO_PROP_SEV.get(sig_sev, Severity.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Context-based severity adjustment
# ─────────────────────────────────────────────────────────────────────────────


def _adjust_severity_with_context(
    base_severity: Severity,
    enriched: EnrichedNodeState | None,
) -> Severity:
    """Adjust impact severity using operational context at the affected node.

    Rules (deterministic):
    - Fresh inventory coverage >= 30 days: reduce severity by one level
    - Critical customer flag: increase severity by one level
    - Maintenance flag on facility: maintain or increase severity
    """
    if enriched is None or enriched.operational_state is None:
        return base_severity

    levels = [Severity.BLOCKING, Severity.CRITICAL, Severity.WARNING, Severity.INFO]
    order = {s: i for i, s in enumerate(levels)}
    current = order.get(base_severity, 3)

    # Inventory coverage reduces severity
    inv = enriched.inventory
    if inv is not None and inv.coverage_days is not None and inv.coverage_days >= 30:
        current = min(3, current + 1)

    # Critical customer increases severity
    biz = enriched.business
    if biz is not None and biz.critical_customer_flag:
        current = max(0, current - 1)

    # Facility under maintenance increases severity
    prod = enriched.production
    if prod is not None and prod.maintenance_flag:
        current = max(0, current - 1)

    return levels[current]


def _adjust_confidence_with_context(
    base_confidence: float,
    enriched: EnrichedNodeState | None,
) -> float:
    """Adjust confidence using operational context freshness.

    Rules (deterministic):
    - No operational state: reduce confidence by 30%
    - Stale operational state: reduce confidence by 50%
    - Degraded freshness: reduce confidence by 20%
    """
    if enriched is None or enriched.operational_state is None:
        return max(0.05, base_confidence * 0.70)

    if enriched.has_fresh_operational_state:
        return base_confidence
    elif enriched.has_degraded_operational_state:
        return max(0.05, base_confidence * 0.80)
    elif enriched.has_stale_operational_state:
        return max(0.05, base_confidence * 0.50)

    return base_confidence


# ─────────────────────────────────────────────────────────────────────────────
# Impact classification (Step 4)
# ─────────────────────────────────────────────────────────────────────────────


def classify_impact(
    entity_type: str,
    rule: PropagationRule,
) -> ImpactType:
    """Classify impact type for an entity using the rule's mapping."""
    return rule.impact_type_for(entity_type)


def build_impact_reason(
    rule: PropagationRule,
    source_entity: str,
    affected_entity: str,
    relationship: str,
    hop: int,
    severity: Severity,
    confidence: float,
) -> str:
    """Build the human-readable impact reason from the rule template."""
    try:
        return rule.explanation_template.format(
            source_entity=source_entity,
            affected_entity=affected_entity,
            relationship=relationship,
            hop=hop,
            severity=severity.value,
            confidence=confidence,
        )
    except (KeyError, ValueError):
        return rule.explanation_template


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


class PropagationEngine:
    """Deterministic impact propagation engine.

    Usage:
        engine = PropagationEngine()
        result = engine.propagate(
            signal,                  # SignalInstance
            enriched_snapshot,       # EnrichedSnapshot
            graph,                   # InMemoryGraph
            request,                 # PropagationRequest
        )
        snapshot = result.snapshot

    The engine is stateless and pure. Same inputs → same outputs.
    No DB access, no API calls, no mutations.
    """

    def propagate(
        self,
        signal: SignalInstance,
        enriched: EnrichedSnapshot,
        graph: InMemoryGraph,
        request: PropagationRequest,
    ) -> PropagationResult:
        """Run propagation from a single signal.

        Returns PropagationResult containing the full PropagationSnapshot.
        """
        start_time = time.perf_counter()
        warnings: list[str] = []

        # Select rule matching the signal
        rule = get_rule(signal.signal_name)
        if rule.name == "generic_downstream":
            warnings.append(
                f"No specific rule for signal '{signal.signal_name}'; using generic_downstream."
            )

        # Determine depth
        max_depth = min(rule.max_depth, request.max_depth)

        # Determine traversal direction
        if rule.direction == PropagationDirection.DOWNSTREAM:
            traversal_dir = "out"
        elif rule.direction == PropagationDirection.UPSTREAM:
            traversal_dir = "in"
        else:
            traversal_dir = "both"

        # Source info
        source_node_id = request.source_node_id
        source_node = graph.get_node(source_node_id)
        if source_node is None:
            return PropagationResult(
                snapshot=_empty_snapshot(signal, request, enriched),
                success=False,
                warnings=[f"Source node {source_node_id} not in graph."],
            )

        source_node_type = source_node.entity_type
        source_entity_id = source_node.entity_id
        source_severity = _convert_severity(signal.severity)
        source_confidence = signal.confidence

        propagation_id = str(uuid7())

        # BFS propagation
        steps: list[PropagationStep] = []
        visited: set[str] = {source_node_id}
        queue: deque[tuple[str, int, str | None, str]] = deque()
        # tuples: (node_id, hop, parent_node_id, relationship_traversed)
        queue.append((source_node_id, 0, None, "SOURCE"))

        while queue:
            current_id, hop, parent_id, rel_used = queue.popleft()

            # Get current node
            current_node = graph.get_node(current_id)
            if current_node is None:
                continue

            # Get enriched state for current node (features + context)
            current_enriched = enriched.by_node.get(current_id)

            # Compute attenuation, confidence, severity, impact type
            attenuation = rule.attenuation_at_hop(hop)
            confidence = rule.confidence_at_hop(hop, source_confidence)
            # Only apply context adjustment for propagated hops (hop > 0)
            # Source signal (hop 0) already reflects operational context
            if hop > 0:
                confidence = _adjust_confidence_with_context(confidence, current_enriched)

            base_severity = rule.severity_for_hop(hop, source_severity)
            severity = _adjust_severity_with_context(base_severity, current_enriched)

            impact_type = classify_impact(current_node.entity_type, rule)
            reason = build_impact_reason(
                rule,
                source_entity_id,
                current_node.entity_id,
                rel_used,
                hop,
                severity,
                confidence,
            )

            # Skip if confidence below minimum (don't include this BEFORE adding step)
            if confidence < request.min_confidence:
                continue

            # Build the step record
            step = PropagationStep(
                propagation_id=propagation_id,
                source_signal_id=signal.signal_id,
                source_node_id=source_node_id,
                source_node_type=source_node_type,
                affected_node_id=current_id,
                affected_node_type=current_node.entity_type,
                affected_entity_id=current_node.entity_id,
                hop_number=hop,
                relationship_type=rel_used,
                parent_node_id=parent_id,
                attenuation=round(attenuation, 4),
                confidence=round(confidence, 4),
                impact_type=impact_type,
                impact_severity=severity,
                impact_reason=reason,
                graph_version=enriched.feature_snapshot_version,
                feature_snapshot_version=enriched.feature_snapshot_version,
                context_snapshot_version=enriched.operational_snapshot_version,
            )
            steps.append(step)

            # Stop expansion if at max depth
            if hop >= max_depth:
                continue

            # Stop if current node type is a stop condition
            if rule.should_stop(current_node.entity_type):
                continue

            # Filter if requested impact_type_filter doesn't match (still continue expanding)
            if request.impact_type_filter is not None and impact_type != request.impact_type_filter:
                # Note: don't skip expansion — this filter only affects what's reported
                pass

            # Expand to neighbors
            for edge, neighbor_node in neighbors(
                graph,
                current_id,
                direction=traversal_dir,
            ):
                # Relationship filter
                if not rule.follows_relationship(edge.relationship_type):
                    continue
                # Cycle protection
                if neighbor_node.node_id in visited:
                    continue
                visited.add(neighbor_node.node_id)
                queue.append(
                    (
                        neighbor_node.node_id,
                        hop + 1,
                        current_id,
                        edge.relationship_type,
                    )
                )

        # Build affected entities (deduplicated — each node appears once at its lowest hop)
        affected_entities = _build_affected_entities(steps)

        # Build summary
        summary = _build_summary(steps)

        # Categorized affected lists
        affected_facilities = sorted(
            {s.affected_node_id for s in steps if s.affected_node_type == "Facility"}
        )
        affected_inventory = sorted(
            {
                s.affected_node_id
                for s in steps
                if s.affected_node_type in ("InventoryItem", "Product")
            }
        )
        affected_orders = sorted(
            {
                s.affected_node_id
                for s in steps
                if s.affected_node_type in ("PurchaseOrder", "SalesOrder")
            }
        )
        affected_customers = sorted(
            {s.affected_node_id for s in steps if s.affected_node_type == "Customer"}
        )

        # Build tree
        tree = PropagationTree(
            propagation_id=propagation_id,
            source_signal_id=signal.signal_id,
            source_node_id=source_node_id,
            source_node_type=source_node_type,
            steps=steps,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        max_depth_reached = max((s.hop_number for s in steps), default=0)

        snapshot = PropagationSnapshot(
            propagation_id=propagation_id,
            workspace_id=request.workspace_id,
            source_signal_id=signal.signal_id,
            source_signal_name=signal.signal_name,
            source_node_id=source_node_id,
            source_node_type=source_node_type,
            source_severity=source_severity,
            source_confidence=round(source_confidence, 4),
            graph_version=enriched.feature_snapshot_version,
            feature_snapshot_version=enriched.feature_snapshot_version,
            context_snapshot_version=enriched.operational_snapshot_version,
            signal_snapshot_version=signal.snapshot_version,
            tree=tree,
            affected_entities=affected_entities,
            summary=summary,
            affected_facilities=affected_facilities,
            affected_inventory=affected_inventory,
            affected_orders=affected_orders,
            affected_customers=affected_customers,
            execution_time_ms=round(elapsed_ms, 2),
            max_depth_reached=max_depth_reached,
            rules_applied=[rule.name],
            metadata={
                "rule_version": rule.version,
                "traversal_direction": rule.direction.value,
                "max_depth_configured": max_depth,
                "nodes_visited": len(visited),
                "warnings": list(warnings),
            },
        )

        return PropagationResult(
            snapshot=snapshot,
            success=True,
            warnings=warnings,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _empty_snapshot(
    signal: SignalInstance,
    request: PropagationRequest,
    enriched: EnrichedSnapshot,
) -> PropagationSnapshot:
    """Build an empty snapshot when propagation can't run."""
    propagation_id = str(uuid7())
    return PropagationSnapshot(
        propagation_id=propagation_id,
        workspace_id=request.workspace_id,
        source_signal_id=signal.signal_id,
        source_signal_name=signal.signal_name,
        source_node_id=request.source_node_id,
        source_node_type="",
        source_severity=_convert_severity(signal.severity),
        source_confidence=signal.confidence,
        graph_version=enriched.feature_snapshot_version,
        feature_snapshot_version=enriched.feature_snapshot_version,
        context_snapshot_version=enriched.operational_snapshot_version,
        signal_snapshot_version=signal.snapshot_version,
        tree=PropagationTree(
            propagation_id=propagation_id,
            source_signal_id=signal.signal_id,
            source_node_id=request.source_node_id,
            source_node_type="",
            steps=[],
        ),
        affected_entities=[],
        summary=ImpactSummary(total_affected=0),
        affected_facilities=[],
        affected_inventory=[],
        affected_orders=[],
        affected_customers=[],
        execution_time_ms=0.0,
        max_depth_reached=0,
        rules_applied=["generic_downstream"],
        metadata={"error": "source_node_not_found"},
    )


def _build_affected_entities(steps: list[PropagationStep]) -> list[AffectedEntity]:
    """Build deduplicated list of affected entities.

    Each node appears at its lowest hop, sorted by hop then node_id for determinism.
    """
    seen: dict[str, PropagationStep] = {}
    for step in steps:
        if (
            step.affected_node_id not in seen
            or step.hop_number < seen[step.affected_node_id].hop_number
        ):
            seen[step.affected_node_id] = step

    entities = [
        AffectedEntity(
            node_id=s.affected_node_id,
            entity_id=s.affected_entity_id,
            entity_type=s.affected_node_type,
            hop_number=s.hop_number,
            impact_type=s.impact_type,
            impact_severity=s.impact_severity,
            confidence=s.confidence,
            impact_reason=s.impact_reason,
        )
        for s in seen.values()
    ]
    entities.sort(key=lambda e: (e.hop_number, e.node_id))
    return entities


def _build_summary(steps: list[PropagationStep]) -> ImpactSummary:
    """Aggregate impact stats from all propagation steps."""
    if not steps:
        return ImpactSummary(total_affected=0)

    by_impact_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_entity_type: dict[str, int] = {}
    confidences: list[float] = []

    for s in steps:
        it = s.impact_type.value
        by_impact_type[it] = by_impact_type.get(it, 0) + 1

        sev = s.impact_severity.value
        by_severity[sev] = by_severity.get(sev, 0) + 1

        et = s.affected_node_type
        by_entity_type[et] = by_entity_type.get(et, 0) + 1

        confidences.append(s.confidence)

    max_hop = max(s.hop_number for s in steps)

    return ImpactSummary(
        total_affected=len(steps),
        by_impact_type=dict(sorted(by_impact_type.items())),
        by_severity=dict(sorted(by_severity.items())),
        by_entity_type=dict(sorted(by_entity_type.items())),
        max_hop=max_hop,
        avg_confidence=round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
        min_confidence=round(min(confidences), 4) if confidences else 0.0,
    )
