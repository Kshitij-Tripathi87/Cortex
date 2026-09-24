"""MAF-5 — typed capability contracts for the World State vertical slice.

Every real capability declares the full MAF-5 acceptance contract:

* authoritative source — the Nexus-owned component that produces the data;
* tenant/workspace scope — enforced by the capability registry source;
* World State version — resolved from the task context at invocation time;
* capability version — semantic version of the adapter contract itself;
* typed input/output schema — validated by the injected schema validator;
* evidence references — required for every capability in this slice;
* deterministic invocation identity — stable digest of (task, capability,
  arguments), used both by the durable invocation store and by the write
  path's idempotency key;
* explicit side-effect classification — READ vs ANALYZE vs
  WRITE_CONSEQUENTIAL; consequential operations stay behind the approval
  boundary (PROPOSED -> policy -> human approval -> APPROVED -> EXECUTING);
* policy requirements — scopes evaluated by the application authorizer;
* timeout/error semantics — per-capability timeout and explicit error codes;
* idempotency behavior — declared per capability;
* provenance — recorded by the gateway for NexusTrace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import CapabilityDescriptor

_OBJECT = {"type": "object"}

_WORLD_ID_PROPERTY = {
    "world_id": {"type": "string", "description": "Authoritative World State identifier."},
}

_READ_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["world_state_version", "source", "variables"],
    "properties": {
        "world_state_version": {"type": "integer"},
        "source": {"type": "string"},
        "variables": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["variable_id", "variable_type", "entity_id", "value"],
            },
        },
    },
}


def _inventory_read_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["world_id"],
        "properties": {
            **_WORLD_ID_PROPERTY,
            "version": {
                "type": "integer",
                "description": "Optional World State version override; defaults to the task snapshot.",
            },
            "warehouse_id": {"type": "string"},
            "component_id": {"type": "string"},
        },
    }


def _supplier_read_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["world_id", "supplier_id"],
        "properties": {
            **_WORLD_ID_PROPERTY,
            "supplier_id": {"type": "string", "description": "Supplier entity identifier."},
            "version": {"type": "integer"},
        },
    }


def _risk_analyze_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["world_id", "warehouse_id", "component_id"],
        "properties": {
            **_WORLD_ID_PROPERTY,
            "warehouse_id": {"type": "string"},
            "component_id": {"type": "string"},
            "supplier_id": {"type": "string"},
            "version": {"type": "integer"},
        },
    }


def _inventory_adjust_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["world_id", "warehouse_id", "component_id", "quantity_change"],
        "properties": {
            **_WORLD_ID_PROPERTY,
            "warehouse_id": {"type": "string"},
            "component_id": {"type": "string"},
            "quantity_change": {
                "type": "integer",
                "description": "Signed quantity delta; positive increases stock.",
            },
            "reason": {"type": "string"},
        },
    }


@dataclass(frozen=True)
class CapabilityContract:
    """A real capability plus the operational metadata MAF-5 requires."""

    descriptor: CapabilityDescriptor
    authoritative_source: str
    scope: str
    idempotency: str
    error_semantics: str
    provenance: str


def _contract(
    *,
    capability_id: str,
    name: str,
    description: str,
    side_effect: str,
    input_schema: dict[str, Any],
    authoritative_source: str,
    idempotency: str,
    error_semantics: str,
) -> CapabilityContract:
    return CapabilityContract(
        descriptor=CapabilityDescriptor(
            capability_id=capability_id,
            name=name,
            version="1.0.0",
            description=description,
            input_schema=input_schema,
            output_schema=_READ_OUTPUT_SCHEMA
            if side_effect in ("READ", "ANALYZE")
            else {
                "type": "object",
                "required": ["event_id", "world_state_version", "idempotency_key"],
                "properties": {
                    "event_id": {"type": "string"},
                    "version_id": {"type": "string"},
                    "world_state_version": {"type": "integer"},
                    "idempotency_key": {"type": "string"},
                    "is_duplicate": {"type": "boolean"},
                },
            },
            side_effect=side_effect,  # type: ignore[arg-type]
            authorization=("capability:world-state",),
            timeout_seconds=15.0,
            budget_units=1.0,
            evidence_required=True,
        ),
        authoritative_source=authoritative_source,
        scope="tenant_id + workspace_id; World State rows are scoped to both",
        idempotency=idempotency,
        error_semantics=error_semantics,
        provenance="Gateway ToolProvenance (invocation_id, arguments_sha256, "
        "world_state_version) persisted to nexus_task_invocations",
    )


WORLD_STATE_CAPABILITY_CONTRACTS: dict[str, CapabilityContract] = {
    contract.descriptor.capability_id: contract
    for contract in (
        _contract(
            capability_id="world.inventory.read",
            name="World State inventory read",
            description="Read authoritative inventory levels from the workspace World State.",
            side_effect="READ",
            input_schema=_inventory_read_schema(),
            authoritative_source="WorldStateService / StateRepository (world_states, "
            "world_state_events)",
            idempotency="Read-only; the durable invocation store deduplicates repeats by "
            "(task, step, capability, arguments) digest.",
            error_semantics="WORLD_STATE_NOT_FOUND, WORLD_STATE_VERSION_NOT_FOUND; adapter "
            "timeout of 15s surfaces as CAPABILITY_EXECUTION_FAILED.",
        ),
        _contract(
            capability_id="world.supplier.read",
            name="World State supplier read",
            description="Read authoritative supplier lead time and health from World State.",
            side_effect="READ",
            input_schema=_supplier_read_schema(),
            authoritative_source="WorldStateService / StateRepository (lead_time, "
            "supplier_health variables)",
            idempotency="Read-only; deduplicated by (task, step, capability, arguments) digest.",
            error_semantics="WORLD_STATE_NOT_FOUND, WORLD_STATE_VERSION_NOT_FOUND; adapter "
            "timeout of 15s surfaces as CAPABILITY_EXECUTION_FAILED.",
        ),
        _contract(
            capability_id="world.risk.analyze",
            name="Lead-time and stockout risk analysis",
            description="Compute days of cover and risk classification from real World "
            "State values.",
            side_effect="ANALYZE",
            input_schema=_risk_analyze_schema(),
            authoritative_source="WorldStateService (inventory, demand, lead_time variables)",
            idempotency="Pure derivation from one World State version; no side effects.",
            error_semantics="WORLD_STATE_NOT_FOUND, WORLD_STATE_VERSION_NOT_FOUND; adapter "
            "timeout of 15s surfaces as CAPABILITY_EXECUTION_FAILED.",
        ),
        _contract(
            capability_id="world.inventory.adjust",
            name="World State inventory adjustment",
            description="Apply a signed inventory delta to the authoritative World State. "
            "Consequential: requires PROPOSED -> human approval -> APPROVED before "
            "EXECUTING.",
            side_effect="WRITE_CONSEQUENTIAL",
            input_schema=_inventory_adjust_schema(),
            authoritative_source="WorldStateService.submit_event (sole write path; "
            "advisory-locked, append-only)",
            idempotency="Deterministic idempotency key derived from (task, capability, "
            "arguments digest); a replayed key returns the original version without "
            "creating a new one.",
            error_semantics="WORLD_STATE_NOT_FOUND, INVALID_INVENTORY_ARGUMENTS; adapter "
            "timeout of 15s surfaces as CAPABILITY_EXECUTION_FAILED.",
        ),
    )
}


def world_state_capability_ids() -> tuple[str, ...]:
    """Deterministic capability id ordering for this vertical slice."""

    return tuple(sorted(WORLD_STATE_CAPABILITY_CONTRACTS))
