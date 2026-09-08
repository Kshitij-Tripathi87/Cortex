"""Nexus Vanessa — Grounded Reasoning Orchestrator.

Vanessa's reasoning engine:
1. Intent classification — match user question to candidate tools
2. Permission check — confirm the requester's role can invoke those tools
3. Tool execution — invoke each tool deterministically
4. Evidence aggregation — collect every tool's structured output + citations
5. Natural-language rendering — produce a human-readable answer that cites
   the exact tools and numbers it used

The LLM, if present, only renders the final answer (step 5). All fact-
production happens in deterministic tools (steps 1-4) against the live
world model / demand engine / decision memory.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.modules.nexus_spine.vanessa.builtin_tools import (
    get_tool_registry,
)
from app.modules.nexus_spine.vanessa.tools import (
    ToolCall,
    ToolRegistry,
    ToolResult,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Intent(StrEnum):
    """Recognized user intents. The classifier maps natural-language to one."""

    WORLD_OVERVIEW = "world_overview"
    SUPPLIER_RISK = "supplier_risk"
    DEMAND_FORECAST = "demand_forecast"
    FORECAST_CALIBRATION = "forecast_calibration"
    BLAST_RADIUS = "blast_radius"
    SIGNAL_TRIAGE = "signal_triage"
    ORDER_RISK = "order_risk"
    DECISION_LOOKUP = "decision_lookup"
    ANALOGOUS_DECISIONS = "analogous_decisions"
    UNKNOWN = "unknown"


_INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.SUPPLIER_RISK: ["supplier", "risk", "vendor", "score", "capacity"],
    Intent.DEMAND_FORECAST: ["forecast", "demand", "expected", "predict"],
    Intent.FORECAST_CALIBRATION: [
        "accuracy",
        "calibration",
        "bias",
        "wrong",
        "actual vs forecast",
        "drift",
    ],
    Intent.BLAST_RADIUS: ["blast radius", "blast", "impact", "downstream", "affected", "ripple"],
    Intent.SIGNAL_TRIAGE: ["signal", "alert", "attention", "anomaly", "warning"],
    Intent.ORDER_RISK: ["order", "sla", "miss", "delivery", "late", "breach"],
    Intent.DECISION_LOOKUP: ["decision", "approved", "rejected", "what did we decide"],
    Intent.ANALOGOUS_DECISIONS: [
        "similar",
        "analogous",
        "before",
        "history",
        "past decision",
        "remember",
    ],
    Intent.WORLD_OVERVIEW: ["world", "summary", "state", "overview", "status"],
}


@dataclass(frozen=True)
class IntentClassification:
    intent: Intent
    confidence: float
    matched_tools: list[str]


def classify_intent(text: str, registry: ToolRegistry) -> IntentClassification:
    """Match the user's text to an intent using simple keyword scoring.

    Returns the highest-scoring intent with its confidence in [0, 1].
    Unknown intent is returned when no keywords match.
    """
    text_lower = text.lower()
    scored: list[tuple[Intent, float, list[str]]] = []
    for intent, keywords in _INTENT_KEYWORDS.items():
        matches = [kw for kw in keywords if kw in text_lower]
        if not matches:
            continue
        # Normalize by the number of intent keywords (so dense keyword sets
        # don't artificially inflate scores).
        score = len(matches) / len(keywords)
        tool_for_intent = _tool_for_intent(intent)
        scored.append((intent, score, tool_for_intent))

    if not scored:
        return IntentClassification(intent=Intent.UNKNOWN, confidence=0.0, matched_tools=[])

    scored.sort(key=lambda x: x[1], reverse=True)
    best_intent, best_score, tools = scored[0]
    return IntentClassification(
        intent=best_intent,
        confidence=min(best_score * 2.0, 1.0),  # rescale to [0, 1]
        matched_tools=tools,
    )


def _tool_for_intent(intent: Intent) -> list[str]:
    """Map an intent to the canonical Vanessa tools that satisfy it."""
    return {
        Intent.WORLD_OVERVIEW: ["query_world_state"],
        Intent.SUPPLIER_RISK: ["get_supplier_risk"],
        Intent.DEMAND_FORECAST: ["get_forecast"],
        Intent.FORECAST_CALIBRATION: ["compare_forecast_actual"],
        Intent.BLAST_RADIUS: ["get_blast_radius"],
        Intent.SIGNAL_TRIAGE: ["get_signal"],
        Intent.ORDER_RISK: ["get_orders_at_risk"],
        Intent.DECISION_LOOKUP: ["get_decision"],
        Intent.ANALOGOUS_DECISIONS: ["find_analogous_decisions"],
        Intent.UNKNOWN: [],
    }[intent]


# ──────────────────────────────────────────────────────────────────────────────
# Vanessa Query / Response
# ──────────────────────────────────────────────────────────────────────────────


class VanessaQuery(BaseModel):
    """A Vanessa query from a user."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    requester_id: str
    requester_role: str = "viewer"
    tenant_id: UUID
    workspace_id: UUID
    arguments: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class VanessaAnswer:
    """The grounded response Vanessa produces.

    Carries: the original intent, the tools invoked, their results, the
    citations, and a human-readable rendered answer. Everything is in one
    object so callers (UI, API) can show the entire reasoning chain.
    """

    query_id: UUID
    intent: Intent
    intent_confidence: float
    tool_calls: list[ToolResult]
    rendered_answer: str
    citations: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": str(self.query_id),
            "intent": self.intent.value,
            "intent_confidence": round(self.intent_confidence, 4),
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "rendered_answer": self.rendered_answer,
            "citations": list(self.citations),
            "timestamp": self.timestamp.isoformat(),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────────


