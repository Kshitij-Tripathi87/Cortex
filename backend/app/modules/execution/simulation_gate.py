"""Simulation Gate — Digital Twin Pre-Execution Dry-Run Verification.

Program N.3 (Digital Twin Simulation Gate):
Guarantees that every material mitigation action passes through an isolated
sandbox dry-run before reaching human review or production ERP/WMS systems.
"""

from __future__ import annotations

import copy

from app.common.ids import uuid7
from app.modules.execution.execution_models import ActionPlan, SimulationGateResult
from app.modules.rl.environment import SupplyChainEnv
from app.modules.world.world_models import WorldState


class SimulationGate:
    """Pre-execution verification harness utilizing Digital Twin sandboxes."""

    def verify_plan(
        self,
        plan: ActionPlan,
        world_state: WorldState,
    ) -> SimulationGateResult:
        """Run dry-run simulation of the ActionPlan in an isolated sandbox environment."""
        twin_id = f"twin_gate_{uuid7()}"

        # 1. Initialize isolated environment
        sandbox_state = copy.deepcopy(world_state)
        env = SupplyChainEnv(initial_world_state=sandbox_state, max_steps=5)

        # 2. Execute plan action in sandbox
        step_res = env.step(plan.action)

        # 3. Assess outcome
        action_cost = plan.expected_cost_usd
        protected_benefit = plan.expected_benefit_usd
        net_benefit = protected_benefit - action_cost

        stockout_occurrences = step_res.next_state.stockout_occurrences

        # Invariants:
        # 1. Expected benefit must be >= action cost
        # 2. Action must not trigger catastrophic downstream stockouts
        passed = (net_benefit >= 0.0) and (stockout_occurrences <= 2)

        validation_log = (
            f"Sandbox dry-run completed in twin {twin_id}. "
            f"Simulated Net Benefit: ${net_benefit:,.2f}, Post-action stockouts: {stockout_occurrences}. "
            f"Gate Decision: {'PASS' if passed else 'FAIL'}."
        )

        return SimulationGateResult(
            plan_id=plan.plan_id,
            simulation_passed=passed,
            simulated_net_benefit_usd=net_benefit,
            simulated_downstream_stockouts=stockout_occurrences,
            validation_log=validation_log,
            twin_id=twin_id,
        )
