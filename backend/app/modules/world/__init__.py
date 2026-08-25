"""World State & Digital Twin — Program J.

This module contains the World State Engine and supporting infrastructure
for Cortex's event-sourced world model and digital twin capabilities.

Components:
- World State Engine: Immutable world state, snapshots, transitions
- State Repository: Persistence layer (PostgreSQL + event store)
- State Projection: Pure functions for event -> state projection
- State History: Replay, time-travel, rollback, comparison
- State Diff: Difference engine for state changes
- World Validation: Validation rules for state integrity

This is the foundation upon which Programs K (GNN), L (RL), M (Agent Runtime),
and N (Execution Plane) will be built.
"""

from app.modules.world.state_diff import (
    DiffEngine,
    DiffFormatter,
    DiffSummary,
    EntityDiff,
    StateDiff,
    TimeSeriesDiff,
    TimeSeriesDiffEngine,
    VariableDiff,
)
from app.modules.world.state_history import (
    ReplayEngine,
    ReplayResult,
    RollbackEngine,
    RollbackResult,
    StateComparison,
    StateDiffEngine,
    TimeTravelResult,
    compare_states,
    get_state_at_time,
    get_state_history,
)
from app.modules.world.state_projection import (
    apply_transition,
    apply_transitions,
    create_initial_state,
    create_state_snapshot,
    project_capacity_change,
    project_demand_change,
    project_factory_shutdown,
    project_inventory_change,
    project_order_placed,
    project_price_change,
    project_route_disruption,
    project_shipment_delayed,
    project_supplier_delay,
    reconstruct_state,
    replay_from_snapshot,
    validate_state_hash,
)
from app.modules.world.state_repository import (
    StateRepository,
    WorldMetadataDB,
    WorldSnapshotDB,
    WorldStateDB,
    WorldStateEventDB,
    WorldVersionDB,
)
from app.modules.world.world_models import (
    StateMetadata,
    StateSummary,
    StateTransition,
    StateTransitionType,
    StateVariable,
    StateVariableType,
    WorldSnapshot,
    WorldState,
)
from app.modules.world.world_service import (
    SubmitEventResult,
    WorldStateService,
)
from app.modules.world.world_validation import (
    ValidationIssue,
    ValidationResult,
    ValidationRules,
    ValidationSeverity,
    WorldValidator,
    get_state_errors,
    is_valid_state,
    validate_snapshot,
    validate_state,
)

__all__ = [
    # Service
    "WorldStateService",
    "SubmitEventResult",
    # World Models
    "StateVariable",
    "StateVariableType",
    "StateTransition",
    "StateTransitionType",
    "WorldState",
    "WorldSnapshot",
    "StateMetadata",
    "StateSummary",
    # Repository
    "StateRepository",
    "WorldStateDB",
    "WorldStateEventDB",
    "WorldSnapshotDB",
    "WorldVersionDB",
    "WorldMetadataDB",
    # Projection
    "apply_transition",
    "apply_transitions",
    "create_initial_state",
    "create_state_snapshot",
    "validate_state_hash",
    "reconstruct_state",
    "replay_from_snapshot",
    "project_inventory_change",
    "project_supplier_delay",
    "project_factory_shutdown",
    "project_route_disruption",
    "project_order_placed",
    "project_demand_change",
    "project_capacity_change",
    "project_shipment_delayed",
    "project_price_change",
    # History
    "ReplayEngine",
    "StateDiffEngine",
    "RollbackEngine",
    "ReplayResult",
    "TimeTravelResult",
    "StateComparison",
    "RollbackResult",
    "compare_states",
    "get_state_at_time",
    "get_state_history",
    # Diff
    "DiffEngine",
    "TimeSeriesDiffEngine",
    "DiffFormatter",
    "DiffSummary",
    "VariableDiff",
    "EntityDiff",
    "StateDiff",
    "TimeSeriesDiff",
    # Validation
    "WorldValidator",
    "ValidationRules",
    "ValidationIssue",
    "ValidationResult",
    "ValidationSeverity",
    "validate_state",
    "validate_snapshot",
    "is_valid_state",
    "get_state_errors",
]
