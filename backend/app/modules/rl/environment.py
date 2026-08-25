"""Supply Chain MDP Environment — Gym-compatible Sandbox for RL Policies.

Program L.1 (Markov Decision Process Environment):
Interfaces directly with the deterministic WorldState and Digital Twin substrate,
enabling RL policies to step through time and evaluate mitigation actions.
"""

from __future__ import annotations

import copy

from app.modules.rl.rl_models import (
    ActionType,
    EnvStateVector,
    MitigationAction,
    StepResult,
)
from app.modules.simulation.metrics import CanonicalKPICalculator
from app.modules.twin.twin_validation_helpers import make_fake_event
from app.modules.world.state_projection import (
    apply_transition,
    create_state_snapshot,
    project_event_to_transition,
)
from app.modules.world.world_models import StateVariableType, WorldState


class SupplyChainEnv:
    """Markov Decision Process environment for supply chain mitigation."""

    def __init__(
        self,
        initial_world_state: WorldState,
        max_steps: int = 10,
        expedite_cost_per_day: float = 1500.0,
        transfer_cost_per_unit: float = 8.0,
        stockout_penalty_per_unit: float = 100.0,
    ):
        self.base_state = initial_world_state
        self.current_state = copy.deepcopy(initial_world_state)
        self.max_steps = max_steps
        self.expedite_cost_per_day = expedite_cost_per_day
        self.transfer_cost_per_unit = transfer_cost_per_unit
        self.stockout_penalty_per_unit = stockout_penalty_per_unit

        self.current_step = 0
        self.kpi_calc = CanonicalKPICalculator()

    def reset(self) -> EnvStateVector:
        """Reset the environment back to initial base state."""
        self.current_state = copy.deepcopy(self.base_state)
        self.current_step = 0
        return self._extract_state_vector()

    def step(self, action: MitigationAction) -> StepResult:
        """Execute a mitigation action in the environment."""
        self.current_step += 1
        baseline_kpis = self.kpi_calc.compute(self.base_state, self.current_state)

        action_cost = 0.0

        # 1. Apply Action Transition
        if action.action_type == ActionType.TRANSFER_INVENTORY and action.target_entity_id:
            # Transfer from entity_id (source warehouse) to target_entity_id (dest warehouse)
            qty = max(0.0, action.quantity)
            src_wh = action.entity_id
            dst_wh = action.target_entity_id
            action_cost = qty * self.transfer_cost_per_unit

            # Apply decrement to source
            evt_src = make_fake_event(
                event_id=f"rl_trf_src_{self.current_step}",
                world_id=self.current_state.world_id,
                workspace_id=self.current_state.workspace_id,
                entity_type="warehouse",
                entity_id=src_wh,
                event_type="inventory_changed",
                payload={
                    "warehouse_id": src_wh,
                    "component_id": "comp_01",
                    "quantity_change": -int(qty),
                },
            )
            tr_src = project_event_to_transition(self.current_state, evt_src)
            if tr_src:
                self.current_state = apply_transition(self.current_state, tr_src)

            # Apply increment to destination
            evt_dst = make_fake_event(
                event_id=f"rl_trf_dst_{self.current_step}",
                world_id=self.current_state.world_id,
                workspace_id=self.current_state.workspace_id,
                entity_type="warehouse",
                entity_id=dst_wh,
                event_type="inventory_changed",
                payload={
                    "warehouse_id": dst_wh,
                    "component_id": "comp_01",
                    "quantity_change": int(qty),
                },
            )
            tr_dst = project_event_to_transition(self.current_state, evt_dst)
            if tr_dst:
                self.current_state = apply_transition(self.current_state, tr_dst)

        elif action.action_type == ActionType.EXPEDITE_SUPPLIER:
            # Reduce lead time by expediting
            sup_id = action.entity_id
            days_saved = max(1, int(action.quantity))
            action_cost = days_saved * self.expedite_cost_per_day

            evt_exp = make_fake_event(
                event_id=f"rl_exp_{self.current_step}",
                world_id=self.current_state.world_id,
                workspace_id=self.current_state.workspace_id,
                entity_type="supplier",
                entity_id=sup_id,
                event_type="supplier_delayed",
                payload={"delay_days": -days_saved, "disruption_type": "rush_expedite"},
            )
            tr_exp = project_event_to_transition(self.current_state, evt_exp)
            if tr_exp:
                self.current_state = apply_transition(self.current_state, tr_exp)

        # 2. Simulate Background Dynamics (Customer consumption per step)
        for var in self.current_state.variables.values():
            if var.variable_type == StateVariableType.INVENTORY and float(var.raw_value) > 0:
                burn_evt = make_fake_event(
                    event_id=f"rl_burn_{self.current_step}_{var.entity_id}",
                    world_id=self.current_state.world_id,
                    workspace_id=self.current_state.workspace_id,
                    entity_type="warehouse",
                    entity_id=var.entity_id,
                    event_type="inventory_changed",
                    payload={
                        "warehouse_id": var.entity_id,
                        "component_id": "comp_01",
                        "quantity_change": -30,
                    },
                )
                tr_burn = project_event_to_transition(self.current_state, burn_evt)
                if tr_burn:
                    self.current_state = apply_transition(self.current_state, tr_burn)

        # 3. Compute Reward & KPI Deltas
        next_kpis = self.kpi_calc.compute(self.base_state, self.current_state)

        rev_loss = next_kpis.financial.revenue_at_risk.value
        stockout_hrs = next_kpis.operational.stockout_hours.value

        # Reward = - (Revenue Lost + Action Cost + Stockout Penalty)
        reward = -(rev_loss * 0.10 + action_cost + stockout_hrs * 10.0)

        done = self.current_step >= self.max_steps
        next_state_vec = self._extract_state_vector()

        kpi_deltas = {
            "revenue_at_risk_delta": rev_loss - baseline_kpis.financial.revenue_at_risk.value,
            "action_cost_usd": action_cost,
            "stockout_hours": stockout_hrs,
        }

        return StepResult(
            next_state=next_state_vec,
            reward=reward,
            done=done,
            kpi_deltas=kpi_deltas,
            info={"action_type": action.action_type.value, "step": self.current_step},
        )

    def get_legal_actions(self) -> list[MitigationAction]:
        """Discover valid actions from current network topology and state."""
        actions = [
            MitigationAction(
                action_type=ActionType.NOOP,
                entity_id="system",
                rationale="Observe network without intervening",
            )
        ]

        warehouses = [
            v
            for v in self.current_state.variables.values()
            if v.variable_type == StateVariableType.INVENTORY
        ]
        suppliers = [
            v
            for v in self.current_state.variables.values()
            if v.variable_type == StateVariableType.LEAD_TIME
        ]

        # 1. Candidate inventory transfers between warehouses
        for w_src in warehouses:
            src_inv = float(w_src.raw_value)
            if src_inv > 100.0:
                for w_dst in warehouses:
                    if w_src.entity_id != w_dst.entity_id:
                        transfer_qty = min(200.0, src_inv / 2.0)
                        actions.append(
                            MitigationAction(
                                action_type=ActionType.TRANSFER_INVENTORY,
                                entity_id=w_src.entity_id,
                                target_entity_id=w_dst.entity_id,
                                quantity=transfer_qty,
                                cost_usd=transfer_qty * self.transfer_cost_per_unit,
                                rationale=f"Transfer {transfer_qty:.0f} units from {w_src.entity_id} to {w_dst.entity_id}",
                            )
                        )

        # 2. Candidate supplier expedites
        for s in suppliers:
            actions.append(
                MitigationAction(
                    action_type=ActionType.EXPEDITE_SUPPLIER,
                    entity_id=s.entity_id,
                    quantity=3.0,  # 3 days expedite
                    cost_usd=3.0 * self.expedite_cost_per_day,
                    rationale=f"Expedite supplier {s.entity_id} by 3 days",
                )
            )

        return actions

    def _extract_state_vector(self) -> EnvStateVector:
        """Extract flat numerical feature vector and summary statistics from WorldState."""
        total_inv = 0.0
        capacities = []
        max_lt = 0.0
        stockout_count = 0

        features = []
        for var in sorted(self.current_state.variables.values(), key=lambda v: v.variable_id):
            val = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
            features.append(val)

            if var.variable_type == StateVariableType.INVENTORY:
                total_inv += val
                if val <= 0:
                    stockout_count += 1
            elif var.variable_type == StateVariableType.CAPACITY:
                capacities.append(val)
            elif var.variable_type == StateVariableType.LEAD_TIME:
                if val > max_lt:
                    max_lt = val

        avg_cap = sum(capacities) / len(capacities) if capacities else 100.0
        snapshot = create_state_snapshot(self.current_state)

        return EnvStateVector(
            state_features=features,
            total_inventory=total_inv,
            avg_capacity_pct=avg_cap,
            max_lead_time_days=max_lt,
            stockout_occurrences=stockout_count,
            step_number=self.current_step,
            state_hash=snapshot.state_hash,
        )
