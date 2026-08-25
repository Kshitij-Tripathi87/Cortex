"""Test Supplier Similarity & Alternative Sourcing — Program K.3.

Verifies:
- Multi-factor ranking of alternative suppliers
- Embedding cosine similarity integration with operational constraints
- Transparent factor score decomposition
"""

from __future__ import annotations

from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.models import SupplyChainGNN
from app.modules.gnn.tasks.supplier_similarity import SupplierSimilarityEngine
from app.modules.world.state_projection import (
    create_initial_state,
    lead_time_var_id,
    supplier_health_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestSupplierSimilarity:
    def test_find_alternative_suppliers_multi_factor_ranking(self) -> None:
        """Rank alternative suppliers combining structural embedding and operational viability."""
        # Target supplier
        s_target = StateVariable(
            variable_id=lead_time_var_id("sup_disrupted"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_disrupted",
            entity_type="supplier",
            value=7,
        )
        s_target_health = StateVariable(
            variable_id=supplier_health_var_id("sup_disrupted"),
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_disrupted",
            entity_type="supplier",
            value=0.20,
        )

        # Candidate 1: High health, good lead time (8d), 100% capacity
        s_cand1 = StateVariable(
            variable_id=lead_time_var_id("sup_prime"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_prime",
            entity_type="supplier",
            value=8,
        )
        s_cand1_health = StateVariable(
            variable_id=supplier_health_var_id("sup_prime"),
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_prime",
            entity_type="supplier",
            value=0.98,
        )

        # Candidate 2: High lead time (30d), lower health (0.60)
        s_cand2 = StateVariable(
            variable_id=lead_time_var_id("sup_slow"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_slow",
            entity_type="supplier",
            value=30,
        )
        s_cand2_health = StateVariable(
            variable_id=supplier_health_var_id("sup_slow"),
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_slow",
            entity_type="supplier",
            value=0.60,
        )

        state = create_initial_state(
            workspace_id="ws_similarity",
            world_id="world_similarity",
            graph_version=1,
            initial_variables={
                s_target.variable_id: s_target,
                s_target_health.variable_id: s_target_health,
                s_cand1.variable_id: s_cand1,
                s_cand1_health.variable_id: s_cand1_health,
                s_cand2.variable_id: s_cand2,
                s_cand2_health.variable_id: s_cand2_health,
            },
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)
        gnn = SupplyChainGNN(in_features=graph_data.feature_dim)
        embeddings = gnn.encode(graph_data)

        engine = SupplierSimilarityEngine()
        report = engine.find_alternatives(
            target_supplier_id="sup_disrupted",
            graph_data=graph_data,
            embeddings=embeddings,
            top_k=5,
        )

        assert report.target_supplier_id == "sup_disrupted"
        assert len(report.candidates) == 2

        top_cand = report.candidates[0]
        # sup_prime must outrank sup_slow
        assert top_cand.candidate_supplier_id == "sup_prime"
        assert top_cand.rank == 1
        assert top_cand.overall_match_score > report.candidates[1].overall_match_score
        assert (
            top_cand.factor_scores.lead_time_compatibility
            > report.candidates[1].factor_scores.lead_time_compatibility
        )
        assert (
            top_cand.factor_scores.risk_profile_match
            > report.candidates[1].factor_scores.risk_profile_match
        )
