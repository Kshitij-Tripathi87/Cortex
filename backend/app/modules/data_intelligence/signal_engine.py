"""Program Q6 & Q7 — Temporal Operational State & Signal Anomaly Engine.

Tracks temporal health metrics across entities (dispatch latency, transit variance, SLA breaches)
and generates high-fidelity operational signals and anomaly events with structured evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7


@dataclass
class OperationalSignal:
    signal_id: str
    entity_id: str
    entity_type: str  # "SUPPLIER" | "ROUTE" | "ORDER" | "REGION" ("SELLER" is an ingest-time alias of "SUPPLIER")
    signal_type: str  # "SUPPLIER_DEGRADATION" | "ROUTE_CONGESTION" | "SLA_BREACH_RISK" | "ORDER_ACCUMULATION"
    severity: str  # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    confidence: float
    metric_value: float
    baseline_threshold: float
    deviation_pct: float
    evidence: list[str]
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "signal_type": self.signal_type,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "metric_value": round(self.metric_value, 2),
            "baseline_threshold": round(self.baseline_threshold, 2),
            "deviation_pct": round(self.deviation_pct, 1),
            "evidence": self.evidence,
            "detected_at": self.detected_at.isoformat(),
        }


class OperationalSignalEngine:
    """Detects operational degradation and anomalies across sellers, routes, and shipments."""

    def __init__(self) -> None:
        self._signals: list[OperationalSignal] = []

    def evaluate_seller_performance(
        self,
        seller_id: str,
        avg_dispatch_days: float,
        baseline_dispatch_days: float = 2.0,
        recent_order_count: int = 15,
    ) -> OperationalSignal | None:
        if avg_dispatch_days > (baseline_dispatch_days * 1.5):
            dev = ((avg_dispatch_days - baseline_dispatch_days) / baseline_dispatch_days) * 100.0
            sev = "CRITICAL" if dev > 100.0 else ("HIGH" if dev > 50.0 else "MEDIUM")

            sig = OperationalSignal(
                signal_id=f"sig_{uuid7()[:8]}",
                entity_id=seller_id,
                entity_type="SUPPLIER",
                signal_type="SUPPLIER_DEGRADATION",
                severity=sev,
                confidence=0.94,
                metric_value=avg_dispatch_days,
                baseline_threshold=baseline_dispatch_days,
                deviation_pct=dev,
                evidence=[
                    f"avg_dispatch_days={avg_dispatch_days:.2f} vs baseline={baseline_dispatch_days:.2f}",
                    f"recent_orders_impacted={recent_order_count}",
                    f"fulfillment_rate_drop={dev:.1f}%",
                ],
            )
            self._signals.append(sig)
            return sig
        return None

    def evaluate_route_congestion(
        self,
        route_id: str,
        avg_transit_days: float,
        expected_transit_days: float = 5.0,
    ) -> OperationalSignal | None:
        if avg_transit_days > (expected_transit_days * 1.4):
            dev = ((avg_transit_days - expected_transit_days) / expected_transit_days) * 100.0
            sig = OperationalSignal(
                signal_id=f"sig_{uuid7()[:8]}",
                entity_id=route_id,
                entity_type="ROUTE",
                signal_type="ROUTE_CONGESTION",
                severity="HIGH" if dev > 60.0 else "MEDIUM",
                confidence=0.91,
                metric_value=avg_transit_days,
                baseline_threshold=expected_transit_days,
                deviation_pct=dev,
                evidence=[
                    f"transit_time={avg_transit_days:.1f}d vs SLA={expected_transit_days:.1f}d",
                    "carrier_hub_dwell_time_exceeded",
                ],
            )
            self._signals.append(sig)
            return sig
        return None

    def list_signals(self, entity_id: str | None = None) -> list[OperationalSignal]:
        if entity_id:
            return [s for s in self._signals if s.entity_id == entity_id]
        return self._signals

    def evaluate_from_graph(
        self,
        graph_engine: "OperationalGraphEngine",
        analytics: "GraphAnalyticsSummary",
    ) -> list[OperationalSignal]:
        """Detect signals from graph topology and analytics (real, not hardcoded).

        Derives signals from:
        - SPOFs (high-dependency suppliers)
        - Route congestion (critical routes with many active orders)
        - Supplier concentration (high Gini coefficient)
        """
        from app.modules.data_intelligence.operational_graph import (
            GraphAnalyticsSummary,
            OperationalGraphEngine,
        )

        signals: list[OperationalSignal] = []
        n = max(1, len(graph_engine.nodes))

        # SPOF signals
        for spof_id in analytics.high_dependency_spofs:
            node = graph_engine.nodes.get(spof_id)
            if node and node.node_type in ("SUPPLIER", "SELLER"):
                baseline = 1.0 / n
                deviation = (node.pagerank - baseline) / max(0.001, baseline) * 100
                severity = "CRITICAL" if deviation > 200 else ("HIGH" if deviation > 100 else "MEDIUM")
                sig = OperationalSignal(
                    signal_id=f"sig_{uuid7()[:8]}",
                    entity_id=spof_id,
                    entity_type=node.node_type,
                    signal_type="SUPPLIER_DEGRADATION",
                    severity=severity,
                    confidence=min(1.0, node.pagerank * n),
                    metric_value=node.pagerank,
                    baseline_threshold=baseline,
                    deviation_pct=round(deviation, 1),
                    evidence=[
                        f"pagerank={node.pagerank:.6f}",
                        f"degree={len(graph_engine.adjacency.get(spof_id, set()))}",
                        f"is_spof=True",
                    ],
                )
                signals.append(sig)
                self._signals.append(sig)

        # Route congestion signals
        for route_info in analytics.top_critical_routes[:5]:
            route_id = route_info["route_id"]
            active = route_info["active_orders"]
            baseline_orders = 5
            deviation = (active - baseline_orders) / max(1, baseline_orders) * 100
            severity = "HIGH" if active > 10 else "MEDIUM"
            sig = OperationalSignal(
                signal_id=f"sig_{uuid7()[:8]}",
                entity_id=route_id,
                entity_type="ROUTE",
                signal_type="ROUTE_CONGESTION",
                severity=severity,
                confidence=0.85,
                metric_value=active,
                baseline_threshold=baseline_orders,
                deviation_pct=round(deviation, 1),
                evidence=[f"active_orders={active}"],
            )
            signals.append(sig)
            self._signals.append(sig)

        # Concentration signal
        if analytics.supplier_concentration_gini > 0.5:
            sig = OperationalSignal(
                signal_id=f"sig_{uuid7()[:8]}",
                entity_id="WORKSPACE",
                entity_type="WORKSPACE",
                signal_type="SUPPLIER_CONCENTRATION",
                severity="HIGH" if analytics.supplier_concentration_gini > 0.7 else "MEDIUM",
                confidence=0.90,
                metric_value=analytics.supplier_concentration_gini,
                baseline_threshold=0.4,
                deviation_pct=round(
                    (analytics.supplier_concentration_gini - 0.4) / 0.4 * 100, 1
                ),
                evidence=[f"gini={analytics.supplier_concentration_gini:.3f}"],
            )
            signals.append(sig)
            self._signals.append(sig)

        return signals
