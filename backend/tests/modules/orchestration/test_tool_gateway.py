from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.modules.orchestration.contracts import AgentContext, CapabilityDescriptor
from app.modules.orchestration.tool_gateway import AuthorizationDecision, NexusToolGateway


CAP = CapabilityDescriptor(
    capability_id="inventory.read",
    name="Read inventory",
    version="1.0.0",
    description="Read authoritative inventory state.",
    input_schema={"type": "object", "required": ["sku"]},
    output_schema={"type": "object"},
    side_effect="READ",
    budget_units=1.0,
    evidence_required=True,
)


@dataclass
class Authorizer:
    allowed: bool = True

    async def authorize(self, *, capability, context) -> AuthorizationDecision:
        return AuthorizationDecision(self.allowed, "allowed" if self.allowed else "denied", "p-test")


@dataclass
class Validator:
    valid: bool = True

    def validate(self, *, schema, arguments) -> None:
        if not self.valid:
            raise ValueError("invalid")
        if "sku" not in arguments:
            raise ValueError("sku required")


@dataclass
class Executor:
    calls: int = 0
    payload: dict[str, object] = field(default_factory=lambda: {"evidence_refs": ("e:1",)})

    async def execute(self, *, capability, arguments, context) -> dict[str, object]:
        self.calls += 1
        return dict(self.payload)


@dataclass
class Trace:
    results: list[object] = field(default_factory=list)

    async def record_tool_invocation(self, *, result) -> None:
        self.results.append(result)


def context(**kwargs) -> AgentContext:
    values = dict(
        workspace_id=uuid4(),
        tenant_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
        actor_id=uuid4(),
        world_state_version=42,
        allowed_capabilities=("inventory.read",),
        budget=100.0,
        policy_context={},
    )
    values.update(kwargs)
    return AgentContext(**values)


def gateway(*, authorizer=None, validator=None, executor=None, trace=None):
    ex = executor or Executor()
    tr = trace or Trace()
    gw = NexusToolGateway(
        authorizer=authorizer or Authorizer(),
        executor=ex,
        schema_validator=validator or Validator(),
        trace_writer=tr,
    )
    return gw, ex, tr


@pytest.mark.asyncio
async def test_allow_list_is_enforced_before_execution():
    gw, ex, tr = gateway()
    result = await gw.invoke(capability=CAP, arguments={"sku": "S1"}, context=context(allowed_capabilities=()))
    assert result.status == "BLOCKED"
    assert result.error == "CAPABILITY_NOT_ALLOWED"
    assert ex.calls == 0
    assert tr.results[-1] == result


@pytest.mark.asyncio
async def test_budget_is_enforced_before_execution():
    gw, ex, _ = gateway()
    result = await gw.invoke(capability=CAP, arguments={"sku": "S1"}, context=context(budget=0.5))
    assert result.status == "BLOCKED"
    assert result.error == "BUDGET_EXCEEDED"
    assert ex.calls == 0


@pytest.mark.asyncio
async def test_deadline_is_enforced_before_execution():
    gw, ex, _ = gateway()
    result = await gw.invoke(
        capability=CAP,
        arguments={"sku": "S1"},
        context=context(deadline=datetime.now(timezone.utc) - timedelta(seconds=1)),
    )
    assert result.status == "BLOCKED"
    assert result.error == "DEADLINE_EXCEEDED"
    assert ex.calls == 0


@pytest.mark.asyncio
async def test_schema_failure_is_blocked_and_traced():
    gw, ex, tr = gateway(validator=Validator(valid=False))
    result = await gw.invoke(capability=CAP, arguments={"sku": "S1"}, context=context())
    assert result.status == "BLOCKED"
    assert result.error == "INVALID_ARGUMENTS"
    assert ex.calls == 0
    assert tr.results[-1] == result


@pytest.mark.asyncio
async def test_policy_denial_is_blocked_and_traced():
    gw, ex, tr = gateway(authorizer=Authorizer(allowed=False))
    result = await gw.invoke(capability=CAP, arguments={"sku": "S1"}, context=context())
    assert result.status == "BLOCKED"
    assert result.error == "POLICY_DENIED"
    assert ex.calls == 0
    assert tr.results[-1] == result


@pytest.mark.asyncio
async def test_success_is_evidence_bearing_and_scoped():
    gw, _, _ = gateway()
    result = await gw.invoke(capability=CAP, arguments={"sku": "S1"}, context=context())
    assert result.status == "SUCCESS"
    assert result.capability_id == "inventory.read"
    assert result.capability_version == "1.0.0"
    assert result.world_state_version == 42
    assert result.evidence_refs == ("e:1",)
    assert result.provenance.workspace_id == result.workspace_id
    assert result.provenance.task_id == result.task_id
    assert result.provenance.trace_id == result.trace_id


@pytest.mark.asyncio
async def test_missing_evidence_cannot_be_success():
    gw, ex, _ = gateway(executor=Executor(payload={"value": 1}))
    result = await gw.invoke(capability=CAP, arguments={"sku": "S1"}, context=context())
    assert result.status == "FAILED"
    assert result.error == "EVIDENCE_REQUIRED"
    assert ex.calls == 1


@pytest.mark.asyncio
async def test_consequential_side_effect_requires_gate():
    cap = CapabilityDescriptor(
        capability_id="inventory.adjust",
        name="Adjust inventory",
        version="1.0.0",
        description="Apply an authorized adjustment.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect="WRITE_CONSEQUENTIAL",
        budget_units=1.0,
        evidence_required=True,
    )
    gw, ex, _ = gateway()
    result = await gw.invoke(
        capability=cap,
        arguments={"sku": "S1", "quantity": 10},
        context=context(allowed_capabilities=("inventory.adjust",)),
    )
    assert result.status == "BLOCKED"
    assert result.error == "APPROVAL_REQUIRED"
    assert ex.calls == 0
