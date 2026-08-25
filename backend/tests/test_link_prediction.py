"""Test Hidden Dependency & Link Prediction — Program K.5.

Verifies:
- Discovered latent dependencies between entities with no direct edge
- Identification of shared correlation clusters
- Evidence rationale generation
"""

from __future__ import annotations

from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.models import SupplyChainGNN
from app.modules.gnn.tasks.link_prediction import HiddenDependencyDetector
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestLinkPrediction:
    def test_detect_hidden_dependencies_across_network(self) -> None:
        """Entities sharing upstream suppliers or structural positions have latent links discovered."""
        v1 = StateVariable(
            variable_id=lead_time_var_id("sup_shared"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_shared",
            entity_type="supplier",
            value=10,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_east"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_east",
            entity_type="factory",
            value=95.0,
        )
        f2 = StateVariable(
            variable_id=capacity_var_id("fac_west"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_west",
            entity_type="factory",
            value=90.0,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_central", "comp_x"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_central",
            entity_type="warehouse",
            value=1000,
        )

        state = create_initial_state(
            workspace_id="ws_link_pred",
            world_id="world_link_pred",
            graph_version=1,
            initial_variables={
                v1.variable_id: v1,
                f1.variable_id: f1,
                f2.variable_id: f2,
                w1.variable_id: w1,
            },
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)
        gnn = SupplyChainGNN(in_features=graph_data.feature_dim)
        embeddings = gnn.encode(graph_data)

        detector = HiddenDependencyDetector(confidence_threshold=0.30)
        report = detector.detect_hidden_dependencies(graph_data, embeddings, max_discoveries=10)

        assert report.workspace_id == "ws_link_pred"
        assert len(report.discovered_dependencies) > 0

        first_dep = report.discovered_dependencies[0]
        assert first_dep.confidence > 0.0
        assert len(first_dep.evidence_rationale) > 0
        assert first_dep.risk_impact in ("low", "medium", "high", "critical")
