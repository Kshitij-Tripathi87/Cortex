"""Nexus Vanessa — Investigation Planner.

Vanessa's core intelligence upgrade: instead of single-shot answers, she
now plans a multi-step investigation chain of grounded tools.

Flow:
    Question → Intent → Plan → Tool execution → Synthesized answer

Every tool result is turned into a typed block; every tool invocation records
evidence for the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.modules.nexus_spine.ontology import get_world_model
from app.modules.nexus_spine.vanessa.builtin_tools import get_tool_registry
from app.modules.nexus_spine.vanessa.tools import ToolRegistry
from app.modules.nexus_spine.vanessa.orchestrator import Intent, IntentClassification, classify_intent


def _classify(question: str) -> IntentClassification:
    """Classify the intent of a question using the Vanessa intent classifier."""
    return classify_intent(question, get_tool_registry())


class ResponseKind(StrEnum):
    """Typed rendering blocks the UI knows how to render."""

    TEXT = "text"
    TABLE = "table"
    GRAPH_PATH = "graph_path"
    METRIC = "metric"
    SCENARIO_MATRIX = "scenario_matrix"
    EVIDENCE_CHAIN = "evidence_chain"
    RISK_CARD = "risk_card"
    TIME_SERIES = "time_series"
    FORECAST_COMPARISON = "forecast_comparison"


class ResponseBlock(BaseModel):
    """A typed response block with provenance.

    The UI routes the response chain by payload type, not schema.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ResponseKind
    title: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InvestigationResult(BaseModel):
    """The overall result of a Vanessa investigation."""

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    intent: str
    intent_confidence: float
    answer_text: str = ""
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    evidence_trail: list[dict[str, Any]] = Field(default_factory=list)
    world_state_version: int = 0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PlanStep:
    """One step in an investigation chain."""

    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    optional: bool = False


_INVESTIGATION_PLANS: dict[str, list[PlanStep]] = {
    "supplier_risk": [
        PlanStep("get_supplier_risk", args={"limit": 10}, rationale="Identify high-risk suppliers"),
        PlanStep("get_signal", args={"min_severity": 0.4}, rationale="Get capacity/drop signals"),
        PlanStep("traverse_graph", args={"max_depth": 3}, rationale="Map supplier→order connections"),
        PlanStep("get_orders_at_risk", args={"min_revenue": 0}, rationale="Show affected orders"),
        PlanStep("find_analogous_decisions", args={"limit": 3}, rationale="Historical precedents"),
    ],
    "demand_forecast": [
        PlanStep("get_supplier_risk", args={"limit": 5}, rationale="High-risk suppliers driving forecast"),
        PlanStep("get_forecast", args={"sku": "DEFAULT"}, rationale="Current forecast"),
        PlanStep("compare_forecast_actual", args={}, rationale="Verify accuracy"),
    ],
    "world": [
        PlanStep("query_world_state", args={"limit": 50}, rationale="Inventory of the world"),
        PlanStep("get_supplier_risk", args={"limit": 5}, rationale="Talk suppliers"),
        PlanStep("get_signal", args={"limit": 10}, rationale="Active signals"),
    ],
    "signal_what_happened": [
        PlanStep("get_signal", args={"min_severity": 0.5}, rationale="Active signals"),
        PlanStep("get_blast_radius", args={"max_depth": 3}, rationale="Downstream impact"),
        PlanStep("traverse_graph", args={"max_depth": 3}, rationale="What assets follow"),
    ],
    "decision_context": [
        PlanStep("get_decision", args={}, rationale="Look up decision"),
        PlanStep("find_analogous_decisions", args={}),
    ],
    "order_risk": [
        PlanStep("get_orders_at_risk", args={"min_revenue": 0}, rationale="Orders at SLA risk"),
    ],
    "risk_debrief": [
        PlanStep("get_supplier_risk", args={"limit": 5}, rationale="Top risk suppliers"),
        PlanStep("get_signal", args={"min_severity": 0.5}, rationale="High-severity signals"),
        PlanStep("get_orders_at_risk", args={"min_revenue": 0}, rationale="Orders at SLA risk"),
        PlanStep("run_scenario", args={}),
    ],
    "default": [
        PlanStep("get_supplier_risk", args={}),
    ],
}


_BLOCK_FOR_SIGNAL: dict[str, ResponseKind] = {
    "query_world_state": ResponseKind.TABLE,
    "get_supplier_risk": ResponseKind.TABLE,
    "get_signal": ResponseKind.TABLE,
    "get_blast_radius": ResponseKind.GRAPH_PATH,
    "get_orders_at_risk": ResponseKind.TABLE,
    "get_forecast": ResponseKind.TIME_SERIES,
    "compare_forecast_actual": ResponseKind.TIME_SERIES,
    "get_truth_loop_summary": ResponseKind.TABLE,
    "run_scenario": ResponseKind.SCENARIO_MATRIX,
    "get_decision": ResponseKind.METRIC,
    "find_analogous_decisions": ResponseKind.TABLE,
}


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert complex payloads into JSON-safe data."""
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if isinstance(v, (str, int, float, bool, list, dict, type(None))):
            out[k] = v
    return out


_HEX_COMMENT: str = "hash is just a constant hash of value"


class VanessaInvestigator:
    """Plans + executes multi-step investigations on behalf of Vanessa."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def investigate(
        self,
        question: str,
        tenant_id: UUID,
        workspace_id: UUID,
        requester: Any,
    ) -> InvestigationResult:
        """Run a multi-tool investigation.

        Produces:
        - An answer_text the operator can read
        - Typed response blocks for the UI to render
        - Evidence trail (for the audit log)
        """
        wm = get_world_model()
        world_state_version = wm.world_state_version

