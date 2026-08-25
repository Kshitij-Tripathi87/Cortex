"""Test Intelligence Progression Comparison — Program P.4.

Verifies:
- Benchmarking of Level 1 (Deterministic) vs Level 2 (+GNN) vs Level 3 (+MultiAgent+RL)
- Economic value lift and error reduction quantification
"""

from __future__ import annotations

from app.modules.production_validation.intelligence_comparator import (
    IntelligenceProgressionHarness,
)
from app.modules.world.state_projection import create_initial_state


class TestIntelligenceProgression:
    def test_intelligence_progression_benchmarking(self) -> None:
        """Progression report proves advanced layers measurably outperform simpler baselines."""
        state = create_initial_state(workspace_id="ws_comp", world_id="world_comp", graph_version=1)

        harness = IntelligenceProgressionHarness()
        report = harness.compare_tiers([state])

        assert report.scenario_count >= 1
        assert (
            report.level1_deterministic.mean_revenue_error_pct
            > report.level2_gnn_augmented.mean_revenue_error_pct
        )
        assert (
            report.level2_gnn_augmented.mean_revenue_error_pct
            > report.level3_full_multiagent_rl.mean_revenue_error_pct
        )

        assert report.gnn_lift_pct > 0.0
        assert report.multiagent_rl_lift_pct > report.gnn_lift_pct
        assert "Level 3" in report.recommended_active_intelligence_tier
