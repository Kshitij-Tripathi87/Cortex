"""MAF-5 — the real capability executor behind the Nexus Tool Gateway.

This adapter is the concrete business capability for the inventory and
procurement vertical slice. It reads from — and writes through —
``WorldStateService``, the sole authoritative write path for World State
mutations. It never issues direct SQL, HTTP, or SDK calls, and it is never
handed to specialists directly: only the Tool Gateway can reach it.

Side-effect discipline:

* ``world.inventory.read`` / ``world.supplier.read`` — READ; participates in
  reasoning and produces evidence references.
* ``world.risk.analyze`` — ANALYZE; pure derivation over one World State
  version.
* ``world.inventory.adjust`` — WRITE_CONSEQUENTIAL; a real ``InventoryChanged``
  event is submitted through ``WorldStateService.submit_event`` only after the
  gateway's approval boundary has been satisfied (PROPOSED -> human approval
  -> APPROVED -> EXECUTING). The write is idempotent: the idempotency key is
  derived deterministically from (task, capability, arguments), so a replayed
  invocation returns the original World State version instead of creating a
  duplicate.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from app.modules.events.event_models import InventoryChanged
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariableType
from app.modules.world.world_service import WorldStateService

from ..contracts import AgentContext, CapabilityDescriptor
from ..tool_gateway import CapabilityExecutor


class CapabilityExecutionError(RuntimeError):
    """Explicit adapter error; code becomes the durable error semantics."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


class _SessionSessionFactory(Protocol):
    def __call__(self) -> Any: ...


