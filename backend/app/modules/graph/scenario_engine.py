"""Scenario Engine — deterministic what-if simulation over propagation results.

The engine consumes:
  - PropagationSnapshot (from Program E)
  - ScenarioDefinition (what-if specification)
  - ScenarioRule (deterministic formulas for this scenario type)
  - EnrichedSnapshot (features + operational context)

And outputs:
  - ScenarioSnapshot (impacts + estimates + assumptions + summary)

The engine does NOT compute propagation itself — it reuses the
PropagationSnapshot and enriches it with scenario-specific estimates:
  - Recovery time
  - Financial impact
  - Service level impact

All formulas are deterministic and explicit.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.propagation_models import (
    PropagationSnapshot,
    PropagationStep,
    Severity,
)
from app.modules.graph.scenario_models import (
    ScenarioAssumption,
    ScenarioDefinition,
    ScenarioImpactRecord,
    ScenarioRequest,
    ScenarioResult,
    ScenarioSnapshot,
    ScenarioStatus,
    ScenarioSummary,
)
from app.modules.graph.scenario_rules import ScenarioRule, get_rule
from app.modules.graph.signal_models import SignalSeverity

# ─────────────────────────────────────────────────────────────────────────────
# Severity mapping
# ─────────────────────────────────────────────────────────────────────────────

_PROP_SEV_TO_SCENARIO = {
    Severity.INFO: "info",
    Severity.WARNING: "warning",
    Severity.CRITICAL: "critical",
    Severity.BLOCKING: "critical",
}

_SIG_SEV_TO_SCENARIO = {
    SignalSeverity.INFO: "info",
    SignalSeverity.WARNING: "warning",
    SignalSeverity.CRITICAL: "critical",
    SignalSeverity.BLOCKING: "critical",
}


def _map_severity(prop_sev: Severity, rule: ScenarioRule) -> str:
    """Map propagation severity to scenario severity using rule's map."""
    sev_key = prop_sev.value
    return rule.severity_map.get(sev_key, sev_key)


# ─────────────────────────────────────────────────────────────────────────────
# Assumption generation
# ─────────────────────────────────────────────────────────────────────────────


def _generate_assumptions(
    definition: ScenarioDefinition,
    rule: ScenarioRule,
    propagation: PropagationSnapshot | None,
) -> list[ScenarioAssumption]:
    """Generate explicit assumptions for this scenario execution."""
    assumptions: list[ScenarioAssumption] = []

    # Default assumptions from rule
    for _i, a in enumerate(rule.default_assumptions):
        assumptions.append(
            ScenarioAssumption(
                assumption_id=str(uuid7()),
                scenario_id=definition.scenario_id,
                description=a["description"],
                category=a["category"],
                confidence=a["confidence"],
                source=a["source"],
                metadata={},
            )
        )

    # Scenario parameter assumptions
    for p in definition.parameters:
        if p.value is not None:
            assumptions.append(
                ScenarioAssumption(
                    assumption_id=str(uuid7()),
                    scenario_id=definition.scenario_id,
                    description=f"Parameter '{p.name}' = {p.value} {p.unit or ''}",
                    category="parameter",
                    confidence=1.0,
                    source="user_defined",
                    metadata={"parameter": p.name, "value": p.value},
                )
            )

    # Propagation-based assumptions
    if propagation:
        assumptions.append(
            ScenarioAssumption(
                assumption_id=str(uuid7()),
                scenario_id=definition.scenario_id,
                description=f"Propagation from {propagation.source_signal_name} used as impact base",
                category="propagation",
                confidence=0.9,
                source="derived_from_propagation",
                metadata={
                    "source_propagation_id": propagation.propagation_id,
                    "propagation_max_depth": propagation.max_depth_reached,
                },
            )
        )

    return assumptions


# ─────────────────────────────────────────────────────────────────────────────
# Impact estimation
# ─────────────────────────────────────────────────────────────────────────────


