"""Test Deep GNN Research & Production Validation — Program K Validation Gate.

Verifies:
- Graph topological perturbation stability under edge noise
- Out-of-Distribution graph scale generalization
"""

from __future__ import annotations

from app.modules.gnn.gnn_validation import GNNResearchValidator
from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestGNNDeepResearch:
    def test_gnn_topological_perturbation_stability(self) -> None:
        """GNN node embeddings remain stable under 15% edge drop/addition noise."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_alpha"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_alpha",
            entity_type="supplier",
            value=7,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_bravo"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_bravo",
            entity_type="factory",
            value=95.0,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_charlie", "comp_1"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_charlie",
            entity_type="warehouse",
            value=1000,
        )

        state = create_initial_state(
            workspace_id="ws_gnn_research",
            world_id="world_gnn_research",
            graph_version=1,
            initial_variables={s1.variable_id: s1, f1.variable_id: f1, w1.variable_id: w1},
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)

        validator = GNNResearchValidator()
        result = validator.test_topological_perturbation_stability(graph_data, noise_ratio=0.15)

        assert result.noise_ratio == 0.15
        assert result.is_robust is True
        assert result.mean_cosine_drift < 0.40
        assert result.topological_invariance_score > 0.60

    def test_gnn_out_of_distribution_generalization(self) -> None:
        """GNN maintains unit-norm stability when network scale expands 3x."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=10,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=90.0,
        )

        state = create_initial_state(
            workspace_id="ws_gnn_ood",
            world_id="world_gnn_ood",
            graph_version=1,
            initial_variables={s1.variable_id: s1, f1.variable_id: f1},
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)

        validator = GNNResearchValidator()
        ood_result = validator.test_out_of_distribution_generalization(
            graph_data, scale_multiplier=3.0
        )

        assert ood_result.passed_ood_gate is True
        assert ood_result.generalization_score > 0.90
