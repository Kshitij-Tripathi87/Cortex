"""Agent Conversation Store — Persistent Storage and Inspectability for Multi-Agent Runs.

Provides:
- Durable storage of multi-agent conversations (deliberations, proposals, critiques, consensus)
- Inspectability for audit, debugging, evaluation, and human explainability
- Decision Room timeline generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.multi_agent.runtime.message_envelope import AgentMessageEnvelope


@dataclass
class ConversationRecord:
    """Complete audit record of a multi-agent deliberation session."""

    conversation_id: str
    tenant_id: str
    organization_id: str
    workspace_id: str
    task_id: str
    task_description: str
    status: str
    consensus_score: float
    started_at: datetime
    completed_at: datetime | None
    messages: list[AgentMessageEnvelope] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    critiques: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    participating_agents: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "task_description": self.task_description,
            "status": self.status,
            "consensus_score": round(self.consensus_score, 4),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "message_count": len(self.messages),
            "messages": [m.to_dict() for m in self.messages],
            "proposals": self.proposals,
            "critiques": self.critiques,
            "synthesis": self.synthesis,
            "participating_agents": self.participating_agents,
            "total_cost_usd": round(self.total_cost_usd, 2),
            "errors": self.errors,
        }

    def to_decision_room_timeline(self) -> list[dict[str, Any]]:
        """Generate human-readable timeline for the Decision Room UI."""
        timeline: list[dict[str, Any]] = []
        for msg in self.messages:
            timeline.append({
                "timestamp": msg.occurred_at.strftime("%H:%M:%S"),
                "agent": msg.agent_id.upper(),
                "type": msg.message_type.value,
                "summary": self._extract_summary(msg),
                "payload": msg.payload,
            })
        return timeline

    def _extract_summary(self, msg: AgentMessageEnvelope) -> str:
        p = msg.payload
        if "description" in p:
            return str(p["description"])
        if "domain_rationale" in p:
            return str(p["domain_rationale"])
        if "critique_rationale" in p:
            return str(p["critique_rationale"])
        if "coordination_summary" in p:
            return str(p["coordination_summary"])
        return f"{msg.message_type.value} from {msg.agent_id}"


class ConversationStore:
    """In-memory and durable repository for agent conversations."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationRecord] = {}

    def save(self, record: ConversationRecord) -> None:
        """Save or update a conversation record."""
        self._conversations[record.conversation_id] = record

    def get(self, conversation_id: str) -> ConversationRecord | None:
        """Retrieve conversation by ID."""
        return self._conversations.get(conversation_id)

    def list_by_workspace(
        self, workspace_id: str, limit: int = 50
    ) -> list[ConversationRecord]:
        """List conversations for a given workspace ordered by start time descending."""
        records = [
            c for c in self._conversations.values() if c.workspace_id == workspace_id
        ]
        records.sort(key=lambda x: x.started_at, reverse=True)
        return records[:limit]

    def list_by_tenant(
        self, tenant_id: str, limit: int = 50
    ) -> list[ConversationRecord]:
        """List conversations for a given tenant ordered by start time descending."""
        records = [
            c for c in self._conversations.values() if c.tenant_id == tenant_id
        ]
        records.sort(key=lambda x: x.started_at, reverse=True)
        return records[:limit]


# Global singleton
_global_conv_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _global_conv_store
    if _global_conv_store is None:
        _global_conv_store = ConversationStore()
    return _global_conv_store