def _estimate_recovery_hours(
    step: PropagationStep,
    enriched: EnrichedSnapshot | None,
    rule: ScenarioRule,
) -> float:
    """Estimate recovery time in hours."""
    base = rule.recovery_hours_base
    hop_bonus = rule.recovery_hours_per_hop * step.hop_number
    severity_bonus = rule.recovery_hours_per_severity.get(step.impact_severity.value, 0.0)

    # Adjust based on operational context
    context_factor = 1.0
    if enriched:
        node_enriched = enriched.by_node.get(step.affected_node_id)
        if node_enriched:
            # Inventory coverage reduces recovery time
            inv = node_enriched.inventory
            if inv and inv.coverage_days is not None:
                if inv.coverage_days > 30:
                    context_factor *= 0.5
                elif inv.coverage_days > 14:
                    context_factor *= 0.75
            # Production redundancy reduces recovery
            prod = node_enriched.production
            if prod and prod.capacity_pct is not None and prod.capacity_pct > 0.7:
                context_factor *= 0.8

    return round((base + hop_bonus + severity_bonus) * context_factor, 1)


def _estimate_financial_impact(
    step: PropagationStep,
    enriched: EnrichedSnapshot | None,
    rule: ScenarioRule,
) -> float:
    """Estimate financial impact in USD."""
    base = rule.financial_impact_base
    severity_mult = rule.financial_impact_per_severity.get(step.impact_severity.value, 1.0)
    entity_mult = rule.financial_impact_per_entity_type.get(step.affected_node_type, 1.0)

    # Context adjustments
    context_factor = 1.0
    if enriched:
        node_enriched = enriched.by_node.get(step.affected_node_id)
        if node_enriched:
            biz = node_enriched.business
            if biz and biz.revenue_at_risk is not None:
                # Use actual revenue at risk as upper bound
                context_factor = min(2.0, biz.revenue_at_risk / base / 1000)
            # Critical customer increases impact
            if biz and biz.critical_customer_flag:
                context_factor *= 1.5

    return round(base * severity_mult * entity_mult * context_factor, 2)


def _estimate_service_level_impact(
    step: PropagationStep,
    rule: ScenarioRule,
) -> float:
    """Estimate service level impact as percentage."""
    base = rule.service_level_impact_base
    severity_bonus = rule.service_level_impact_per_severity.get(step.impact_severity.value, 0.0)
    hop_bonus = rule.service_level_impact_per_hop * step.hop_number

    return round(min(100.0, base + severity_bonus + hop_bonus), 1)


def _determine_impact_category(
    entity_type: str,
    rule: ScenarioRule,
) -> str:
    """Map entity type to impact category."""
    # Try exact match first, then lowercase fallback
    return rule.impact_category_map.get(
        entity_type, rule.impact_category_map.get(entity_type.lower(), "business")
    )