class WorldStateCapabilityExecutor(CapabilityExecutor):
    """Real capability adapter backed by authoritative World State."""

    def __init__(self, *, session_factory: _SessionSessionFactory) -> None:
        self._session_factory = session_factory

    async def execute(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        handler = self._handler_for(capability.capability_id)
        try:
            return await asyncio.wait_for(
                handler(capability=capability, arguments=arguments, context=context),
                timeout=capability.timeout_seconds,
            )
        except TimeoutError as exc:
            raise CapabilityExecutionError(
                "ADAPTER_TIMEOUT",
                f"{capability.capability_id} exceeded its {capability.timeout_seconds}s budget.",
            ) from exc

    def _handler_for(self, capability_id: str) -> Any:
        handlers = {
            "world.inventory.read": self._read_inventory,
            "world.supplier.read": self._read_supplier,
            "world.risk.analyze": self._analyze_risk,
            "world.inventory.adjust": self._adjust_inventory,
        }
        handler = handlers.get(capability_id)
        if handler is None:
            raise CapabilityExecutionError(
                "UNKNOWN_CAPABILITY",
                f"{capability_id} is not a World State capability.",
            )
        return handler

    # ── Shared helpers ────────────────────────────────────────────────────────

    @asynccontextmanager
    async def _world_service(self) -> AsyncGenerator[WorldStateService]:
        """Own the per-invocation session lifecycle: open, use, close.

        ``WorldStateService`` never closes the session it is handed; without
        this wrapper each capability invocation leaked a pooled connection
        to the garbage collector.
        """
        session = self._session_factory()
        try:
            yield WorldStateService(repository=StateRepository(db=session))
        finally:
            await session.close()

    @staticmethod
    def _world_id(arguments: dict[str, Any]) -> str:
        world_id = arguments.get("world_id")
        if not isinstance(world_id, str) or not world_id:
            raise CapabilityExecutionError("INVALID_ARGUMENTS", "world_id is required.")
        return world_id

    @staticmethod
    def _version(arguments: dict[str, Any], context: AgentContext) -> int:
        """World State version: explicit argument overrides the task snapshot."""

        override = arguments.get("version")
        if override is not None and not isinstance(override, bool):
            return int(override)
        return context.world_state_version

    async def _state_at_version(self, world_id: str, workspace_id: str, version: int) -> Any:
        async with self._world_service() as service:
            state = await service.get_state_at_version(
                world_id=world_id, workspace_id=workspace_id, version=version
            )
        if state is None:
            raise CapabilityExecutionError(
                "WORLD_STATE_VERSION_NOT_FOUND",
                f"World {world_id} has no version {version} in this workspace.",
            )
        return state

    @staticmethod
    def _raw(state: Any, variable_id: str) -> float | int:
        variable = state.get_variable(variable_id)
        if variable is None:
            return 0
        return variable.raw_value  # type: ignore[no-any-return]

    @staticmethod
    def _inventory_var_id(warehouse_id: str, component_id: str) -> str:
        return f"inventory.warehouse.{component_id}.{warehouse_id}"

    @staticmethod
    def _variable_records(state: Any, variable_ids: list[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for variable_id in variable_ids:
            variable = state.get_variable(variable_id)
            if variable is None:
                continue
            records.append(
                {
                    "variable_id": variable.variable_id,
                    "variable_type": variable.variable_type.value,
                    "entity_id": variable.entity_id,
                    "entity_type": variable.entity_type,
                    "value": variable.raw_value,
                    "unit": variable.unit,
                    "observed_at": variable.value.provenance.observed_at.isoformat(),
                    "source_event_id": variable.value.provenance.source_event_id,
                }
            )
        return records

    @staticmethod
    def _evidence_ref(world_id: str, version: int, variable_id: str) -> str:
        return f"world-state:{world_id}:v{version}:{variable_id}"

    @staticmethod
    def _arguments_digest(arguments: dict[str, Any]) -> str:
        payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(payload.encode("utf-8")).hexdigest()

    # ── READ capabilities ─────────────────────────────────────────────────────

    async def _read_inventory(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        del capability
        world_id = self._world_id(arguments)
        version = self._version(arguments, context)
        state = await self._state_at_version(world_id, str(context.workspace_id), version)

        variable_ids: list[str] = []
        warehouse_id = arguments.get("warehouse_id")
        component_id = arguments.get("component_id")
        if isinstance(warehouse_id, str) and isinstance(component_id, str):
            variable_ids.append(self._inventory_var_id(warehouse_id, component_id))
        else:
            variable_ids = sorted(
                variable.variable_id
                for variable in state.get_variables_by_type(StateVariableType.INVENTORY)
            )

        return {
            "world_state_version": state.version,
            "source": "world_states",
            "variables": self._variable_records(state, variable_ids),
            "evidence_refs": tuple(
                self._evidence_ref(world_id, state.version, variable_id)
                for variable_id in variable_ids
            ),
        }

    async def _read_supplier(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        del capability
        world_id = self._world_id(arguments)
        version = self._version(arguments, context)
        supplier_id = arguments.get("supplier_id")
        if not isinstance(supplier_id, str) or not supplier_id:
            raise CapabilityExecutionError("INVALID_ARGUMENTS", "supplier_id is required.")
        state = await self._state_at_version(world_id, str(context.workspace_id), version)

        variable_ids = [
            f"lead_time.supplier.{supplier_id}",
            f"supplier_health.supplier.{supplier_id}",
        ]
        return {
            "world_state_version": state.version,
            "source": "world_states",
            "variables": self._variable_records(state, variable_ids),
            "evidence_refs": tuple(
                self._evidence_ref(world_id, state.version, variable_id)
                for variable_id in variable_ids
            ),
        }

    # ── ANALYZE capability ────────────────────────────────────────────────────

    async def _analyze_risk(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        del capability
        world_id = self._world_id(arguments)
        version = self._version(arguments, context)
        warehouse_id = arguments.get("warehouse_id")
        component_id = arguments.get("component_id")
        if not isinstance(warehouse_id, str) or not isinstance(component_id, str):
            raise CapabilityExecutionError(
                "INVALID_ARGUMENTS", "warehouse_id and component_id are required."
            )
        state = await self._state_at_version(world_id, str(context.workspace_id), version)

        inventory_var_id = self._inventory_var_id(warehouse_id, component_id)
        demand_var_id = f"demand.component.{component_id}"
        inventory_qty = self._raw(state, inventory_var_id)
        daily_demand = self._raw(state, demand_var_id)

        supplier_id = arguments.get("supplier_id")
        lead_time_days: float | int = 0
        lead_time_var_id: str | None = None
        if isinstance(supplier_id, str) and supplier_id:
            lead_time_var_id = f"lead_time.supplier.{supplier_id}"
            lead_time_days = self._raw(state, lead_time_var_id)

        days_of_cover: float | None = None
        if daily_demand and daily_demand > 0:
            days_of_cover = round(inventory_qty / daily_demand, 4)

        if days_of_cover is None:
            risk_class = "LOW"
        elif lead_time_days and days_of_cover < lead_time_days:
            risk_class = "CRITICAL"
        elif lead_time_days and days_of_cover < 2 * lead_time_days:
            risk_class = "HIGH"
        else:
            risk_class = "MEDIUM" if days_of_cover < 14 else "LOW"

        variable_ids = [inventory_var_id, demand_var_id]
        if lead_time_var_id is not None:
            variable_ids.append(lead_time_var_id)
        return {
            "world_state_version": state.version,
            "source": "world_states",
            "warehouse_id": warehouse_id,
            "component_id": component_id,
            "inventory_qty": inventory_qty,
            "daily_demand": daily_demand,
            "lead_time_days": lead_time_days,
            "days_of_cover": days_of_cover,
            "risk_class": risk_class,
            "variables": self._variable_records(state, variable_ids),
            "evidence_refs": tuple(
                self._evidence_ref(world_id, state.version, variable_id)
                for variable_id in variable_ids
                if state.get_variable(variable_id) is not None
            ),
        }

    # ── CONSEQUENTIAL WRITE capability ────────────────────────────────────────

    async def _adjust_inventory(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        world_id = self._world_id(arguments)
        warehouse_id = arguments.get("warehouse_id")
        component_id = arguments.get("component_id")
        quantity_change = arguments.get("quantity_change")
        if not isinstance(warehouse_id, str) or not isinstance(component_id, str):
            raise CapabilityExecutionError(
                "INVALID_ARGUMENTS", "warehouse_id and component_id are required."
            )
        if not isinstance(quantity_change, int) or isinstance(quantity_change, bool):
            raise CapabilityExecutionError(
                "INVALID_INVENTORY_ARGUMENTS", "quantity_change must be an integer delta."
            )
        reason = arguments.get("reason", "task_execution")
        if not isinstance(reason, str) or not reason:
            reason = "task_execution"

        idempotency_key = (
            f"task:{context.task_id}:capability:{capability.capability_id}:"
            f"{self._arguments_digest(arguments)}"
        )
        event = InventoryChanged(
            event_id=str(uuid4()),
            world_id=world_id,
            workspace_id=str(context.workspace_id),
            entity_type="warehouse",
            entity_id=warehouse_id,
            warehouse_id=warehouse_id,
            component_id=component_id,
            quantity_change=quantity_change,
            reason=reason,
            metadata={
                "task_id": str(context.task_id),
                "capability_id": capability.capability_id,
                "capability_version": capability.version,
                "actor_id": str(context.actor_id),
            },
        )
        async with self._world_service() as service:
            result = await service.submit_event(event, idempotency_key=idempotency_key)

        new_version = result.version
        variable_id = self._inventory_var_id(warehouse_id, component_id)
        return {
            "event_id": result.event_id,
            "version_id": result.version_id,
            "world_state_version": new_version,
            "idempotency_key": idempotency_key,
            "is_duplicate": result.is_duplicate,
            "evidence_refs": (self._evidence_ref(world_id, new_version, variable_id),),
        }
