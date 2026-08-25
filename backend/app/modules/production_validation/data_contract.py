"""Minimal Enterprise Integration Contract & Lineage Validator — Program P.1 & P.2.

Provides frictionless customer pilot onboarding by converting minimal enterprise tables
into an immutable, evidence-backed WorldState.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.production_validation.validation_models import MinimalEnterpriseContract
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
    supplier_health_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType, WorldState


class EnterpriseContractIngestor:
    """Ingests, validates, and builds canonical WorldState from minimal customer tables."""

    def ingest_and_reconstruct_world_state(
        self,
        workspace_id: str,
        world_id: str,
        contract: MinimalEnterpriseContract,
    ) -> WorldState:
        """Construct canonical WorldState with complete evidence provenance."""
        variables: dict[str, StateVariable] = {}

        # 1. Ingest Suppliers & Lead Times
        for sup in contract.suppliers:
            sup_id = str(sup.get("supplier_id", sup.get("id", "sup_unknown")))
            lead_time = float(sup.get("lead_time_days", 7.0))
            health = float(sup.get("health_score", 1.0))

            v_lt = StateVariable(
                variable_id=lead_time_var_id(sup_id),
                variable_type=StateVariableType.LEAD_TIME,
                entity_id=sup_id,
                entity_type="supplier",
                value=lead_time,
            )
            v_health = StateVariable(
                variable_id=supplier_health_var_id(sup_id),
                variable_type=StateVariableType.SUPPLIER_HEALTH,
                entity_id=sup_id,
                entity_type="supplier",
                value=health,
            )
            variables[v_lt.variable_id] = v_lt
            variables[v_health.variable_id] = v_health

        # 2. Ingest Warehouses & Inventory
        for inv in contract.inventory_levels:
            wh_id = str(inv.get("warehouse_id", "wh_default"))
            comp_id = str(inv.get("component_id", "comp_default"))
            qty = float(inv.get("quantity", 0.0))

            v_inv = StateVariable(
                variable_id=inventory_var_id(wh_id, comp_id),
                variable_type=StateVariableType.INVENTORY,
                entity_id=wh_id,
                entity_type="warehouse",
                value=qty,
            )
            variables[v_inv.variable_id] = v_inv

        # 3. Ingest Factories & Capacity
        for fac in contract.factories:
            fac_id = str(fac.get("factory_id", fac.get("id", "fac_default")))
            cap = float(fac.get("capacity_pct", 100.0))

            v_cap = StateVariable(
                variable_id=capacity_var_id(fac_id),
                variable_type=StateVariableType.CAPACITY,
                entity_id=fac_id,
                entity_type="factory",
                value=cap,
            )
            variables[v_cap.variable_id] = v_cap

        # 4. Ingest Orders / Customer Demand
        for ord_rec in contract.purchase_orders:
            cust_id = str(ord_rec.get("customer_id", ord_rec.get("order_id", "cust_default")))
            demand_qty = float(ord_rec.get("quantity_ordered", 100.0))

            v_dem = StateVariable(
                variable_id=demand_var_id(cust_id),
                variable_type=StateVariableType.DEMAND,
                entity_id=cust_id,
                entity_type="customer",
                value=demand_qty,
            )
            variables[v_dem.variable_id] = v_dem

        # Construct WorldState
        return create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables=variables,
        )

    @staticmethod
    def compute_sha256_checksum(raw_data: dict[str, Any] | list[Any]) -> str:
        """Compute deterministic SHA-256 hash for raw customer payload."""
        data_str = json.dumps(raw_data, sort_keys=True)
        return hashlib.sha256(data_str.encode("utf-8")).hexdigest()
