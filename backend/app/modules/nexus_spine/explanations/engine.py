"""Nexus Explanation Engine — the "Why?" engine (item 10).

Every operational output (risk, forecast, scenario, recommendation)
returns a structured explanation covering six questions:

  WHAT         — what changed / what is happening
  WHY          — root cause / drivers
  IMPACT       — who/what is affected, financial/SLA impact
  CONFIDENCE   — how sure are we, calibration data
  EVIDENCE     — supporting observations, data sources
  WHAT NEXT    — recommended actions, simulation links

These are rendered in the UI as:
  TEXT | METRIC | TABLE | GRAPH | TIME_SERIES | RISK_CARD |
  SCENARIO_MATRIX | DECISION_CARD | EVIDENCE_CHAIN | TIMELINE
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ResponseBlockType(StrEnum):
    """Multimodal response blocks for Vanessa and the UI (item 8)."""

    TEXT = "text"
    METRIC = "metric"
    TABLE = "table"
    GRAPH = "graph"
    TIME_SERIES = "time_series"
    RISK_CARD = "risk_card"
    SCENARIO_MATRIX = "scenario_matrix"
    DECISION_CARD = "decision_card"
    EVIDENCE_CHAIN = "evidence_chain"
    TIMELINE = "timeline"


@dataclass
class ExplanationBlock:
    """One typed block in an explanation."""

    block_type: ResponseBlockType
    title: str = ""
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.block_type.value,
            "title": self.title,
            "content": self.content,
            "data": self.data,
            "metrics": self.metrics,
        }


@dataclass
class Explanation:
    """Complete explanation answering WHAT/WHY/IMPACT/CONFIDENCE/EVIDENCE/WHAT NEXT."""

    subject_id: str
    subject_kind: str  # risk|forecast|scenario|recommendation|signal
    what: str
    why: str
    impact: str
    confidence: float
    confidence_reasoning: str
    evidence_count: int
    evidence_refs: list[str]
    what_next: list[str]
    what_next_actions: list[dict[str, Any]]
    blocks: list[ExplanationBlock] = field(default_factory=list)
    impact_metrics: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind,
            "what": self.what,
            "why": self.why,
            "impact": self.impact,
            "confidence": round(self.confidence, 4),
            "confidence_reasoning": self.confidence_reasoning,
            "evidence_count": self.evidence_count,
            "evidence_refs": self.evidence_refs,
            "what_next": self.what_next,
            "what_next_actions": self.what_next_actions,
            "impact_metrics": self.impact_metrics,
            "blocks": [b.to_dict() for b in self.blocks],
            "generated_at": self.generated_at.isoformat(),
        }


class ExplanationEngine:
    """Produces structured, evidence-backed explanations for Nexus outputs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def explain_risk(
        self,
        *,
        entity_id: str,
        entity_name: str,
        entity_kind: str,
        severity: str,
        risk_score: float,
        gnn_risk_score: float | None = None,
        title: str,
        description: str,
        root_causes: list[str],
        revenue_exposure: float | None = None,
        sla_risk_pct: float | None = None,
        blast_radius_count: int = 0,
        affected_orders: int = 0,
        affected_skus: list[str] | None = None,
        affected_plants: list[str] | None = None,
        hidden_dependencies: list[dict[str, Any]] | None = None,
        confidence: float = 0.7,
        evidence_refs: list[str] | None = None,
        candidate_actions: list[dict[str, Any]] | None = None,
    ) -> Explanation:
        """Explain a risk assessment."""
        what = title or f"{severity} risk on {entity_name}"
        why_parts = []
        if root_causes:
            why_parts.append("; ".join(root_causes[:3]))
        if hidden_dependencies:
            why_parts.append(
                f"{len(hidden_dependencies)} hidden multi-hop dependencies detected by GNN"
            )
        why = ". ".join(why_parts) if why_parts else description

        impact_parts = []
        if revenue_exposure is not None:
            impact_parts.append(f"₹{revenue_exposure:,.0f} revenue exposure")
        if sla_risk_pct is not None:
            impact_parts.append(f"{int(sla_risk_pct * 100)}% SLA breach risk")
        if affected_orders > 0:
            impact_parts.append(f"{affected_orders} orders")
        if affected_skus:
            impact_parts.append(f"{len(affected_skus)} SKUs")
        if affected_plants:
            impact_parts.append(f"{len(affected_plants)} plants")
        impact = ", ".join(impact_parts) if impact_parts else "Limited impact"

        what_next = []
        w_actions = []
        if candidate_actions:
            for action in candidate_actions[:3]:
                what_next.append(
                    action.get("explanation", action.get("action_type", "Evaluate action"))
                )
                w_actions.append(
                    {
                        "action": action.get("action_type", "evaluate"),
                        "label": action.get("action_type", "SIMULATE")
                        .upper()
                        .replace("_", " ")[:20],
                    }
                )
        else:
            what_next = [
                "Run simulation to evaluate mitigation options",
                "Check alternate suppliers",
                "Review historical decisions for similar situations",
            ]
        # Always provide default action buttons
        if not w_actions:
            w_actions = [
                {"action": "simulate", "label": "SIMULATE"},
                {"action": "compare", "label": "COMPARE"},
                {"action": "evidence", "label": "EVIDENCE"},
            ]
        what_next_actions = w_actions

        blocks = [
            ExplanationBlock(
                block_type=ResponseBlockType.RISK_CARD,
                title=f"{severity.upper()} — {entity_name}",
                content=what,
                metrics={
                    "risk_score": round(risk_score, 4),
                    "gnn_risk_score": round(gnn_risk_score or risk_score, 4),
                    "revenue_exposure": revenue_exposure,
                    "sla_risk_pct": sla_risk_pct,
                    "blast_radius": blast_radius_count,
                },
            ),
        ]
        if hidden_dependencies:
            blocks.append(
                ExplanationBlock(
                    block_type=ResponseBlockType.GRAPH,
                    title="GNN hidden dependencies",
                    data={"dependencies": hidden_dependencies[:5]},
                )
            )

        return Explanation(
            subject_id=str(entity_id),
            subject_kind="risk",
            what=what,
            why=why,
            impact=impact,
            confidence=confidence,
            confidence_reasoning=self._confidence_reason(confidence, gnn_risk_score),
            evidence_count=len(evidence_refs or []),
            evidence_refs=evidence_refs or [],
            what_next=what_next,
            what_next_actions=what_next_actions,
            blocks=blocks,
            impact_metrics={
                "revenue_exposure": revenue_exposure,
                "sla_risk_pct": sla_risk_pct,
                "affected_orders": affected_orders,
                "affected_skus": affected_skus or [],
                "affected_plants": affected_plants or [],
                "blast_radius_count": blast_radius_count,
            },
        )

    def explain_forecast(
        self,
        *,
        sku: str,
        p50: float,
        p80: float,
        p95: float,
        actual: float | None = None,
        model_version: str = "baseline-v1",
        mae: float | None = None,
        wape: float | None = None,
        bias: float | None = None,
        p80_coverage: float | None = None,
        drift_detected: bool = False,
        confidence: float = 0.7,
        explanation_text: str | None = None,
    ) -> Explanation:
        """Explain a forecast vs reality (item 12)."""
        error_pct = None
        if actual is not None and p50 != 0:
            error_pct = (actual - p50) / p50 * 100

        what = f"Forecast for {sku}: P50={p50:,.0f}, P80={p80:,.0f}, P95={p95:,.0f}"
        if actual is not None:
            what += f"; Actual={actual:,.0f}"
            if error_pct is not None:
                direction = "underforecast" if error_pct > 0 else "overforecast"
                what += f" ({direction} by {abs(error_pct):.1f}%)"

        why_parts = []
        if drift_detected:
            why_parts.append("Forecast drift detected — recent accuracy differs from historical")
        if bias is not None and abs(bias) > 0.05:
            why_parts.append(
                f"Systematic bias: {'underforecasting' if bias > 0 else 'overforecasting'} by {abs(bias) * 100:.1f}%"
            )
        why = (
            ". ".join(why_parts)
            if why_parts
            else explanation_text
            or f"Forecast generated by model {model_version} using seasonal patterns and demand drivers"
        )

        impact_parts = []
        if wape is not None:
            impact_parts.append(f"Historical WAPE: {wape * 100:.1f}%")
        if error_pct is not None:
            impact_parts.append(f"Current error: {error_pct:+.1f}%")
        impact = ", ".join(impact_parts) if impact_parts else f"Model {model_version}"

        metrics_block = ExplanationBlock(
            block_type=ResponseBlockType.METRIC,
            title=f"Forecast: {sku}",
            metrics={
                "p50": p50,
                "p80": p80,
                "p95": p95,
                "actual": actual,
                "error_pct": round(error_pct, 2) if error_pct is not None else None,
                "wape": round(wape, 4) if wape is not None else None,
                "bias": round(bias, 4) if bias is not None else None,
                "p80_coverage": round(p80_coverage, 4) if p80_coverage is not None else None,
            },
        )

        return Explanation(
            subject_id=sku,
            subject_kind="forecast",
            what=what,
            why=why,
            impact=impact,
            confidence=confidence,
            confidence_reasoning=f"Based on model {model_version}"
            + (f", P80 coverage {p80_coverage:.0%}" if p80_coverage else ""),
            evidence_count=1,
            evidence_refs=[f"model:{model_version}"],
            what_next=[
                "Ask Vanessa to investigate drivers of error",
                "Review forecast segmentation by supplier/region",
                "Check for recent drift signals",
            ],
            what_next_actions=[
                {
                    "action": "ask_vanessa",
                    "label": "ASK VANESSA",
                    "query": f"Why did we {'under' if (error_pct or 0) > 0 else 'over'}forecast {sku}?",
                },
                {"action": "simulate", "label": "SIMULATE", "scenario": "demand_shift"},
            ],
            blocks=[metrics_block],
            impact_metrics={
                "p50": p50,
                "p80": p80,
                "p95": p95,
                "actual": actual,
                "error_pct": error_pct,
                "wape": wape,
                "bias": bias,
                "drift_detected": drift_detected,
            },
        )

    def explain_recommendation(
        self,
        *,
        recommendation_id: str,
        action_type: str,
        description: str,
        predicted_nev: float,
        predicted_sla: float,
        predicted_cost: float,
        confidence: float,
        alternative_count: int,
        evidence_refs: list[str] | None = None,
        simulation_id: str | None = None,
    ) -> Explanation:
        """Explain a decision recommendation (item 6)."""
        what = f"Recommended action: {description or action_type}"
        why = f"Maximizes net economic value (₹{predicted_nev:,.0f}) across {alternative_count} alternatives, with {predicted_sla * 100:.0f}% projected SLA compliance"
        impact = f"Cost: ₹{predicted_cost:,.0f}, NEV: ₹{predicted_nev:,.0f}, SLA: {predicted_sla * 100:.0f}%"

        decision_card = ExplanationBlock(
            block_type=ResponseBlockType.DECISION_CARD,
            title=what,
            metrics={
                "predicted_nev": predicted_nev,
                "predicted_sla": predicted_sla,
                "predicted_cost": predicted_cost,
                "confidence": confidence,
                "alternative_count": alternative_count,
            },
        )

        return Explanation(
            subject_id=recommendation_id,
            subject_kind="recommendation",
            what=what,
            why=why,
            impact=impact,
            confidence=confidence,
            confidence_reasoning=f"Based on {alternative_count} simulated alternatives"
            + (" and GNN features" if confidence > 0.7 else ""),
            evidence_count=len(evidence_refs or []),
            evidence_refs=evidence_refs or [],
            what_next=[
                "Review alternatives in scenario comparison",
                "View evidence chain for this recommendation",
                "Approve or reject in governance console",
            ],
            what_next_actions=[
                {"action": "simulate", "label": "SIMULATE"},
                {"action": "compare", "label": "COMPARE ALTERNATIVES"},
                {"action": "evidence", "label": "VIEW EVIDENCE"},
            ],
            blocks=[decision_card],
            impact_metrics={
                "predicted_nev": predicted_nev,
                "predicted_sla": predicted_sla,
                "predicted_cost": predicted_cost,
            },
        )

    def explain_intelligence_health(
        self,
        systems: dict[str, dict[str, Any]],
    ) -> Explanation:
        """Supply Chain Truth dashboard explanation (item 13)."""
        avg_accuracy = sum(s.get("accuracy", 0) for s in systems.values()) / max(1, len(systems))
        what = f"Nexus Intelligence Health: {avg_accuracy * 100:.0f}% average accuracy across {len(systems)} systems"
        below = [name for name, data in systems.items() if data.get("accuracy", 0) < 0.85]
        why = (
            f"{len(below)} system(s) below 85% reliability threshold"
            if below
            else "All systems operating within acceptable parameters"
        )
        impact = f"Decision confidence calibrated against historical accuracy of {avg_accuracy * 100:.0f}%"

        table_rows = []
        for name, data in systems.items():
            table_rows.append(
                {
                    "system": name,
                    "accuracy": f"{data.get('accuracy', 0) * 100:.0f}%",
                    "model": data.get("name", "-"),
                    "version": data.get("version", "-"),
                }
            )
        table_block = ExplanationBlock(
            block_type=ResponseBlockType.TABLE,
            title="Intelligence Health",
            data={"headers": ["System", "Accuracy", "Model", "Version"], "rows": table_rows},
            metrics=systems,
        )

        return Explanation(
            subject_id="intelligence-health",
            subject_kind="health",
            what=what,
            why=why,
            impact=impact,
            confidence=min(1.0, avg_accuracy + 0.1),
            confidence_reasoning="Based on rolling window of historical prediction accuracy",
            evidence_count=sum(1 for s in systems.values() if s.get("metrics")),
            evidence_refs=[],
            what_next=[
                "Drill into individual systems for detailed metrics",
                "Review drift alerts for degrading systems",
                "Compare deployed vs shadow model performance",
            ],
            what_next_actions=[],
            blocks=[table_block],
            impact_metrics={"average_accuracy": avg_accuracy, "systems": systems},
        )

    def _confidence_reason(self, confidence: float, gnn_score: float | None) -> str:
        parts = []
        if confidence >= 0.9:
            parts.append("High confidence based on multiple converging signals")
        elif confidence >= 0.7:
            parts.append("Moderate confidence")
        else:
            parts.append("Lower confidence — investigate before deciding")
        if gnn_score is not None:
            parts.append(
                f"GNN structural features {'reinforce' if gnn_score > 0.7 else 'moderate'} this assessment"
            )
        return "; ".join(parts)


_singleton: ExplanationEngine | None = None


def get_explanation_engine() -> ExplanationEngine:
    global _singleton
    if _singleton is None:
        _singleton = ExplanationEngine()
    return _singleton


def reset_explanation_engine() -> None:
    global _singleton
    _singleton = None
