"""Scenario-1 — isolated scenario worlds over the production World State.

A scenario consumes the same World State snapshot the task runtime uses:

    Production World State
        │
        ├──────────────→ baseline (authoritative, versioned)
        │
        └──────────────→ isolated scenario world
                              │
                         parameter changes (redirected into isolation)
                              │
                         deterministic simulation
                              │
                         outcome

The key invariant — **scenario mutation must never write to production
World State** — is enforced structurally and verified explicitly:

1. Every parameter event is rewritten into the isolated scenario world id
   before submission, even one that was mis-specified against production.
2. All World State rows, events, versions, and lineage for the scenario live
   under the scenario world id; the production world_id is never touched.
3. After simulation, the production state version is re-read and compared to
   the pre-simulation version; any drift raises ScenarioIsolationError.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.common.ids import uuid7
from app.modules.events.event_models import WorldEvent
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateMetadata, WorldState
from app.modules.world.world_service import WorldStateService


class ScenarioIsolationError(RuntimeError):
    """Raised when scenario execution would violate production isolation."""


@dataclass(frozen=True)
class ScenarioOutcome:
    """Durable-shaped result of one scenario run."""

    scenario_world_id: str
    workspace_id: str
    baseline_world_id: str
    baseline_version: int
    scenario_version: int
    applied_event_ids: tuple[str, ...]
    variables_changed: tuple[str, ...]
    deltas: dict[str, float | int | str]
    state: WorldState


class _WorldServiceFactory(Protocol):
    def __call__(self) -> WorldStateService: ...


class ScenarioService:
    """Runs parameterized simulations in isolated scenario worlds."""

    def __init__(
        self, *, session_factory: Any, world_service_factory: _WorldServiceFactory | None = None
    ) -> None:
        self._session_factory = session_factory
        self._world_service_factory = world_service_factory or self._default_world_service_factory

    def _default_world_service_factory(self) -> WorldStateService:
        return WorldStateService(repository=StateRepository(db=self._session_factory()))

    async def run_scenario(
        self,
        *,
        workspace_id: str,
        world_id: str,
        baseline_version: int,
        parameter_events: list[WorldEvent],
        created_by: str = "nexus_scenario",
    ) -> ScenarioOutcome:
        """Simulate parameter changes against an isolated copy of the baseline.

        The baseline is the exact World State version a task runtime would
        read; the scenario never writes to the production world.
        """
        service = self._world_service_factory()
        baseline = await service.get_state_at_version(
            world_id=world_id, workspace_id=workspace_id, version=baseline_version
        )
        if baseline is None:
            raise ScenarioIsolationError(
                f"World {world_id} has no version {baseline_version} in this workspace."
            )

        production_version_before = await self._production_version(service, workspace_id, world_id)

        scenario_world_id = f"scenario:{uuid7()}"
        scenario_state = await service.initialize_world(
            workspace_id=workspace_id,
            world_id=scenario_world_id,
            graph_version=baseline.graph_version,
            initial_variables=dict(baseline.variables),
            metadata={
                "source": "simulation",
                "parent_world_id": world_id,
                "parent_version": baseline_version,
                "created_by": created_by,
            },
        )
        await self._record_lineage(
            workspace_id=workspace_id,
            scenario_world_id=scenario_world_id,
            baseline_world_id=world_id,
            baseline_version=baseline_version,
            graph_version=baseline.graph_version,
        )

        applied: list[Any] = []
        for index, event in enumerate(parameter_events):
            # Structural isolation: parameter changes are rewritten into the
            # scenario world before submission, never aimed at production.
            scenario_event = replace(event, world_id=scenario_world_id, workspace_id=workspace_id)
            result = await service.submit_event(
                scenario_event,
                idempotency_key=f"scenario:{scenario_world_id}:{index}",
            )
            applied.append(result)

        final_state = applied[-1].state if applied else scenario_state
        deltas, variables_changed = _deltas_against(baseline, final_state)

        production_version_after = await self._production_version(service, workspace_id, world_id)
        if (
            production_version_before is not None
            and production_version_after != production_version_before
        ):
            raise ScenarioIsolationError(
                "Scenario mutation wrote to production World State: "
                f"version moved {production_version_before} -> {production_version_after}."
            )

        return ScenarioOutcome(
            scenario_world_id=scenario_world_id,
            workspace_id=workspace_id,
            baseline_world_id=world_id,
            baseline_version=baseline_version,
            scenario_version=final_state.version,
            applied_event_ids=tuple(result.event_id for result in applied),
            variables_changed=variables_changed,
            deltas=deltas,
            state=final_state,
        )

    async def _production_version(
        self, service: WorldStateService, workspace_id: str, world_id: str
    ) -> int | None:
        state = await service.get_current_state(workspace_id, world_id)
        return state.version if state is not None else None

    async def _record_lineage(
        self,
        *,
        workspace_id: str,
        scenario_world_id: str,
        baseline_world_id: str,
        baseline_version: int,
        graph_version: int,
    ) -> None:
        async with self._session_factory() as session:
            repo = StateRepository(db=session)
            await repo.store_metadata(
                StateMetadata(
                    workspace_id=workspace_id,
                    world_id=scenario_world_id,
                    version=1,
                    graph_version=graph_version,
                    source="simulation",
                    parent_world_id=baseline_world_id,
                    parent_version=baseline_version,
                    tags=["scenario"],
                )
            )
            await session.commit()


def _deltas_against(
    baseline: WorldState, final_state: WorldState
) -> tuple[dict[str, float | int | str], tuple[str, ...]]:
    """Deterministic per-variable deltas of the scenario against the baseline."""

    deltas: dict[str, float | int | str] = {}
    for variable_id in sorted(final_state.variables):
        variable = final_state.variables[variable_id]
        base_variable = baseline.variables.get(variable_id)
        base_value = base_variable.raw_value if base_variable is not None else 0
        value = variable.raw_value
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            if value != base_value:
                deltas[variable_id] = str(value)
            continue
        if value != base_value:
            deltas[variable_id] = value - base_value  # type: ignore[operator]
    return deltas, tuple(deltas)