def _build_impact_reason(
    step: PropagationStep,
    rule: ScenarioRule,
) -> str:
    """Build human-readable impact reason."""
    return (
        f"{rule.description} — propagated from {step.source_node_type} "
        f"via {step.relationship_type} at hop {step.hop_number}. "
        f"Severity: {step.impact_severity.value}, Confidence: {step.confidence:.2f}."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioEngine:
    """Deterministic scenario execution engine.

    Consumes PropagationSnapshot + ScenarioDefinition, applies ScenarioRule,
    produces ScenarioSnapshot with enriched impact estimates.
    """

    def execute(
        self,
        request: ScenarioRequest,
        propagation: PropagationSnapshot | None,
        enriched: EnrichedSnapshot,
    ) -> ScenarioResult:
        """Execute a scenario.

        Args:
            request: The scenario request with definition
            propagation: Optional source PropagationSnapshot (if scenario based on propagation)
            enriched: EnrichedSnapshot for context-aware estimates

        Returns:
            ScenarioResult with the ScenarioSnapshot
        """
        start = time.perf_counter()
        warnings: list[str] = []

        definition = request.scenario_definition
        rule = get_rule(definition.scenario_type)

        # Validate parameters
        param_warnings = self._validate_parameters(definition, rule)
        warnings.extend(param_warnings)

        if propagation is None and definition.source_propagation_id:
            warnings.append(
                f"Source propagation {definition.source_propagation_id} "
                "not provided; using scenario parameters only."
            )

        # Generate assumptions
        assumptions = _generate_assumptions(definition, rule, propagation)

        # Build impacts from propagation or from scenario parameters
        impacts: list[ScenarioImpactRecord] = []

        if propagation:
            impacts = self._build_impacts_from_propagation(
                propagation=propagation,
                enriched=enriched,
                rule=rule,
                scenario_id=definition.scenario_id,
            )
        else:
            impacts = self._build_impacts_from_definition(
                definition=definition,
                enriched=enriched,
                rule=rule,
            )

        # Apply scenario parameter adjustments (e.g., shortage severity %)
        impacts = self._apply_parameter_adjustments(impacts, definition, rule)

        # Build summary
        summary = self._build_summary(impacts)

        # Compute snapshot hash
        snapshot_hash = self._compute_snapshot_hash(definition, impacts)

        elapsed = (time.perf_counter() - start) * 1000

        snapshot = ScenarioSnapshot(
            scenario_id=definition.scenario_id,
            workspace_id=definition.workspace_id,
            scenario_definition=definition,
            status=ScenarioStatus.COMPLETED,
            assumptions=assumptions,
            impacts=impacts,
            summary=summary,
            source_propagation_id=propagation.propagation_id if propagation else None,
            source_signal_id=definition.source_signal_id,
            graph_version=enriched.feature_snapshot_version,
            feature_snapshot_version=enriched.feature_snapshot_version,
            context_snapshot_version=enriched.operational_snapshot_version,
            propagation_snapshot_version=propagation.tree.steps[0].graph_version
            if propagation and propagation.tree.steps
            else None,
            execution_time_ms=round(elapsed, 2),
            rules_applied=[rule.name],
            warnings=warnings,
            scenario_snapshot_version=request.snapshot_version
            or enriched.feature_snapshot_version
            or 0,
            scenario_snapshot_hash=snapshot_hash,
            completed_at=datetime.now(UTC),
        )

        return ScenarioResult(
            snapshot=snapshot,
            success=True,
            warnings=warnings,
        )

    def _validate_parameters(
        self,
        definition: ScenarioDefinition,
        rule: ScenarioRule,
    ) -> list[str]:
        """Validate scenario parameters against rule specification."""
        warnings: list[str] = []

        param_specs = {p["name"]: p for p in rule.parameters}
        provided = {p.name: p for p in definition.parameters}

        for name, spec in param_specs.items():
            if spec.get("required", False) and name not in provided:
                warnings.append(f"Required parameter '{name}' missing")
            elif name in provided:
                value = provided[name].value
                # Type/range validation
                if spec.get("type") is int:
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        warnings.append(f"Parameter '{name}' must be integer")
                        continue
                    if "min" in spec and value < spec["min"]:
                        warnings.append(f"Parameter '{name}' below minimum {spec['min']}")
                    if "max" in spec and value > spec["max"]:
                        warnings.append(f"Parameter '{name}' above maximum {spec['max']}")

        return warnings

    def _build_impacts_from_propagation(
        self,
        propagation: PropagationSnapshot,
        enriched: EnrichedSnapshot,
        rule: ScenarioRule,
        scenario_id: str,
    ) -> list[ScenarioImpactRecord]:
        """Build scenario impacts from propagation steps."""
        impacts: list[ScenarioImpactRecord] = []

        for step in propagation.tree.steps:
            # Skip source step (hop 0) - that's the trigger
            if step.hop_number == 0:
                continue

            # Apply severity mapping
            mapped_severity = _map_severity(step.impact_severity, rule)

            # Estimate recovery, financial, service level
            recovery_hours = _estimate_recovery_hours(step, enriched, rule)
            financial_impact = _estimate_financial_impact(step, enriched, rule)
            service_level = _estimate_service_level_impact(step, rule)
            impact_category = _determine_impact_category(step.affected_node_type, rule)
            # Build impact reason (used for audit/debug; not stored in impact record)
            _build_impact_reason(step, rule)
            impact = ScenarioImpactRecord(
                scenario_id=scenario_id,
                affected_node_id=step.affected_node_id,
                affected_entity_id=step.affected_entity_id,
                affected_entity_type=step.affected_node_type,
                hop_number=step.hop_number,
                impact_category=impact_category,
                severity=mapped_severity,
                confidence=step.confidence,
                estimated_recovery_hours=recovery_hours,
                estimated_financial_impact=financial_impact,
                estimated_service_level_impact_pct=service_level,
                source_propagation_step_id=step.propagation_id,
                graph_version=step.graph_version,
                context_version=step.context_snapshot_version,
                propagation_version=step.feature_snapshot_version,
                metadata={
                    "source_signal_name": propagation.source_signal_name,
                    "source_node_id": propagation.source_node_id,
                    "attenuation": step.attenuation,
                    "original_severity": step.impact_severity.value,
                },
            )
            impacts.append(impact)

        return impacts

    def _build_impacts_from_definition(
        self,
        definition: ScenarioDefinition,
        enriched: EnrichedSnapshot,
        rule: ScenarioRule,
    ) -> list[ScenarioImpactRecord]:
        """Build impacts directly from scenario definition (no propagation).

        Used when scenario is defined without a source propagation.
        Creates impacts for nodes that match the scenario type's target entities.
        """
        # This is a fallback - in practice scenarios should have propagation
        impacts: list[ScenarioImpactRecord] = []

        # Use parameter values to estimate scope
        severity_param = next(
            (p.value for p in definition.parameters if "severity" in p.name.lower()), None
        )

        # Default to WARNING if not specified
        base_severity = "warning"
        if severity_param is not None:
            if severity_param >= 70:
                base_severity = "critical"
            elif severity_param <= 30:
                base_severity = "info"

        # Create a single representative impact for the scenario
        impact = ScenarioImpactRecord(
            scenario_id=definition.scenario_id,
            affected_node_id=definition.parameters[0].value if definition.parameters else "unknown",
            affected_entity_id=definition.parameters[0].value
            if definition.parameters
            else "unknown",
            affected_entity_type=definition.scenario_type.value.replace("_", " ").title(),
            hop_number=1,
            impact_category=definition.scenario_type.value,
            severity=base_severity,
            confidence=0.7,  # Lower confidence without propagation
            estimated_recovery_hours=rule.recovery_hours_base,
            estimated_financial_impact=rule.financial_impact_base,
            estimated_service_level_impact_pct=rule.service_level_impact_base,
            metadata={"source": "definition_only"},
        )
        impacts.append(impact)

        return impacts

    def _apply_parameter_adjustments(
        self,
        impacts: list[ScenarioImpactRecord],
        definition: ScenarioDefinition,
        rule: ScenarioRule,
    ) -> list[ScenarioImpactRecord]:
        """Adjust impacts based on scenario parameters (e.g., shortage severity %)."""
        # Find severity/reduction parameters
        severity_factor = 1.0
        for p in definition.parameters:
            if "severity" in p.name.lower() or "reduction" in p.name.lower():
                severity_factor = p.value / 100.0 if isinstance(p.value, (int, float)) else 1.0

        adjusted: list[ScenarioImpactRecord] = []
        for imp in impacts:
            # Scale financial and recovery by severity factor
            new_financial = (
                round(imp.estimated_financial_impact * severity_factor, 2)
                if imp.estimated_financial_impact
                else 0.0
            )
            new_recovery = (
                round(imp.estimated_recovery_hours * severity_factor, 1)
                if imp.estimated_recovery_hours
                else 0.0
            )
            new_service = (
                round(
                    min(100.0, (imp.estimated_service_level_impact_pct or 0) * severity_factor), 1
                )
                if imp.estimated_service_level_impact_pct
                else 0.0
            )

            # Escalate severity if factor > 1.0 (not typical) or keep
            new_severity = imp.severity
            if severity_factor >= 0.7:
                new_severity = "critical"
            elif severity_factor >= 0.4:
                new_severity = "warning"
            else:
                new_severity = "info"

            adjusted.append(
                ScenarioImpactRecord(
                    scenario_id=imp.scenario_id,
                    affected_node_id=imp.affected_node_id,
                    affected_entity_id=imp.affected_entity_id,
                    affected_entity_type=imp.affected_entity_type,
                    hop_number=imp.hop_number,
                    impact_category=imp.impact_category,
                    severity=new_severity,
                    confidence=imp.confidence,
                    estimated_recovery_hours=new_recovery,
                    estimated_financial_impact=new_financial,
                    estimated_service_level_impact_pct=new_service,
                    source_propagation_step_id=imp.source_propagation_step_id,
                    graph_version=imp.graph_version,
                    context_version=imp.context_version,
                    propagation_version=imp.propagation_version,
                    created_at=imp.created_at,
                    metadata={**imp.metadata, "severity_factor": severity_factor},
                )
            )

        return adjusted

    def _build_summary(self, impacts: list[ScenarioImpactRecord]) -> ScenarioSummary:
        """Aggregate impact summary."""
        if not impacts:
            return ScenarioSummary(total_impacted_entities=0)

        by_category: dict[str, int] = {}
        by_severity: dict[str, int] = {}
        by_entity_type: dict[str, int] = {}
        max_hop = 0
        confidences: list[float] = []
        total_recovery = 0.0
        total_financial = 0.0
        max_service = 0.0

        for imp in impacts:
            by_category[imp.impact_category] = by_category.get(imp.impact_category, 0) + 1
            by_severity[imp.severity] = by_severity.get(imp.severity, 0) + 1
            by_entity_type[imp.affected_entity_type] = (
                by_entity_type.get(imp.affected_entity_type, 0) + 1
            )
            max_hop = max(max_hop, imp.hop_number)
            confidences.append(imp.confidence)
            total_recovery += imp.estimated_recovery_hours or 0
            total_financial += imp.estimated_financial_impact or 0
            max_service = max(max_service, imp.estimated_service_level_impact_pct or 0)

        return ScenarioSummary(
            total_impacted_entities=len(impacts),
            by_impact_category=dict(sorted(by_category.items())),
            by_severity=dict(sorted(by_severity.items())),
            by_entity_type=dict(sorted(by_entity_type.items())),
            max_hop=max_hop,
            avg_confidence=round(sum(confidences) / len(confidences), 4) if confidences else 0.0,
            min_confidence=round(min(confidences), 4) if confidences else 0.0,
            total_estimated_recovery_hours=round(total_recovery, 2),
            total_estimated_financial_impact=round(total_financial, 2),
            max_service_level_impact_pct=round(max_service, 2),
        )

    def _compute_snapshot_hash(
        self,
        definition: ScenarioDefinition,
        impacts: list[ScenarioImpactRecord],
    ) -> str:
        """Compute deterministic hash of scenario snapshot."""
        hasher = hashlib.sha256()
        hasher.update(definition.scenario_id.encode())
        hasher.update(definition.scenario_type.value.encode())
        for p in sorted(definition.parameters, key=lambda x: x.name):
            hasher.update(f"{p.name}={p.value}".encode())
        for imp in sorted(impacts, key=lambda x: x.affected_node_id):
            hasher.update(
                f"{imp.affected_node_id}:{imp.hop_number}:{imp.severity}:{imp.confidence:.4f}".encode()
            )
        return hasher.hexdigest()[:16]

    # Alias for test compatibility
    execute_scenario = execute
