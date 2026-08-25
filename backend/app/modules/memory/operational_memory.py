"""Operational Memory Engine — Current Operational State and Entity Context.

Stores live variables, stock levels, supplier statuses, and open disruptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.world.world_models import StateVariable, WorldState


@dataclass
class OperationalMemoryEngine:
    """Provides fast workspace-scoped access to live operational variables."""

    def __init__(self) -> None:
        self._states: dict[str, WorldState] = {}

    def update_state(self, world_state: WorldState) -> None:
        """Store or update the current world state."""
        self._states[world_state.workspace_id] = world_state

    def set_live_world_state(
        self, tenant_id: str, workspace_id: str, world_state: WorldState
    ) -> None:
        """Tenant-scoped live state update."""
        self._states[workspace_id] = world_state

    def get_live_world_state(
        self, tenant_id: str, workspace_id: str
    ) -> WorldState | None:
        """Tenant-scoped live state fetch."""
        return self._states.get(workspace_id)

    def get_state(self, workspace_id: str) -> WorldState | None:
        """Retrieve latest operational state for workspace."""
        return self._states.get(workspace_id)

    def query_variable(
        self, workspace_id: str, variable_id: str
    ) -> StateVariable | None:
        """Fetch specific state variable."""
        state = self.get_state(workspace_id)
        if not state:
            return None
        for var in state.variables:
            if var.variable_id == variable_id:
                return var
        return None

    def get_summary(self, workspace_id: str) -> dict[str, Any]:
        """Return operational state summary metrics."""
        state = self.get_state(workspace_id)
        if not state:
            return {"status": "uninitialized", "variable_count": 0}
        return {
            "world_id": state.world_id,
            "version": state.version,
            "graph_version": state.graph_version,
            "variable_count": len(state.variables),
            "stockout_occurrences": state.stockout_occurrences,
            "state_hash": state.state_hash,
        }


_global_operational_mem = OperationalMemoryEngine()


def get_operational_memory() -> OperationalMemoryEngine:
    return _global_operational_mem
