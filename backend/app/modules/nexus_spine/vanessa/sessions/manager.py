"""Vanessa Session Manager — production-grade contextual conversations (items 7, 8)."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.modules.nexus_spine.explanations import ResponseBlockType
from app.modules.nexus_spine.vanessa.orchestrator import (
    Intent,
    VanessaAnswer,
    VanessaOrchestrator,
    VanessaQuery,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ConversationContext:
    """Operational context bound to a Vanessa session."""

    tenant_id: str
    workspace_id: str
    user_id: str
    user_role: str = "operator"
    permissions: list[str] = field(default_factory=lambda: ["read", "simulate", "ask"])

    current_world_state_version: int | None = None
    active_trace_id: str | None = None
    selected_entity_id: str | None = None
    selected_entity_kind: str | None = None
    selected_entity_name: str | None = None
    selected_risk_id: str | None = None
    selected_decision_id: str | None = None
    selected_scenario_id: str | None = None
    selected_sku: str | None = None

    # Resolved anaphora ("it", "that", "that supplier", etc.)
    last_referenced_entity_id: str | None = None
    last_topic: str | None = None

    # Context bag for arbitrary state
    context_bag: dict[str, Any] = field(default_factory=dict)

    def clone(self) -> ConversationContext:
        return ConversationContext(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            user_id=self.user_id,
            user_role=self.user_role,
            permissions=list(self.permissions),
            current_world_state_version=self.current_world_state_version,
            active_trace_id=self.active_trace_id,
            selected_entity_id=self.selected_entity_id,
            selected_entity_kind=self.selected_entity_kind,
            selected_entity_name=self.selected_entity_name,
            selected_risk_id=self.selected_risk_id,
            selected_decision_id=self.selected_decision_id,
            selected_scenario_id=self.selected_scenario_id,
            selected_sku=self.selected_sku,
            last_referenced_entity_id=self.last_referenced_entity_id,
            last_topic=self.last_topic,
            context_bag=dict(self.context_bag),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "user_role": self.user_role,
            "permissions": list(self.permissions),
            "current_world_state_version": self.current_world_state_version,
            "active_trace_id": self.active_trace_id,
            "selected_entity_id": self.selected_entity_id,
            "selected_entity_kind": self.selected_entity_kind,
            "selected_entity_name": self.selected_entity_name,
            "selected_risk_id": self.selected_risk_id,
            "selected_decision_id": self.selected_decision_id,
            "selected_scenario_id": self.selected_scenario_id,
            "selected_sku": self.selected_sku,
            "last_referenced_entity_id": self.last_referenced_entity_id,
            "last_topic": self.last_topic,
        }


@dataclass
class SessionMessage:
    role: str  # user|assistant|system|tool
    content: str
    intent: str | None = None
    confidence: float | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    response_blocks: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "intent": self.intent,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
            "tool_calls": self.tool_calls,
            "response_blocks": self.response_blocks,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SessionResponse:
    """Full session response with multimodal blocks and updated context."""

    session_id: str
    answer: str
    intent: str
    confidence: float
    response_blocks: list[dict[str, Any]]
    citations: list[str]
    tool_results: list[dict[str, Any]]
    context: dict[str, Any]
    suggestions: list[str]
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "answer": self.answer,
            "intent": self.intent,
            "confidence": round(self.confidence, 4),
            "response_blocks": self.response_blocks,
            "citations": self.citations,
            "tool_results": self.tool_results,
            "context": self.context,
            "suggestions": self.suggestions,
            "timestamp": self.timestamp.isoformat(),
        }


class VanessaSessionManager:
    """Manages per-user per-workspace contextual Vanessa conversations."""

    # Anaphoric references that resolve to the last selected entity
    ANAPHORA = {
        "it",
        "that",
        "this",
        "they",
        "them",
        "the supplier",
        "that supplier",
        "this supplier",
        "the order",
        "that order",
        "the risk",
        "that risk",
        "the decision",
        "that decision",
        "the scenario",
        "that scenario",
        "the forecast",
        "that forecast",
    }

    # Follow-up intents suggested based on current context
    CONTEXTUAL_SUGGESTIONS: dict[str, list[str]] = {
        "supplier": [
            "What happens if we lose it?",
            "Compare that with the alternate supplier",
            "Show me the hidden dependencies",
            "What did we do last time?",
        ],
        "forecast": [
            "Why did we underforecast?",
            "Show me forecast vs reality",
            "Is there drift?",
            "Which SKUs are wrong?",
        ],
        "decision": [
            "Show me the evidence",
            "What alternatives were considered?",
            "What did we decide last time?",
        ],
        "scenario": [
            "Compare scenarios",
            "What's the net economic value?",
            "What's the SLA impact?",
        ],
        "risk": [
            "Why is it risky?",
            "What happens if it fails?",
            "What can we do?",
            "Show me the evidence",
        ],
        "default": [
            "What's happening in the world?",
            "Which suppliers are at risk?",
            "Show me active signals",
            "Run a scenario",
        ],
    }

    def __init__(self, orchestrator: VanessaOrchestrator | None = None) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._orchestrator = orchestrator

    def _get_orchestrator(self) -> VanessaOrchestrator:
        if self._orchestrator is not None:
            return self._orchestrator
        from app.modules.nexus_spine.vanessa.orchestrator import get_vanessa

        return get_vanessa()

    def get_or_create_session(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
        user_role: str = "operator",
    ) -> tuple[str, ConversationContext]:
        with self._lock:
            # Find existing session for this user+workspace
            for sid, sess in self._sessions.items():
                ctx: ConversationContext = sess["context"]
                if (
                    ctx.tenant_id == tenant_id
                    and ctx.workspace_id == workspace_id
                    and ctx.user_id == user_id
                ):
                    return sid, ctx.clone()
            # Create new session
            session_id = f"VSESS-{uuid4().hex[:10]}"
            ctx = ConversationContext(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                user_role=user_role,
            )
            self._sessions[session_id] = {
                "session_id": session_id,
                "context": ctx,
                "messages": [],
                "created_at": _utc_now(),
                "last_active": _utc_now(),
            }
            return session_id, ctx.clone()

    def get_context(self, session_id: str) -> ConversationContext | None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None
            return sess["context"].clone()

    def update_context(self, session_id: str, **kwargs: Any) -> ConversationContext | None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None
            ctx: ConversationContext = sess["context"]
            for key, val in kwargs.items():
                if hasattr(ctx, key):
                    setattr(ctx, key, val)
            sess["last_active"] = _utc_now()
            return ctx.clone()

    def ask(
        self,
        session_id: str,
        query_text: str,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> SessionResponse:
        """Ask Vanessa within a session — resolves anaphora, updates context, returns multimodal response."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                raise ValueError(f"Session {session_id} not found")
            ctx: ConversationContext = sess["context"]
            orchestrator = self._get_orchestrator()

            # Resolve anaphora in the query
            resolved_query, resolved_args = self._resolve_anaphora(query_text, ctx, arguments or {})

            # Build the Vanessa query
            try:
                t_uuid = UUID(ctx.tenant_id)
                w_uuid = UUID(ctx.workspace_id)
            except ValueError:
                t_uuid = uuid4()
                w_uuid = uuid4()

            query = VanessaQuery(
                query=resolved_query,
                requester_id=ctx.user_id,
                requester_role=ctx.user_role,
                tenant_id=t_uuid,
                workspace_id=w_uuid,
                arguments=resolved_args,
            )

            # Run orchestration
            answer = orchestrator.ask(query)

            # Build multimodal response blocks
            blocks = self._build_response_blocks(answer, ctx)

            # Update context based on intent + entities referenced
            updated_ctx = self._update_context_from_answer(ctx, answer, resolved_args)
            sess["context"] = updated_ctx

            # Record messages
            user_msg = SessionMessage(role="user", content=query_text)
            asst_msg = SessionMessage(
                role="assistant",
                content=answer.rendered_answer,
                intent=answer.intent.value,
                confidence=answer.intent_confidence,
                tool_calls=[t.to_dict() for t in answer.tool_calls],
                response_blocks=blocks,
            )
            sess["messages"].append(user_msg)
            sess["messages"].append(asst_msg)
            sess["last_active"] = _utc_now()

            # Generate contextual suggestions
            suggestions = self._suggest_next(updated_ctx, answer.intent)

            return SessionResponse(
                session_id=session_id,
                answer=answer.rendered_answer,
                intent=answer.intent.value,
                confidence=answer.intent_confidence,
                response_blocks=blocks,
                citations=list(answer.citations),
                tool_results=[t.to_dict() for t in answer.tool_calls],
                context=updated_ctx.to_dict(),
                suggestions=suggestions,
            )

    def _resolve_anaphora(
        self,
        query: str,
        ctx: ConversationContext,
        args: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Resolve pronouns and anaphoric references using session context."""
        resolved_args = dict(args)
        resolved_query = query
        query_lower = query.lower().strip()

        # Check for anaphora referring to a selected entity
        has_anaphora = any(ana in query_lower for ana in self.ANAPHORA) or query_lower in {
            "why?",
            "what happens?",
            "compare",
            "why is it risky?",
        }

        if has_anaphora:
            # If query mentions risk/supplier/etc. and we have a selected entity, inject it
            if ctx.selected_entity_id:
                if "seed_entity_id" not in resolved_args:
                    resolved_args["seed_entity_id"] = ctx.selected_entity_id
                if "entity_id" not in resolved_args:
                    resolved_args["entity_id"] = ctx.selected_entity_id
                # Append context hint
                resolved_query = (
                    f"{query} (referring to {ctx.selected_entity_name or ctx.selected_entity_id})"
                )
                ctx.last_referenced_entity_id = ctx.selected_entity_id
                ctx.last_topic = ctx.selected_entity_kind

            # If query mentions forecast and we have a selected SKU
            if (
                ("forecast" in query_lower or "demand" in query_lower)
                and ctx.selected_sku
                and "sku" not in resolved_args
            ):
                resolved_args["sku"] = ctx.selected_sku

            # If query mentions decision and we have a selected decision
            if "decision" in query_lower and ctx.selected_decision_id:
                resolved_args["decision_id"] = ctx.selected_decision_id

            # If query asks "what happens if we lose it" → scenario
            if "lose" in query_lower or "fail" in query_lower or "what happens" in query_lower:
                ctx.last_topic = "scenario"

        # Detect direct entity references
        sku_match = re.search(r"\b(?:SKU[-_]?|sku[-_]?)([A-Za-z0-9][A-Za-z0-9\-_]*)", query)
        if sku_match:
            ctx.selected_sku = f"SKU-{sku_match.group(1)}"
            resolved_args["sku"] = ctx.selected_sku
            ctx.last_topic = "forecast"

        return resolved_query, resolved_args

    def _build_response_blocks(
        self,
        answer: VanessaAnswer,
        ctx: ConversationContext,
    ) -> list[dict[str, Any]]:
        """Build multimodal response blocks from tool results (item 8)."""
        blocks: list[dict[str, Any]] = []
        primary_payload: dict[str, Any] = {}
        for tr in answer.tool_calls:
            if tr.ok and tr.payload:
                primary_payload = tr.payload
                break

        # Text block (always present)
        blocks.append(
            {
                "type": ResponseBlockType.TEXT.value,
                "title": "",
                "content": answer.rendered_answer,
            }
        )

        # Metric / card blocks based on intent
        if answer.intent == Intent.SUPPLIER_RISK:
            suppliers = primary_payload.get("suppliers", [])
            for s in suppliers[:3]:
                blocks.append(
                    {
                        "type": ResponseBlockType.RISK_CARD.value,
                        "title": s.get("name", "Supplier"),
                        "metrics": {
                            "risk_score": s.get("risk_score"),
                            "capacity_pct": s.get("capacity_pct"),
                            "on_time_rate": s.get("on_time_rate"),
                        },
                        "data": s,
                    }
                )
        elif answer.intent == Intent.DEMAND_FORECAST:
            blocks.append(
                {
                    "type": ResponseBlockType.METRIC.value,
                    "title": f"Forecast: {primary_payload.get('sku', 'SKU')}",
                    "metrics": {
                        "p50": primary_payload.get("p50"),
                        "p80": primary_payload.get("p80"),
                        "p95": primary_payload.get("p95"),
                        "confidence": primary_payload.get("confidence"),
                        "wape": primary_payload.get("backtest_wape"),
                    },
                }
            )
        elif answer.intent == Intent.BLAST_RADIUS:
            blocks.append(
                {
                    "type": ResponseBlockType.GRAPH.value,
                    "title": f"Blast radius from {primary_payload.get('seed_name', '')}",
                    "data": primary_payload,
                }
            )
        elif answer.intent == Intent.ANALOGOUS_DECISIONS:
            analogues = primary_payload.get("analogous_decisions", [])
            if analogues:
                blocks.append(
                    {
                        "type": ResponseBlockType.TIMELINE.value,
                        "title": "Analogous decisions",
                        "data": {"items": analogues},
                    }
                )

        return blocks

    def _update_context_from_answer(
        self,
        ctx: ConversationContext,
        answer: VanessaAnswer,
        args: dict[str, Any],
    ) -> ConversationContext:
        """Update the conversation context based on the answer and detected entities."""
        new_ctx = ctx.clone()

        # Extract entity from args
        if "seed_entity_id" in args:
            new_ctx.selected_entity_id = args["seed_entity_id"]
            new_ctx.last_referenced_entity_id = args["seed_entity_id"]
        if "entity_id" in args:
            new_ctx.selected_entity_id = args["entity_id"]
            new_ctx.last_referenced_entity_id = args["entity_id"]
        if "sku" in args:
            new_ctx.selected_sku = args["sku"]

        # Update topic from intent
        topic_map = {
            Intent.SUPPLIER_RISK: "supplier",
            Intent.DEMAND_FORECAST: "forecast",
            Intent.FORECAST_CALIBRATION: "forecast",
            Intent.BLAST_RADIUS: "risk",
            Intent.SIGNAL_TRIAGE: "risk",
            Intent.ORDER_RISK: "risk",
            Intent.DECISION_LOOKUP: "decision",
            Intent.ANALOGOUS_DECISIONS: "decision",
        }
        new_ctx.last_topic = topic_map.get(answer.intent, new_ctx.last_topic)
        return new_ctx

    def _suggest_next(self, ctx: ConversationContext, last_intent: Intent) -> list[str]:
        """Suggest next actions based on context."""
        topic = ctx.last_topic or "default"
        suggestions = self.CONTEXTUAL_SUGGESTIONS.get(topic, self.CONTEXTUAL_SUGGESTIONS["default"])
        return suggestions[:4]

    def get_history(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return []
            msgs: list[SessionMessage] = sess["messages"]
            return [m.to_dict() for m in msgs[-limit:]]

    def list_sessions(
        self, tenant_id: str, workspace_id: str, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for sid, sess in self._sessions.items():
                ctx: ConversationContext = sess["context"]
                if ctx.tenant_id != tenant_id or ctx.workspace_id != workspace_id:
                    continue
                if user_id and ctx.user_id != user_id:
                    continue
                results.append(
                    {
                        "session_id": sid,
                        "context": ctx.to_dict(),
                        "message_count": len(sess["messages"]),
                        "created_at": sess["created_at"].isoformat(),
                        "last_active": sess["last_active"].isoformat(),
                    }
                )
            return results


_singleton: VanessaSessionManager | None = None


def get_vanessa_session_manager() -> VanessaSessionManager:
    global _singleton
    if _singleton is None:
        _singleton = VanessaSessionManager()
    return _singleton


def reset_vanessa_session_manager() -> None:
    global _singleton
    _singleton = None
