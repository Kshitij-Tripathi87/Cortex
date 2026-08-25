"""Digital Twin Module — Program J Workstream C / J.3.

This module provides the Digital Twin infrastructure for Cortex:

Components:
- Twin Models: DigitalTwin, TwinScenario, TwinRun, TwinResult
- Twin Lineage: compute_twin_lineage_hash, lineage_intact (J.3.1)
- Twin Repository: TwinRepository, TwinDB, TwinRunDB (J.3.1 persistence)
- Twin Isolation: IsolationContext, TwinIsolationEnforcer, production_fingerprint
- Twin Service: TwinService (create/clone, fork, run, get, list, archive, destroy)

Isolation Guarantees (J.3.2):
✓ Never touch Production (reads only, via StateRepository)
✓ Workspace Isolation
✓ Memory Isolation
✓ Snapshot Isolation
✓ Event Log Isolation (twin namespace, not world_state_events)
✓ Immutable Lineage (frozen at creation, fingerprint-verified)
"""

from app.modules.twin.scenario_runtime import ScenarioRuntime
from app.modules.twin.twin_isolation import (
    IsolationContext,
    IsolationError,
    TwinIsolationEnforcer,
    production_fingerprint,
    twin_session,
)
from app.modules.twin.twin_models import (
    TWIN_ENGINE_VERSION,
    TWIN_RNG_VERSION,
    TWIN_SIMULATION_VERSION,
    DigitalTwin,
    Scenario,
    ScenarioEvent,
    ScenarioRun,
    ScenarioType,
    TwinResult,
    TwinRun,
    TwinRunStatus,
    TwinScenario,
    TwinStatus,
    compute_twin_lineage_hash,
    create_capacity_reduction_scenario,
    create_currency_shock_scenario,
    create_cyber_attack_scenario,
    create_demand_spike_scenario,
    create_demand_spike_twin_scenario,
    create_factory_fire_scenario,
    create_inventory_shortage_scenario,
    create_labor_strike_scenario,
    create_pandemic_scenario,
    create_port_closure_scenario,
    create_pricing_shock_scenario,
    create_route_disruption_scenario,
    create_supplier_delay_scenario,
    create_supplier_failure_scenario,
    create_supplier_failure_twin_scenario,
    create_weather_scenario,
    lineage_intact,
)
from app.modules.twin.twin_repository import (
    TwinDB,
    TwinEventDB,
    TwinRepository,
    TwinResultDB,
    TwinRunDB,
    TwinStateDB,
    TwinVersionDB,
)
from app.modules.twin.twin_service import TwinService

__all__ = [
    # Models
    "DigitalTwin",
    "Scenario",
    "ScenarioEvent",
    "ScenarioRun",
    "TwinScenario",
    "TwinRun",
    "TwinResult",
    "TwinStatus",
    "TwinRunStatus",
    "ScenarioType",
    "compute_twin_lineage_hash",
    "lineage_intact",
    "create_supplier_failure_scenario",
    "create_supplier_failure_twin_scenario",
    "create_supplier_delay_scenario",
    "create_inventory_shortage_scenario",
    "create_demand_spike_scenario",
    "create_demand_spike_twin_scenario",
    "create_route_disruption_scenario",
    "create_capacity_reduction_scenario",
    "create_factory_fire_scenario",
    "create_labor_strike_scenario",
    "create_cyber_attack_scenario",
    "create_weather_scenario",
    "create_pricing_shock_scenario",
    "create_currency_shock_scenario",
    "create_pandemic_scenario",
    "create_port_closure_scenario",
    # Provenance constants
    "TWIN_ENGINE_VERSION",
    "TWIN_RNG_VERSION",
    "TWIN_SIMULATION_VERSION",
    # Repository
    "TwinRepository",
    "TwinDB",
    "TwinRunDB",
    "TwinEventDB",
    "TwinVersionDB",
    "TwinStateDB",
    "TwinResultDB",
    # Isolation
    "IsolationContext",
    "IsolationError",
    "TwinIsolationEnforcer",
    "twin_session",
    "production_fingerprint",
    # Service
    "TwinService",
    "ScenarioRuntime",
]
