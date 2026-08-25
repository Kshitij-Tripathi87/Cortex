"""Human Decision Benchmark Engine — Program P.11.5.

Captures and compares:
- Cortex AI Recommendation
- Human Operator Historical Decision
- Actual Empirical Outcome

Answers the core enterprise investment question:
"Would Cortex have produced a demonstrably better decision, and by how much ($ Delta)?"
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.production_validation.validation_models import HumanDecisionBenchmark


class HumanDecisionComparator:
    """Evaluates Cortex mitigation recommendations against historical human operator choices."""

    def benchmark_decisions(
        self,
        scenario_title: str,
        cortex_action_name: str,
        cortex_cost_usd: float,
        cortex_protected_revenue_usd: float,
        human_action_name: str,
        human_cost_usd: float,
        human_protected_revenue_usd: float,
        actual_unmitigated_loss_usd: float,
    ) -> HumanDecisionBenchmark:
        """Compare Cortex vs Human decisions across cost, protected value, and net ROI."""
        bench_id = f"bench_{uuid7()}"

        cortex_net = max(0.0, cortex_protected_revenue_usd - cortex_cost_usd)
        human_net = max(0.0, human_protected_revenue_usd - human_cost_usd)

        economic_delta = cortex_net - human_net
        improved = economic_delta > 0.0

        if economic_delta > 1000.0:
            winner = "CORTEX"
            rationale = f"Cortex generated ${economic_delta:,.2f} incremental net economic value compared to the historical human decision ({cortex_action_name} vs {human_action_name})."
        elif economic_delta < -1000.0:
            winner = "HUMAN"
            rationale = (
                f"Historical human operator achieved ${abs(economic_delta):,.2f} higher net value."
            )
        else:
            winner = "TIE"
            rationale = "Cortex and human operator achieved comparable net economic performance."

        return HumanDecisionBenchmark(
            benchmark_id=bench_id,
            scenario_title=scenario_title,
            cortex_action=cortex_action_name,
            cortex_net_value_usd=cortex_net,
            human_action=human_action_name,
            human_net_value_usd=human_net,
            actual_unmitigated_loss_usd=actual_unmitigated_loss_usd,
            economic_delta_usd=economic_delta,
            would_cortex_have_improved_decision=improved,
            winner=winner,
            verdict_rationale=rationale,
        )
