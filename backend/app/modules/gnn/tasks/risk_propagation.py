"""Risk Propagation & Disruption Cascade Forecasting Task Engine.

Program K.6 (Risk Propagation & Cascading Disruption Forecasting):
Forecasts the downstream spread of disruptions across multi-tier networks,
predicting time-to-impact and expected financial loss per node.
"""

from __future__ import annotations

from app.modules.gnn.gnn_models import (
    EmbeddingBundle,
    HeteroGraphData,
    NodePropagationImpact,
    RiskPropagationForecast,
)


class RiskPropagationForecaster:
    """Forecasts cascading disruption dynamics from an epicenter node."""

    def __init__(
        self,
        decay_factor: float = 0.85,
        default_cost_per_loss_pct: float = 1200.0,
    ):
        self.decay_factor = decay_factor
        self.default_cost_per_loss_pct = default_cost_per_loss_pct

    def forecast_propagation(
        self,
        epicenter_entity_id: str,
        graph_data: HeteroGraphData,
        embeddings: EmbeddingBundle,
        horizon_ticks: int = 7,
        initial_severity_pct: float = 100.0,
    ) -> RiskPropagationForecast:
        """Forecast the cascading impact of a shock at epicenter_entity_id over horizon_ticks."""
        # Find epicenter node
        epicenter_nid = None
        for nid, node in graph_data.nodes.items():
            if node.entity_id == epicenter_entity_id or node.node_id == epicenter_entity_id:
                epicenter_nid = nid
                break

        if not epicenter_nid:
            return RiskPropagationForecast(
                epicenter_node_id=epicenter_entity_id,
                scenario_description=f"Shock on {epicenter_entity_id}",
                horizon_ticks=horizon_ticks,
                predicted_impacts=[],
                total_expected_revenue_loss=0.0,
                critical_path=[],
                model_version=embeddings.model_version,
            )

        # Adjacency map
        out_edges: dict[str, list[str]] = {nid: [] for nid in graph_data.nodes}
        for e in graph_data.edges:
            if e.source_id in out_edges:
                out_edges[e.source_id].append(e.target_id)

        impacts: list[NodePropagationImpact] = []
        visited = {epicenter_nid: 0}  # node -> tick reached
        queue = [(epicenter_nid, 0, initial_severity_pct, 1.0)]  # (nid, tick, severity, prob)

        critical_path = [graph_data.nodes[epicenter_nid].entity_id]
        total_revenue_loss = 0.0

        while queue:
            curr_nid, tick, severity, prob = queue.pop(0)
            if tick > horizon_ticks:
                continue

            node = graph_data.nodes[curr_nid]
            expected_loss_usd = severity * self.default_cost_per_loss_pct * prob
            total_revenue_loss += expected_loss_usd

            impacts.append(
                NodePropagationImpact(
                    node_id=node.entity_id,
                    node_type=node.node_type,
                    time_to_impact_ticks=tick,
                    impact_probability=prob,
                    expected_capacity_loss_pct=severity,
                    expected_revenue_loss_usd=expected_loss_usd,
                )
            )

            # Propagate to downstream neighbors
            next_tick = tick + 1
            next_severity = severity * self.decay_factor
            next_prob = prob * 0.90

            for nxt in out_edges.get(curr_nid, []):
                if nxt not in visited or visited[nxt] > next_tick:
                    visited[nxt] = next_tick
                    queue.append((nxt, next_tick, next_severity, next_prob))
                    nxt_entity = graph_data.nodes[nxt].entity_id
                    if nxt_entity not in critical_path:
                        critical_path.append(nxt_entity)

        return RiskPropagationForecast(
            epicenter_node_id=epicenter_entity_id,
            scenario_description=f"Simulated {initial_severity_pct:.0f}% capacity disruption at {epicenter_entity_id}",
            horizon_ticks=horizon_ticks,
            predicted_impacts=impacts,
            total_expected_revenue_loss=total_revenue_loss,
            critical_path=critical_path,
            model_version=embeddings.model_version,
        )
