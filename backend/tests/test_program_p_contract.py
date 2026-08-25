"""Test Minimal Enterprise Integration Contract — Program P.1 & P.2.

Verifies:
- Frictionless customer pilot table ingestion
- SHA-256 provenance integrity checksums
- Canonical WorldState reconstruction
"""

from __future__ import annotations

from app.modules.production_validation.data_contract import EnterpriseContractIngestor
from app.modules.production_validation.validation_models import MinimalEnterpriseContract
from app.modules.world.state_projection import (
    capacity_var_id,
    inventory_var_id,
    lead_time_var_id,
    supplier_health_var_id,
)


class TestEnterpriseDataContract:
    def test_ingest_and_reconstruct_canonical_world_state(self) -> None:
        """Minimal enterprise tables convert into an immutable, evidence-backed WorldState."""
        suppliers = [
            {"supplier_id": "sup_apex", "lead_time_days": 10.0, "health_score": 0.85},
            {"supplier_id": "sup_beacon", "lead_time_days": 14.0, "health_score": 0.95},
        ]
        warehouses = [{"warehouse_id": "wh_central"}]
        inventory = [
            {"warehouse_id": "wh_central", "component_id": "comp_chip_01", "quantity": 1500.0},
        ]
        factories = [{"factory_id": "fac_assembly_1", "capacity_pct": 90.0}]
        orders = [
            {"order_id": "ord_101", "customer_id": "cust_auto_corp", "quantity_ordered": 250.0}
        ]

        ingestor = EnterpriseContractIngestor()
        checksum = ingestor.compute_sha256_checksum(suppliers)

        contract = MinimalEnterpriseContract(
            suppliers=suppliers,
            components=[{"component_id": "comp_chip_01"}],
            bill_of_materials=[{"parent_sku": "prod_ev_module", "component_id": "comp_chip_01"}],
            warehouses=warehouses,
            inventory_levels=inventory,
            factories=factories,
            purchase_orders=orders,
            source_checksum_sha256=checksum,
        )

        state = ingestor.ingest_and_reconstruct_world_state(
            workspace_id="ws_pilot_01",
            world_id="world_pilot_01",
            contract=contract,
        )

        assert state.workspace_id == "ws_pilot_01"
        assert state.world_id == "world_pilot_01"

        # Verify variables
        assert lead_time_var_id("sup_apex") in state.variables
        assert supplier_health_var_id("sup_apex") in state.variables
        assert inventory_var_id("wh_central", "comp_chip_01") in state.variables
        assert capacity_var_id("fac_assembly_1") in state.variables

        assert float(state.variables[lead_time_var_id("sup_apex")].raw_value) == 10.0
        assert (
            float(state.variables[inventory_var_id("wh_central", "comp_chip_01")].raw_value)
            == 1500.0
        )
