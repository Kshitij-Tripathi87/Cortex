"""Agent Runtime API — Multi-Agent Deliberation, Decision Room, and Tool Execution.

Endpoints:
- POST /api/v1/agents/deliberate — Run multi-agent deliberation protocol
- GET /api/v1/agents/registry — List registered agents and capabilities
- GET /api/v1/agents/tools — List registered tools
- POST /api/v1/agents/tools/execute — Execute a tool within capability context
- GET /api/v1/agents/conversations — List past multi-agent deliberations
- GET /api/v1/agents/conversations/{id} — Retrieve full conversation trace
- GET /api/v1/agents/decision-room/{id} — Retrieve Decision Room chronological timeline
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.common.capabilities import Capability
from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.infrastructure.message_bus import NexusTopic, get_message_bus
from app.infrastructure.realtime_gateway import RealtimeChannel, get_realtime_gateway
from app.infrastructure.security import get_current_user
from app.modules.identity.models import UserPrincipal
from app.modules.multi_agent.runtime.builtin_tools import create_default_tool_registry
from app.modules.multi_agent.runtime.conversation_store import (
    ConversationRecord,
    get_conversation_store,
)
from app.modules.multi_agent.runtime.supervisor import (
    AgentSupervisor,
    SupervisorTask,
    TaskPriority,
)

router = APIRouter(prefix="/agents", tags=["Agent Runtime"])

_supervisor = AgentSupervisor()
_tool_registry = create_default_tool_registry()
_conv_store = get_conversation_store()
_bus = get_message_bus()
_rt_gateway = get_realtime_gateway()


class DeliberationRequest(BaseModel):
    task_type: str = Field(default="disruption_mitigation", description="Task type discriminator")
    description: str = Field(description="Operational incident or problem description")
    world_state_version: int = Field(default=1, description="Target world state version")
    priority: str = Field(default="NORMAL", description="Task priority (LOW, NORMAL, HIGH, CRITICAL)")
    scenario_id: str | None = None
    target_disruption_id: str | None = None


class ToolExecuteRequest(BaseModel):
    tool_name: str
    input_data: dict[str, Any] = Field(default_factory=dict)


@router.post("/deliberate")
async def run_deliberation(
    req: DeliberationRequest,
    principal: UserPrincipal = Depends(get_current_user),
    x_workspace_id: str = Header(default="default_workspace"),
    x_organization_id: str = Header(default="default_org"),
) -> dict[str, Any]:
    """Execute a 3-round multi-agent deliberation across domain specialist agents."""
    ctx = ExecutionContext.from_request(
        principal=principal,
        workspace_id=x_workspace_id,
        organization_id=x_organization_id,
    )

    priority_enum = TaskPriority.NORMAL
    try:
        priority_enum = TaskPriority(req.priority.upper())
    except ValueError:
        pass

    task = SupervisorTask(
        task_id=f"task_{uuid7()}",
        task_type=req.task_type,
        description=req.description,
        world_state_version=req.world_state_version,
        priority=priority_enum,
        scenario_id=req.scenario_id,
        target_disruption_id=req.target_disruption_id,
    )

    result = await _supervisor.run_deliberation(task=task, context=ctx)

    # Save to persistent conversation store
    conv_record = ConversationRecord(
        conversation_id=f"conv_{result.result_id}",
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        workspace_id=ctx.workspace_id,
        task_id=task.task_id,
        task_description=task.description,
        status=result.status.value,
        consensus_score=result.consensus_score,
        started_at=ctx.timestamp,
        completed_at=ctx.timestamp,
        messages=result.messages,
        proposals=result.proposals,
        critiques=result.critiques,
        synthesis=result.synthesis,
        participating_agents=result.participating_agents,
        total_cost_usd=result.total_cost_usd,
        errors=result.errors,
    )
    _conv_store.save(conv_record)

    # Publish messages to message bus and broadcast to real-time Decision Room
    for msg in result.messages:
        await _bus.publish(topic=NexusTopic.AGENT_MESSAGES, envelope=msg)

    await _rt_gateway.broadcast(
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        channel=RealtimeChannel.AGENT_MESSAGES,
        event_type="agent.deliberation.completed",
        payload=result.to_dict(),
    )

    return result.to_dict()


@router.get("/registry")
async def list_agents() -> dict[str, Any]:
    """List all registered specialist agents and their functional roles."""
    return {
        "agents": [
            {
                "name": "Sourcing Specialist",
                "role": "sourcing_specialist",
                "capabilities": ["read", "analyze", "propose"],
                "focus": "Supplier health, expedited sourcing, alternate supplier discovery",
            },
            {
                "name": "Inventory Specialist",
                "role": "inventory_specialist",
                "capabilities": ["read", "analyze", "propose"],
                "focus": "Stockout avoidance, warehouse transfer, safety stock buffer",
            },
            {
                "name": "Logistics Specialist",
                "role": "logistics_specialist",
                "capabilities": ["read", "analyze", "propose"],
                "focus": "Carrier rerouting, port congestion bypass, expedited freight",
            },
            {
                "name": "Production Specialist",
                "role": "production_specialist",
                "capabilities": ["read", "analyze", "propose"],
                "focus": "Factory capacity allocation, work order rescheduling, assembly priority",
            },
            {
                "name": "Executive Coordinator",
                "role": "executive_coordinator",
                "capabilities": ["read", "analyze", "propose", "simulate"],
                "focus": "Conflict resolution, multi-specialist consensus synthesis",
            },
        ]
    }


@router.get("/tools")
async def list_tools(
    principal: UserPrincipal = Depends(get_current_user),
) -> dict[str, Any]:
    """List all available tools governed by the tool registry."""
    tools = _tool_registry.list_available(frozenset({Capability.EXECUTE.value}))
    return {"tools": [t.to_dict() for t in tools]}


@router.post("/tools/execute")
async def execute_tool(
    req: ToolExecuteRequest,
    principal: UserPrincipal = Depends(get_current_user),
    x_workspace_id: str = Header(default="default_workspace"),
    x_organization_id: str = Header(default="default_org"),
) -> dict[str, Any]:
    """Execute a tool through the capability and audit boundary."""
    ctx = ExecutionContext.from_request(
        principal=principal,
        workspace_id=x_workspace_id,
        organization_id=x_organization_id,
    )
    result = await _tool_registry.execute(req.tool_name, req.input_data, ctx)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.to_dict()


@router.get("/conversations")
async def list_conversations(
    principal: UserPrincipal = Depends(get_current_user),
    x_workspace_id: str = Header(default="default_workspace"),
) -> dict[str, Any]:
    """List past multi-agent deliberations in the current workspace."""
    convs = _conv_store.list_by_workspace(x_workspace_id)
    return {"conversations": [c.to_dict() for c in convs]}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    principal: UserPrincipal = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve full details of a specific deliberation conversation."""
    conv = _conv_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv.to_dict()


@router.get("/decision-room/{conversation_id}")
async def get_decision_room_timeline(
    conversation_id: str,
    principal: UserPrincipal = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve formatted Decision Room message trace timeline for frontend UI."""
    conv = _conv_store.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation_id": conv.conversation_id,
        "task_description": conv.task_description,
        "status": conv.status,
        "consensus_score": conv.consensus_score,
        "timeline": conv.to_decision_room_timeline(),
    }
