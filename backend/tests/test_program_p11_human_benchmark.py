"""Test Human Decision Benchmark Engine — Program P.11.5.

Verifies:
- Comparison of Cortex AI recommendations vs historical human operator decisions
- Economic delta calculation (Net_Cortex - Net_Human)
- Determination of whether Cortex would have produced a demonstrably better decision
"""

from __future__ import annotations

from app.modules.production_validation.human_benchmark import HumanDecisionComparator


class TestHumanDecisionBenchmark:
    def test_cortex_outperforms_historical_human_decision(self) -> None:
        """Benchmark confirms Cortex generated higher net value than historical human action."""
        comparator = HumanDecisionComparator()

        # Scenario: Supplier disruption with $5M exposure
        # Human decision: Delayed ground transfer costing $10k, protecting $2.5M (Net: $2.49M)
        # Cortex recommendation: Air express expedite costing $40k, protecting $4.8M (Net: $4.76M)
        benchmark = comparator.benchmark_decisions(
            scenario_title="Microcontroller Fab Delay",
            cortex_action_name="Air Express Expedite (NexChip)",
            cortex_cost_usd=40000.0,
            cortex_protected_revenue_usd=4800000.0,
            human_action_name="Delayed Ground Transfer",
            human_cost_usd=10000.0,
            human_protected_revenue_usd=2500000.0,
            actual_unmitigated_loss_usd=5000000.0,
        )

        assert benchmark.scenario_title == "Microcontroller Fab Delay"
        assert benchmark.cortex_net_value_usd == 4760000.0
        assert benchmark.human_net_value_usd == 2490000.0
        assert benchmark.economic_delta_usd == (4760000.0 - 2490000.0)  # +$2,270,000
        assert benchmark.would_cortex_have_improved_decision is True
        assert benchmark.winner == "CORTEX"
        assert "incremental net economic value" in benchmark.verdict_rationale
