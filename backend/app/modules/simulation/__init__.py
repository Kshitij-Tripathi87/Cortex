"""Simulation Module — Program J Workstream D.

This module provides the Scenario Runtime for Cortex:

Components:
- Simulation Models: Simulation, SimulationTick, SimulationResult, SimulationConfig
- Timeline: Time-based tracking of simulation state
- Impact Calculator: Business impact analysis
- Scenario Registry: Catalog of available scenarios
- Simulation Engine: Executes scenarios through time

Engine Flow: Clone → Inject → Tick → Tick → Tick → Result
"""

from app.modules.simulation.impact_calculator import (
    ImpactCalculator,
    ImpactThresholds,
)
from app.modules.simulation.scenario_registry import (
    ScenarioRegistry,
    ScenarioTemplate,
    get_scenario_registry,
)
from app.modules.simulation.simulation_engine import SimulationEngine
from app.modules.simulation.simulation_models import (
    ImpactSummary,
    Simulation,
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
    SimulationTick,
    TickGranularity,
)
from app.modules.simulation.timeline import TickDelta, Timeline

__all__ = [
    # Models
    "Simulation",
    "SimulationConfig",
    "SimulationResult",
    "SimulationStatus",
    "SimulationTick",
    "TickGranularity",
    "ImpactSummary",
    # Timeline
    "Timeline",
    "TickDelta",
    # Impact
    "ImpactCalculator",
    "ImpactThresholds",
    # Registry
    "ScenarioRegistry",
    "ScenarioTemplate",
    "get_scenario_registry",
    # Engine
    "SimulationEngine",
]
