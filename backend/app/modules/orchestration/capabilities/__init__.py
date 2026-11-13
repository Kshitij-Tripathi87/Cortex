"""MAF-5 — real capability adapters for the inventory/procurement vertical slice.

The only execution boundary remains the Nexus Tool Gateway. This package
provides the concrete, application-owned capability adapters behind it:

* ``descriptors`` — typed capability contracts (source, scope, version,
  schema, side-effect class, policy requirements, timeout/error semantics,
  idempotency behavior);
* ``world_state_adapter`` — the real executor backed by authoritative World
  State (reads, risk analysis, and a consequential write through the sole
  write path, ``WorldStateService``);
* ``capability_source`` — workspace-scoped discovery for the registry;
* ``schema_validator`` — input-schema enforcement for capability contracts;
* ``authorizer`` — the application-owned policy adapter behind the gateway.

Specialists and framework agents never receive direct DB, HTTP, or SDK
access; everything they can do is expressed as one of these capabilities.
"""

from .authorizer import WorkspaceCapabilityAuthorizer
from .capability_source import WorldStateCapabilitySource
from .descriptors import WORLD_STATE_CAPABILITY_CONTRACTS, CapabilityContract
from .schema_validator import JsonSchemaLiteValidator
from .world_state_adapter import CapabilityExecutionError, WorldStateCapabilityExecutor

__all__ = [
    "CapabilityContract",
    "CapabilityExecutionError",
    "JsonSchemaLiteValidator",
    "WORLD_STATE_CAPABILITY_CONTRACTS",
    "WorkspaceCapabilityAuthorizer",
    "WorldStateCapabilityExecutor",
    "WorldStateCapabilitySource",
]
