"""Nexus v1.0 P0 — Vanessa LLM Pipeline.

Replaces keyword-matching Vanessa with a proper structured pipeline:

    User message
        ↓
    [1] Structured Intent Classification  (LLM)
        ↓
    [2] Permission Check                  (AuthZ against principal)
        ↓ (if denied: stop with permission error)
    [3] Tool Plan                         (LLM + deterministic constraints)
        ↓
    [4] Tool Execution                    (controlled, permission-checked)
        ↓ (evidence gathered, Vanessa never writes DB directly)
    [5] Reasoning synthesis               (LLM)
        ↓
    [6] Structured Response               (citations, actions, trace ID)

CRITICAL INVARIANTS:
    * Vanessa NEVER writes to the database directly.
    * Every tool call is gated by AuthZ against the authenticated principal.
    * The LLM is not granted ANY authority; all authority comes from the
      principal's role + the policy layer.
    * Tool outputs are treated as evidence; LLM interprets evidence but
      cannot fabricate it.
    * If no LLM is configured (e.g. tests, dev), a deterministic rule-based
      adapter is used so the pipeline is always functional.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.modules.nexus_spine.p0_migration.authz import (
    AuthorizationService,
    PermissionDenied,
    Principal,
    get_authz,
)


class IntentType(StrEnum):
    # Read-only intents
    STATE_OVERVIEW = "state_overview"
    FORECAST_QUERY = "forecast_query"
    DECISION_QUERY = "decision_query"
    TRACE_QUERY = "trace_query"
    EXPLAIN = "explain"
    RISK_QUERY = "risk_query"
    # Analyze / simulate (no operational changes)
    RUN_DEMAND = "run_demand"
    SIMULATE = "simulate"
    COMPARE = "compare"
    WHATIF = "whatif"
    RECOMMEND = "recommend"
    # Operational intents (require operator role)
    APPROVE = "approve"
    EXECUTE = "execute"
    RECORD_OUTCOME = "record_outcome"
    RECORD_OBSERVATION = "record_observation"
    # Meta
    HELP = "help"
    GREETING = "greeting"
    UNKNOWN = "unknown"


INTENT_TO_TOOL: dict[IntentType, str] = {
    IntentType.STATE_OVERVIEW: "nexus.cockpit.read",
    IntentType.FORECAST_QUERY: "nexus.forecast.read",
    IntentType.DECISION_QUERY: "nexus.decision.list",
    IntentType.TRACE_QUERY: "nexus.trace.get",
    IntentType.EXPLAIN: "nexus.explain",
    IntentType.RISK_QUERY: "nexus.state.read",
    IntentType.RUN_DEMAND: "nexus.demand.run",
    IntentType.SIMULATE: "nexus.rl.simulate",
    IntentType.COMPARE: "nexus.simulate.compare",
    IntentType.WHATIF: "nexus.whatif.run",
    IntentType.RECOMMEND: "nexus.recommend",
    IntentType.APPROVE: "nexus.decision.approve",
    IntentType.EXECUTE: "nexus.decision.execute",
    IntentType.RECORD_OUTCOME: "nexus.outcome.record",
    IntentType.RECORD_OBSERVATION: "nexus.observation.record",
}


@dataclass
class StructuredIntent:
    intent: IntentType
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    raw_text: str = ""


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    source: str
    data: Any
    tool: str | None = None


@dataclass
class VanessaResponse:
    text: str
    intent: IntentType
    actions_taken: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    permission_denied: str | None = None
    trace_id: str = ""
    world_state_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "response": self.text,
            "intent": self.intent.value,
            "actions_taken": self.actions_taken,
            "evidence": self.evidence,
            "permission_denied": self.permission_denied,
            "trace_id": self.trace_id,
            "world_state_version": self.world_state_version,
        }


# ─────────────────────────────────────────────────────────────────────
# LLM Adapter interface + deterministic fallback
# ─────────────────────────────────────────────────────────────────────


class LLMAdapter:
    """Abstract LLM adapter — swap in OpenAI / Anthropic / local models."""

    async def classify_intent(self, text: str) -> StructuredIntent:
        raise NotImplementedError

    async def plan_tools(
        self, intent: StructuredIntent, allowed_tools: list[str]
    ) -> list[ToolCall]:
        raise NotImplementedError

    async def synthesize(self, intent: StructuredIntent, evidence: list[Evidence]) -> str:
        raise NotImplementedError


class DeterministicLLMAdapter(LLMAdapter):
    """Rule-based intent classifier used when no LLM API is configured.
    This is NOT a keyword "fake Vanessa" — it is the structured-pipeline
    fallback that runs the same tool→AuthZ→evidence chain, just with
    deterministic intent classification instead of an LLM call.
    """

    # Keyword map. Use multi-word phrases for specific intents and single
    # words only when unambiguous. Phrase matching uses substring search;
    # word-boundary matching is applied for short single words like "why"
    # / "how" / "hi" to avoid false positives.
    KEYWORDS: dict[IntentType, list[str]] = {
        IntentType.STATE_OVERVIEW: [
            "state of the world",
            "world state",
            "overview",
            "dashboard",
            "cockpit",
            "summary",
            "status report",
        ],
        IntentType.FORECAST_QUERY: [
            "forecast",
            "predict",
            "p50",
            "p80",
            "p95",
            "demand for",
            "demand of",
        ],
        IntentType.DECISION_QUERY: [
            "decision list",
            "pending decision",
            "list proposal",
            "list approval",
            "what decisions",
        ],
        IntentType.TRACE_QUERY: ["trace", "explain why", "why did", "audit", "history of"],
        IntentType.EXPLAIN: ["explain", "why is", "how does", "tell me about", "what are"],
        IntentType.RISK_QUERY: ["risk", "disruption", "threat", "vulnerability"],
        IntentType.RUN_DEMAND: ["run demand", "run forecast", "compute demand", "demand intel"],
        IntentType.SIMULATE: ["simulate", "digital twin", "run simulation"],
        IntentType.COMPARE: ["compare", "versus", " vs "],
        IntentType.WHATIF: ["what if", "whatif", "scenario"],
        IntentType.RECOMMEND: ["recommend", "suggest", "best option", "what should"],
        IntentType.APPROVE: ["approve", "sign off", "authorize"],
        IntentType.EXECUTE: ["execute", "act on", "proceed with", "implement"],
        IntentType.RECORD_OUTCOME: ["record outcome", "outcome was", "result was"],
        IntentType.RECORD_OBSERVATION: ["observed", "actual was", "actual demand", "actual value"],
        IntentType.HELP: ["help", "what can you do", "capabilities"],
        IntentType.GREETING: ["hi", "hello", "hey", "good morning", "good evening"],
    }

    # Priority: operational actions before read queries before generic explain.
    INTENT_PRIORITY = [
        IntentType.RECORD_OBSERVATION,
        IntentType.RECORD_OUTCOME,
        IntentType.EXECUTE,
        IntentType.APPROVE,
        IntentType.WHATIF,
        IntentType.COMPARE,
        IntentType.SIMULATE,
        IntentType.RUN_DEMAND,
        IntentType.RECOMMEND,
        IntentType.TRACE_QUERY,
        IntentType.RISK_QUERY,
        IntentType.FORECAST_QUERY,
        IntentType.DECISION_QUERY,
        IntentType.STATE_OVERVIEW,
        IntentType.EXPLAIN,
        IntentType.HELP,
        IntentType.GREETING,
    ]

    # Words requiring word-boundary matching (avoid false positives in compound words)
    _BOUNDARY_WORDS = {"hi", "hey", "why", "how"}

    def _count_hits(self, kw: str, text: str) -> int:
        import re

        if kw in self._BOUNDARY_WORDS:
            return 1 if re.search(rf"\b{re.escape(kw)}\b", text) else 0
        return 1 if kw in text else 0

    async def classify_intent(self, text: str) -> StructuredIntent:
        lower = text.lower()
        best = IntentType.UNKNOWN
        best_hits = 0
        for intent in self.INTENT_PRIORITY:
            kws = self.KEYWORDS.get(intent, [])
            hits = sum(self._count_hits(kw, lower) for kw in kws)
            if hits > best_hits:
                best, best_hits = intent, hits
        # Extract simple entities (SKU-like tokens)
        entities: dict[str, Any] = {}
        m = re.search(r"\b(SKU-\d+|sku[_-]?\w+)\b", text, re.IGNORECASE)
        if m:
            entities["sku"] = m.group(1)
        return StructuredIntent(
            intent=best, entities=entities, confidence=0.9 if best_hits > 0 else 0.3, raw_text=text
        )

    async def plan_tools(
        self, intent: StructuredIntent, allowed_tools: list[str]
    ) -> list[ToolCall]:
        tool = INTENT_TO_TOOL.get(intent.intent)
        if tool is None or tool not in allowed_tools:
            return []
        return [ToolCall(tool=tool, args=intent.entities)]

    async def synthesize(self, intent: StructuredIntent, evidence: list[Evidence]) -> str:
        if not evidence:
            if intent.intent == IntentType.HELP:
                return (
                    "I'm Vanessa, Nexus's operating intelligence. I can show you "
                    "world state, forecasts, risks, decisions, and traces; run "
                    "demand intelligence, simulations, and what-if analyses; and "
                    "(for operators) approve and execute decisions. What would you "
                    "like to explore?"
                )
            if intent.intent == IntentType.GREETING:
                return "Hello. I'm Vanessa. How can I help with Nexus operations today?"
            if intent.intent == IntentType.UNKNOWN:
                return "I didn't catch that. Try asking about forecasts, decisions, world state, risks, or type 'help'."
            return f"I understood your request as '{intent.intent.value}' but found no evidence in the current world state."
        parts = []
        for ev in evidence:
            if isinstance(ev.data, dict):
                summary = ev.data.get("summary") or json.dumps(ev.data, default=str)[:300]
            elif isinstance(ev.data, str):
                summary = ev.data[:300]
            else:
                summary = str(ev.data)[:300]
            parts.append(f"[{ev.source}] {summary}")
        return "Based on the current Nexus state:\n\n" + "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────
# Vanessa Pipeline
# ─────────────────────────────────────────────────────────────────────

ToolExecutor = Callable[[ToolCall, Principal], Any]


class VanessaPipeline:
    """Production Vanessa pipeline.

    Usage:
        pipeline = VanessaPipeline(authz=get_authz())
        pipeline.register_tool_executor("nexus.cockpit.read", my_read_fn)
        response = await pipeline.handle(principal, "what is the world state?")
    """

    def __init__(self, authz: AuthorizationService | None = None, llm: LLMAdapter | None = None):
        self.authz = authz or get_authz()
        self.llm = llm or DeterministicLLMAdapter()
        self._executors: dict[str, ToolExecutor] = {}
        self._trace_log: list[dict[str, Any]] = []

    def register_tool_executor(self, tool: str, fn: ToolExecutor) -> None:
        """Register a callable for a tool. The callable MUST NOT write DB
        outside of the proper service layer; Vanessa never writes DB directly."""
        self._executors[tool] = fn

    async def handle(
        self, principal: Principal, message: str, *, workspace_id: str | None = None
    ) -> VanessaResponse:
        trace_id = f"TRC-{uuid4().hex[:10]}"
        ts = datetime.now(UTC).isoformat()

        # Step 1: classify intent
        intent = await self.llm.classify_intent(message)

        # Resolve effective workspace
        effective_ws = workspace_id or principal.workspace_id

        # Step 2+3: plan and check permission.
        # First: determine the tool required by intent, even if it isn't in
        # the allowed set — so we can surface a denial rather than silently
        # returning "no evidence" when an LLM suggests an unauthorized action.
        required_tool = INTENT_TO_TOOL.get(intent.intent)
        allowed = self.authz.list_tools_for(principal)
        plan = await self.llm.plan_tools(intent, allowed)

        denied_reason = None
        # Operational/write intents require the role to actually have the tool
        _WRITE_TOOLS = {
            "nexus.decision.approve",
            "nexus.decision.execute",
            "nexus.decision.create",
            "nexus.outcome.record",
            "nexus.observation.record",
            "nexus.policy.approve",
            "nexus.admin.configure",
            "nexus.admin.roles",
        }
        if (
            required_tool
            and required_tool not in allowed
            and intent.intent not in {IntentType.HELP, IntentType.GREETING, IntentType.UNKNOWN}
            and required_tool in _WRITE_TOOLS
        ):
            denied_reason = (
                f"Role '{principal.role.value}' is not permitted to use "
                f"'{required_tool}'. This action requires a higher-privileged role."
            )

        # Explicit permission check for every tool in the plan (defense in depth)
        for tc in plan:
            try:
                self.authz.check(
                    principal, tc.tool, workspace_id=effective_ws, data_tenant=principal.tenant_id
                )
            except PermissionDenied as e:
                denied_reason = str(e)
                break

        if denied_reason:
            return VanessaResponse(
                text=f"I cannot do that. {denied_reason}",
                intent=intent.intent,
                permission_denied=denied_reason,
                trace_id=trace_id,
            )

        # Step 4: execute tools and gather evidence
        evidence: list[Evidence] = []
        actions: list[str] = []
        for tc in plan:
            fn = self._executors.get(tc.tool)
            if fn is None:
                evidence.append(
                    Evidence(
                        source=f"tool:{tc.tool}",
                        data={"error": "tool not registered"},
                        tool=tc.tool,
                    )
                )
                continue
            try:
                result = fn(tc, principal)
                if hasattr(result, "__await__"):
                    result = await result
                evidence.append(Evidence(source=f"tool:{tc.tool}", data=result, tool=tc.tool))
                actions.append(tc.tool)
            except PermissionDenied as e:
                return VanessaResponse(
                    text=f"Permission denied during execution: {e}",
                    intent=intent.intent,
                    permission_denied=str(e),
                    trace_id=trace_id,
                )
            except Exception as e:
                evidence.append(
                    Evidence(source=f"tool:{tc.tool}", data={"error": str(e)}, tool=tc.tool)
                )

        # Step 5+6: synthesize response
        text = await self.llm.synthesize(intent, evidence)

        # Log trace (append-only, in-memory; in production this goes to PG outbox)
        self._trace_log.append(
            {
                "trace_id": trace_id,
                "timestamp": ts,
                "user_id": principal.user_id,
                "workspace_id": effective_ws,
                "message": message,
                "intent": intent.intent.value,
                "tools_called": actions,
                "denied": denied_reason,
            }
        )

        return VanessaResponse(
            text=text,
            intent=intent.intent,
            actions_taken=actions,
            evidence=[
                {"source": e.source, "tool": e.tool, "data_excerpt": _excerpt(e.data)}
                for e in evidence
            ],
            trace_id=trace_id,
        )


def _excerpt(data: Any, n: int = 500) -> Any:
    try:
        s = json.dumps(data, default=str)
        if len(s) > n:
            return s[:n] + "...(truncated)"
        return data
    except Exception:
        return str(data)[:n]


_singleton: VanessaPipeline | None = None


def get_vanessa_pipeline() -> VanessaPipeline:
    global _singleton
    if _singleton is None:
        _singleton = VanessaPipeline()
    return _singleton