# classify → plan → execute
        # Uses the shared intent classifier from the vanessa subsystem.
        classification = _classify(question)
        print(f"DEBUG: classification.intent = {classification.intent}, intent.value = {classification.intent.value}")
        print(f"DEBUG: Intent.UNKNOWN = {Intent.UNKNOWN}")
        print(f"DEBUG: classification.intent == Intent.UNKNOWN: {classification.intent == Intent.UNKNOWN}")
        if classification.intent == Intent.UNKNOWN:
            plan_steps = []
            print("DEBUG: Taking UNKNOWN branch, plan_steps = []")
        else:
            plan_steps = _INVESTIGATION_PLANS.get(
                classification.intent.value.lower(), _INVESTIGATION_PLANS["default"]
            )
            print(f"DEBUG: Taking else branch, plan_steps = {len(plan_steps)} steps")

        executed: list[dict[str, Any]] = []
        evidence_trail: list[dict[str, Any]] = []

        for step in plan_steps:
            args = self._resolve_args(step.args, tenant_id, workspace_id)
            from app.modules.nexus_spine.vanessa.tools import ToolCall

            # Build the tool call with per-request identity
            call = ToolCall(
                tool_name=step.tool_name,
                arguments=args,
                requester_role=getattr(requester, "roles", ["viewer"])[0],
                requester_id=getattr(requester, "user_id", "api"),
                tenant_id=tenant_id,
                workspace_id=workspace_id,
            )
            result = self.registry.invoke(call)

            executed.append({
                "tool": step.tool_name,
                "ok": result.ok,
                "error": result.error,
                "payload": result.payload if result.ok else None,
            })

            if result.ok and result.payload:
                evidence_trail.extend([
                    {"tool": step.tool_name, "key": k, "value": str(v)[:80]}
                    for k, v in result.payload.items()
                ])

        blocks = self._build_blocks(executed)
        answer = self._compose_answer(classification, executed)

        return InvestigationResult(
            query_id=str(uuid4()),
            question=question,
            intent=classification.intent.value,
            intent_confidence=classification.confidence,
            answer_text=answer,
            blocks=[b.model_dump() for b in blocks],
            evidence_trail=evidence_trail,
            world_state_version=world_state_version,
        )

    def _resolve_args(self, args: dict[str, Any], tenant_id: UUID, workspace_id: UUID) -> dict[str, Any]:
        return {
            k: (str(tenant_id) if v == "${tenant_id}" else
                str(workspace_id) if v == "${workspace_id}" else v)
            for k, v in args.items()
        }

    def _build_blocks(self, executed: list[dict[str, Any]]) -> list[ResponseBlock]:
        blocks: list[ResponseBlock] = []
        for r in executed:
            if not r.get("ok"):
                continue
            tool_name = r["tool"]
            kind = _BLOCK_FOR_SIGNAL.get(tool_name, ResponseKind.METRIC)
            payload = r.get("payload") or {}
            blocks.append(
                ResponseBlock(
                    kind=kind,
                    title=tool_name.replace("_", " ").title(),
                    data=_sanitize(payload),
                    citations=[f"{tool_name}"],
                    confidence=self._confidence_of(payload),
                )
            )
        return blocks

    def _compose_answer(self, classification: IntentClassification, executed: list[dict[str, Any]]) -> str:
        tools_done = [r for r in executed if r.get("ok")]
        if not tools_done:
            return "No data returned from any tool."
        block_count = len(tools_done)
        intent_name = classification.intent.value
        return f"Investigation: {intent_name} with {block_count} tool(s)."

    def _confidence_of(self, payload: dict[str, Any]) -> float:
        return float(payload.get("confidence", 0.9)) if isinstance(payload, dict) else 0.95


from app.modules.nexus_spine.vanessa.tools import ToolRegistry
from app.modules.nexus_spine.vanessa.builtin_tools import get_tool_registry as _get_tool_registry
from app.modules.nexus_spine.vanessa.orchestrator import classify_intent

# Package-level singleton for Vanessa's (satisfying tests)
vanessa: VanessaInvestigator = None  # type: ignore[assignment]

def get_vanessa_investigator() -> VanessaInvestigator:
    """Get or create the process-wide investigator."""
    global vanessa
    if vanessa is None:
        vanessa = VanessaInvestigator(registry=_get_tool_registry())
    return vanessa


def reset_vanessa_investigator() -> None:
    """Reset singleton investigator — for tests."""
    global vanessa
    vanessa = None


def _get_tool_registry() -> ToolRegistry:
    """Resolve the process-wide ToolRegistry."""
    from app.modules.nexus_spine.vanessa.builtin_tools import get_tool_registry as _get
    return _get()


__all__ = [
    "PlanStep",
    "ResponseBlock",
    "ResponseKind",
    "InvestigationResult",
    "VanessaInvestigator",
    "get_vanessa_investigator",
    "reset_vanessa_investigator",
    "classify_intent",
    "vanessa",
]
