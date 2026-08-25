"""Scenario Registry — Centralized Catalog of Available Scenarios.

Program J (World State & Digital Twin) scenario catalog:

The ScenarioRegistry provides a single source of truth for all
available scenarios. New scenarios can be registered and queried.

Responsibilities:
- Register built-in scenarios (supplier failure, demand spike, etc.)
- Allow custom scenario registration
- Query scenarios by type, tags, or parameters
- Provide scenario templates with parameter substitution
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.common.ids import uuid7
from app.modules.twin.twin_models import (
    ScenarioType,
    TwinScenario,
    create_currency_shock_scenario,
    create_cyber_attack_scenario,
    create_demand_spike_twin_scenario,
    create_factory_fire_scenario,
    create_labor_strike_scenario,
    create_pandemic_scenario,
    create_port_closure_scenario,
    create_pricing_shock_scenario,
    create_supplier_failure_twin_scenario,
    create_weather_scenario,
)


@dataclass(frozen=True)
class ScenarioTemplate:
    """A reusable scenario template with parameter substitution."""

    template_id: str
    name: str
    description: str
    scenario_type: ScenarioType
    factory: Callable[..., TwinScenario]
    required_params: list[str] = field(default_factory=list)
    optional_params: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def instantiate(self, params: dict[str, Any]) -> TwinScenario:
        """Instantiate this template with the given parameters."""
        scenario_id = str(uuid7())
        return self.factory(scenario_id=scenario_id, **params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "scenario_type": self.scenario_type.value,
            "required_params": list(self.required_params),
            "optional_params": dict(self.optional_params),
            "tags": list(self.tags),
        }


class ScenarioRegistry:
    """Registry of all available scenario templates."""

    def __init__(self):
        self._templates: dict[str, ScenarioTemplate] = {}
        self._by_type: dict[ScenarioType, list[str]] = {}
        self._register_builtin_scenarios()

    def register(self, template: ScenarioTemplate) -> None:
        """Register a scenario template."""
        self._templates[template.template_id] = template

        if template.scenario_type not in self._by_type:
            self._by_type[template.scenario_type] = []
        self._by_type[template.scenario_type].append(template.template_id)

    def get(self, template_id: str) -> ScenarioTemplate | None:
        """Get a scenario template by ID."""
        return self._templates.get(template_id)

    def list_all(self) -> list[ScenarioTemplate]:
        """List all registered templates."""
        return list(self._templates.values())

    def list_by_type(self, scenario_type: ScenarioType) -> list[ScenarioTemplate]:
        """List templates of a specific type."""
        template_ids = self._by_type.get(scenario_type, [])
        return [self._templates[tid] for tid in template_ids]

    def list_by_tag(self, tag: str) -> list[ScenarioTemplate]:
        """List templates with a specific tag."""
        return [t for t in self._templates.values() if tag in t.tags]

    def instantiate(
        self,
        template_id: str,
        params: dict[str, Any],
    ) -> TwinScenario:
        """Instantiate a scenario from a template."""
        template = self.get(template_id)
        if not template:
            raise ValueError(f"Unknown scenario template: {template_id}")

        # Validate required params
        missing = [p for p in template.required_params if p not in params]
        if missing:
            raise ValueError(f"Missing required parameters: {missing}")

        # Apply optional defaults
        merged = {**template.optional_params, **params}

        return template.instantiate(merged)

    def _register_builtin_scenarios(self) -> None:
        """Register all built-in Program J scenarios."""

        self.register(
            ScenarioTemplate(
                template_id="supplier_failure_v1",
                name="Supplier Failure",
                description="A key supplier experiences disruption causing lead time delays.",
                scenario_type=ScenarioType.SUPPLIER_FAILURE,
                factory=create_supplier_failure_twin_scenario,
                required_params=["supplier_id", "delay_days"],
                optional_params={"disruption_type": "factory_fire"},
                tags=["supply_chain", "disruption", "external"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="demand_spike_v1",
                name="Demand Spike",
                description="Sudden increase in customer demand for a component.",
                scenario_type=ScenarioType.DEMAND_SPIKE,
                factory=create_demand_spike_twin_scenario,
                required_params=["component_id", "demand_change"],
                optional_params={"confidence": 0.8},
                tags=["demand", "market", "external"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="port_closure_v1",
                name="Port Closure",
                description="A shipping route is disrupted due to port closure.",
                scenario_type=ScenarioType.PORT_CLOSURE,
                factory=create_port_closure_scenario,
                required_params=["route_id", "delay_days"],
                optional_params={},
                tags=["logistics", "disruption", "external"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="factory_fire_v1",
                name="Factory Fire",
                description="A factory experiences a fire, reducing capacity to 0%.",
                scenario_type=ScenarioType.FACTORY_FIRE,
                factory=create_factory_fire_scenario,
                required_params=["factory_id"],
                optional_params={"capacity_pct": 0.0, "estimated_recovery_days": 30},
                tags=["internal", "disruption", "critical"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="labor_strike_v1",
                name="Labor Strike",
                description="Factory operating at reduced capacity due to labor strike.",
                scenario_type=ScenarioType.LABOR_STRIKE,
                factory=create_labor_strike_scenario,
                required_params=["factory_id"],
                optional_params={"capacity_pct": 50.0, "estimated_recovery_days": 14},
                tags=["internal", "disruption", "workforce"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="cyber_attack_v1",
                name="Cyber Attack",
                description="Factory offline due to cybersecurity incident.",
                scenario_type=ScenarioType.CYBER_ATTACK,
                factory=create_cyber_attack_scenario,
                required_params=["factory_id"],
                optional_params={"capacity_pct": 0.0, "estimated_recovery_days": 21},
                tags=["internal", "disruption", "security", "critical"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="pandemic_v1",
                name="Pandemic",
                description="Workforce reduction across multiple factories due to pandemic.",
                scenario_type=ScenarioType.PANDEMIC,
                factory=create_pandemic_scenario,
                required_params=["affected_factories"],
                optional_params={"capacity_reduction_pct": 30.0, "duration_days": 90},
                tags=["external", "disruption", "global", "extended"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="weather_v1",
                name="Weather Disruption",
                description="Weather event disrupts multiple shipping routes.",
                scenario_type=ScenarioType.WEATHER,
                factory=create_weather_scenario,
                required_params=["affected_routes", "delay_days"],
                optional_params={},
                tags=["external", "disruption", "logistics", "natural"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="pricing_shock_v1",
                name="Pricing Shock",
                description="Sudden price change for a component.",
                scenario_type=ScenarioType.PRICING_SHOCK,
                factory=create_pricing_shock_scenario,
                required_params=["component_id", "price_multiplier"],
                optional_params={},
                tags=["market", "pricing", "external"],
            )
        )

        self.register(
            ScenarioTemplate(
                template_id="currency_shock_v1",
                name="Currency Shock",
                description="Exchange rate shock affecting multiple components.",
                scenario_type=ScenarioType.CURRENCY_SHOCK,
                factory=create_currency_shock_scenario,
                required_params=["affected_components", "exchange_rate_change"],
                optional_params={},
                tags=["market", "currency", "external", "global"],
            )
        )


# Global singleton
_registry: ScenarioRegistry | None = None


def get_scenario_registry() -> ScenarioRegistry:
    """Get the global scenario registry singleton."""
    global _registry
    if _registry is None:
        _registry = ScenarioRegistry()
    return _registry