class VanessaOrchestrator:
    """Routes a query through intent → permission → tools → answer."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or get_tool_registry()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def ask(self, query: VanessaQuery) -> VanessaAnswer:
        """Run a Vanessa query end-to-end and return a grounded answer."""
        classification = classify_intent(query.query, self._registry)
        tool_results: list[ToolResult] = []
        citations: list[str] = []

        for tool_name in classification.matched_tools:
            arguments = self._build_arguments(tool_name, query)
            call = ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                requester_role=query.requester_role,
                requester_id=query.requester_id,
                tenant_id=query.tenant_id,
                workspace_id=query.workspace_id,
            )
            result = self._registry.invoke(call)
            tool_results.append(result)
            citations.extend(result.evidence)

        rendered = render_answer(query.query, classification, tool_results)
        return VanessaAnswer(
            query_id=uuid4(),
            intent=classification.intent,
            intent_confidence=classification.confidence,
            tool_calls=tool_results,
            rendered_answer=rendered,
            citations=citations,
        )

    def _build_arguments(
        self,
        tool_name: str,
        query: VanessaQuery,
    ) -> dict[str, Any]:
        """Build tool arguments from the query and any provided hints."""
        args = dict(query.arguments)
        # If the user didn't specify a target but the tool needs one, try
        # to extract an entity_id or sku from the query text.
        if tool_name == "get_blast_radius" and "seed_entity_id" not in args:
            m = re.search(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", query.query
            )
            if m:
                args["seed_entity_id"] = m.group(0)
        if tool_name == "get_forecast" and "sku" not in args:
            m = re.search(r"\b((?:SKU|sku)[\-_]?[A-Za-z0-9][A-Za-z0-9\-_]*)", query.query)
            if m:
                args["sku"] = m.group(1)
        if tool_name == "compare_forecast_actual" and "sku" not in args:
            m = re.search(r"\b((?:SKU|sku)[\-_]?[A-Za-z0-9][A-Za-z0-9\-_]*)", query.query)
            if m:
                args["sku"] = m.group(1)
        if tool_name == "get_orders_at_risk":
            args.setdefault("min_revenue", 0.0)
        return args


# ──────────────────────────────────────────────────────────────────────────────
# Answer rendering
# ──────────────────────────────────────────────────────────────────────────────


def render_answer(
    user_query: str,
    classification: IntentClassification,
    tool_results: Sequence[ToolResult],
) -> str:
    """Render a structured, evidence-backed answer.

    If an LLM is wired in, this is where it would be invoked. Today the
    renderer produces deterministic prose grounded in the tool payloads.
    """
    if classification.intent == Intent.UNKNOWN or not tool_results:
        return (
            "I could not confidently match your question to a grounded tool. "
            "Try asking about supplier risk, demand forecast, blast radius, "
            "signals, orders at risk, or analogous decisions."
        )
    successful = [r for r in tool_results if r.ok]
    failed = [r for r in tool_results if not r.ok]
    if not successful:
        lines = ["I could not answer your question. The following tools failed:"]
        for r in failed:
            lines.append(f"- {r.tool_name}: {r.error}")
        return "\n".join(lines)

    primary = successful[0]
    payload = primary.payload
    intro = f"I matched your question to intent '{classification.intent.value}' (confidence {classification.confidence:.0%})."

    if classification.intent == Intent.SUPPLIER_RISK:
        suppliers = payload.get("suppliers", [])
        if not suppliers:
            return intro + "\n\nNo suppliers found above the supplied risk threshold."
        lines = [intro, f"\nFound {len(suppliers)} supplier(s):"]
        for s in suppliers[:10]:
            lines.append(
                f"- {s['name']} (risk={s['risk_score']:.2f}, capacity={s['capacity_pct']:.0f}%, "
                f"on-time={s['on_time_rate']:.0%})"
            )
        return "\n".join(lines)

    if classification.intent == Intent.DEMAND_FORECAST:
        lines = [
            intro,
            f"\nForecast for {payload.get('sku')}:",
            f"- P50: {payload.get('p50'):.0f}",
            f"- P80: {payload.get('p80'):.0f}",
            f"- P95: {payload.get('p95'):.0f}",
            f"- Confidence: {payload.get('confidence'):.0%}",
            f"- Backtest WAPE: {payload.get('backtest_wape'):.1%}",
            f"- Volatility: {payload.get('volatility_coefficient'):.2f}",
            f"- Data freshness: {payload.get('data_freshness_seconds') / 60:.0f} minutes",
        ]
        drivers = payload.get("primary_drivers", [])
        if drivers:
            lines.append("Drivers:")
            for d in drivers:
                lines.append(
                    f"  - {d['name']}: {d['magnitude_pct']:+.0%} (confidence {d['confidence']:.0%})"
                )
        return "\n".join(lines)

    if classification.intent == Intent.FORECAST_CALIBRATION:
        buckets = payload.get("calibration", [])
        bias = payload.get("systematic_bias", [])
        lines = [intro, f"\nCalibration for {payload.get('sku')}: {len(buckets)} bucket(s)."]
        for b in buckets:
            lines.append(
                f"- model {b['model_version']}: MAE={b['mean_absolute_error']:.2f}, "
                f"MPE={b['mean_percentage_error']:+.2%}, P80-coverage={b['p80_coverage']:.0%} "
                f"(n={b['sample_count']})"
            )
        if bias:
            lines.append("\nSystematic bias detected:")
            for b in bias:
                lines.append(
                    f"- {b['sku']} on {b['model_version']}: {b['direction']} by {b['mean_pct_error']:+.1%}"
                )
        return "\n".join(lines)

    if classification.intent == Intent.BLAST_RADIUS:
        return (
            intro
            + f"\n\nBlast radius from {payload.get('seed_name')}: "
            + f"{payload.get('count', 0)} downstream entities affected, "
            + f"revenue exposed: ₹{payload.get('revenue_exposed', 0):.2f}L"
        )

    if classification.intent == Intent.SIGNAL_TRIAGE:
        signals = payload.get("signals", [])
        if not signals:
            return intro + "\n\nNo signals above the supplied severity threshold."
        lines = [intro, f"\nTop {min(10, len(signals))} signals:"]
        for s in signals[:10]:
            lines.append(f"- [{s['severity']:.2f}] {s['name']} ({s['signal_type']})")
        return "\n".join(lines)

    if classification.intent == Intent.ORDER_RISK:
        return (
            intro
            + f"\n\n{payload.get('count', 0)} orders at SLA risk, "
            + f"revenue at risk: ₹{payload.get('total_revenue_at_risk', 0):.2f}L"
        )

    if classification.intent == Intent.DECISION_LOOKUP:
        d = payload
        return (
            intro
            + f"\n\nDecision {d.get('decision_id')}: {d.get('situation')}\n"
            + f"Recommended: {d.get('recommended_option_id')}; Chosen: {d.get('chosen_option_id')}\n"
            + f"Status: {d.get('outcome_status')}; Financial impact: {d.get('financial_impact')}"
        )

    if classification.intent == Intent.ANALOGOUS_DECISIONS:
        analogues = payload.get("analogous_decisions", [])
        if not analogues:
            return intro + "\n\nNo analogous historical decisions found."
        lines = [intro, f"\nTop {len(analogues)} analogous past decisions:"]
        for a in analogues:
            d = a["decision"]
            lines.append(f"- [{a['similarity']:.2f}] {d['situation']} → {a['outcome_summary']}")
        return "\n".join(lines)

    return intro + "\n\n" + str(payload)


_singleton: VanessaOrchestrator | None = None


def get_vanessa() -> VanessaOrchestrator:
    """Return the process-wide singleton Vanessa orchestrator."""
    global _singleton
    if _singleton is None:
        _singleton = VanessaOrchestrator()
    return _singleton


def reset_vanessa() -> None:
    """Reset the singleton — used by tests only."""
    global _singleton
    _singleton = None
