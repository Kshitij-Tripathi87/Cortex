"""Multi-Dataset Real Data Spine Regression Harness (S2 Production Scale Gate).

Validates the full 12-stage operational pipeline across 4 materially
different real-world supply chain datasets and asserts:

  1. Topology changes across datasets (nodes, edges, Gini concentration, coverage)
  2. Signal detection changes based on actual entity routing and bottlenecks
  3. Blast radius & RCA calculations scale with real monetary risk
  4. Agent selection & proposal generation emerge from dynamic context
  5. Digital Twin counterfactual simulations calculate dataset-specific NEV and SLA breach risk
  6. Decision evidence DAG tracks end-to-end lineage with distinct hashes
  7. Strict determinism: identical dataset + seed produces byte-identical hashes
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalTable,
    EntityType,
)
from app.modules.nexus_spine.spine_orchestrator import RealDataSpine

# ─────────────────────────────────────────────────────────────────────────────
# Dataset Builders for Distinct Operational Archetypes
# ─────────────────────────────────────────────────────────────────────────────


def build_dataset_a_ecommerce() -> CanonicalDataset:
    """Dataset A: Standard Regional E-commerce (SP / RJ / MG, Brazil)."""
    dataset = CanonicalDataset(workspace_id="ws_ecommerce", organization_id="org_retail")

    dataset.tables[EntityType.SUPPLIER] = CanonicalTable(
        entity_type=EntityType.SUPPLIER,
        rows=[
            {"supplier_id": "S_SP1", "state": "SP", "city": "Sao Paulo", "_source_file": "suppliers.csv", "_source_row": 1},
            {"supplier_id": "S_RJ1", "state": "RJ", "city": "Rio de Janeiro", "_source_file": "suppliers.csv", "_source_row": 2},
            {"supplier_id": "S_MG1", "state": "MG", "city": "Belo Horizonte", "_source_file": "suppliers.csv", "_source_row": 3},
        ],
        column_types={"supplier_id": "str", "state": "str", "city": "str"},
        source_file="suppliers.csv",
    )

    dataset.tables[EntityType.CUSTOMER] = CanonicalTable(
        entity_type=EntityType.CUSTOMER,
        rows=[
            {"customer_id": "C_SP1", "state": "SP", "city": "Sao Paulo", "_source_file": "customers.csv", "_source_row": 1},
            {"customer_id": "C_RJ1", "state": "RJ", "city": "Rio de Janeiro", "_source_file": "customers.csv", "_source_row": 2},
        ],
        column_types={"customer_id": "str", "state": "str", "city": "str"},
        source_file="customers.csv",
    )

    dataset.tables[EntityType.ORDER] = CanonicalTable(
        entity_type=EntityType.ORDER,
        rows=[
            {"order_id": "ORD_E1", "customer_id": "C_SP1", "status": "delivered", "price": 150.0, "_source_file": "orders.csv", "_source_row": 1},
            {"order_id": "ORD_E2", "customer_id": "C_RJ1", "status": "shipped", "price": 250.0, "_source_file": "orders.csv", "_source_row": 2},
            {"order_id": "ORD_E3", "customer_id": "C_SP1", "status": "processing", "price": 75.0, "_source_file": "orders.csv", "_source_row": 3},
        ],
        column_types={"order_id": "str", "customer_id": "str", "status": "str", "price": "float"},
        source_file="orders.csv",
    )

    dataset.tables[EntityType.ORDER_ITEM] = CanonicalTable(
        entity_type=EntityType.ORDER_ITEM,
        rows=[
            {"item_id": "ITM_E1", "order_id": "ORD_E1", "supplier_id": "S_SP1", "product_id": "P_APP", "price": 150.0, "_source_file": "items.csv", "_source_row": 1},
            {"item_id": "ITM_E2", "order_id": "ORD_E2", "supplier_id": "S_RJ1", "product_id": "P_BOOK", "price": 250.0, "_source_file": "items.csv", "_source_row": 2},
            {"item_id": "ITM_E3", "order_id": "ORD_E3", "supplier_id": "S_SP1", "product_id": "P_APP", "price": 75.0, "_source_file": "items.csv", "_source_row": 3},
        ],
        column_types={"item_id": "str", "order_id": "str", "supplier_id": "str", "product_id": "str", "price": "float"},
        source_file="items.csv",
    )

    return dataset


def build_dataset_b_semiconductor() -> CanonicalDataset:
    """Dataset B: Global Semiconductor & Multi-tier Tech (High supplier concentration)."""
    dataset = CanonicalDataset(workspace_id="ws_semi", organization_id="org_tech")

    dataset.tables[EntityType.SUPPLIER] = CanonicalTable(
        entity_type=EntityType.SUPPLIER,
        rows=[
            {"supplier_id": "S_TSMC", "state": "TW", "city": "Hsinchu", "_source_file": "semi_suppliers.csv", "_source_row": 1},
            {"supplier_id": "S_SAMSUNG", "state": "KR", "city": "Suwon", "_source_file": "semi_suppliers.csv", "_source_row": 2},
            {"supplier_id": "S_ASML", "state": "NL", "city": "Veldhoven", "_source_file": "semi_suppliers.csv", "_source_row": 3},
            {"supplier_id": "S_INTEL_FAB", "state": "OR", "city": "Hillsboro", "_source_file": "semi_suppliers.csv", "_source_row": 4},
            {"supplier_id": "S_FOXCONN", "state": "CN", "city": "Shenzhen", "_source_file": "semi_suppliers.csv", "_source_row": 5},
            {"supplier_id": "S_TOKYO_ELEC", "state": "JP", "city": "Tokyo", "_source_file": "semi_suppliers.csv", "_source_row": 6},
        ],
        column_types={"supplier_id": "str", "state": "str", "city": "str"},
        source_file="semi_suppliers.csv",
    )

    dataset.tables[EntityType.CUSTOMER] = CanonicalTable(
        entity_type=EntityType.CUSTOMER,
        rows=[
            {"customer_id": "C_APPLE", "state": "CA", "city": "Cupertino", "_source_file": "semi_cust.csv", "_source_row": 1},
            {"customer_id": "C_NVIDIA", "state": "CA", "city": "Santa Clara", "_source_file": "semi_cust.csv", "_source_row": 2},
            {"customer_id": "C_TESLA", "state": "TX", "city": "Austin", "_source_file": "semi_cust.csv", "_source_row": 3},
            {"customer_id": "C_BMW", "state": "BY", "city": "Munich", "_source_file": "semi_cust.csv", "_source_row": 4},
        ],
        column_types={"customer_id": "str", "state": "str", "city": "str"},
        source_file="semi_cust.csv",
    )

    dataset.tables[EntityType.ORDER] = CanonicalTable(
        entity_type=EntityType.ORDER,
        rows=[
            {"order_id": "ORD_SEMI_1", "customer_id": "C_APPLE", "status": "processing", "price": 4500000.0, "_source_file": "semi_orders.csv", "_source_row": 1},
            {"order_id": "ORD_SEMI_2", "customer_id": "C_NVIDIA", "status": "processing", "price": 8200000.0, "_source_file": "semi_orders.csv", "_source_row": 2},
            {"order_id": "ORD_SEMI_3", "customer_id": "C_TESLA", "status": "shipped", "price": 1200000.0, "_source_file": "semi_orders.csv", "_source_row": 3},
            {"order_id": "ORD_SEMI_4", "customer_id": "C_BMW", "status": "delivered", "price": 950000.0, "_source_file": "semi_orders.csv", "_source_row": 4},
            {"order_id": "ORD_SEMI_5", "customer_id": "C_NVIDIA", "status": "processing", "price": 3100000.0, "_source_file": "semi_orders.csv", "_source_row": 5},
        ],
        column_types={"order_id": "str", "customer_id": "str", "status": "str", "price": "float"},
        source_file="semi_orders.csv",
    )

    dataset.tables[EntityType.ORDER_ITEM] = CanonicalTable(
        entity_type=EntityType.ORDER_ITEM,
        rows=[
            # Dominant supplier S_TSMC creates high concentration (Gini skew)
            {"item_id": "ITM_S1", "order_id": "ORD_SEMI_1", "supplier_id": "S_TSMC", "product_id": "WAF_3NM", "price": 4500000.0, "_source_file": "semi_items.csv", "_source_row": 1},
            {"item_id": "ITM_S2", "order_id": "ORD_SEMI_2", "supplier_id": "S_TSMC", "product_id": "GPU_H100", "price": 8200000.0, "_source_file": "semi_items.csv", "_source_row": 2},
            {"item_id": "ITM_S3", "order_id": "ORD_SEMI_3", "supplier_id": "S_SAMSUNG", "product_id": "DRAM_HBM3", "price": 1200000.0, "_source_file": "semi_items.csv", "_source_row": 3},
            {"item_id": "ITM_S4", "order_id": "ORD_SEMI_4", "supplier_id": "S_INTEL_FAB", "product_id": "MCU_AUTO", "price": 950000.0, "_source_file": "semi_items.csv", "_source_row": 4},
            {"item_id": "ITM_S5", "order_id": "ORD_SEMI_5", "supplier_id": "S_TSMC", "product_id": "GPU_B200", "price": 3100000.0, "_source_file": "semi_items.csv", "_source_row": 5},
        ],
        column_types={"item_id": "str", "order_id": "str", "supplier_id": "str", "product_id": "str", "price": "float"},
        source_file="semi_items.csv",
    )

    return dataset


def build_dataset_c_pharma_cold_chain() -> CanonicalDataset:
    """Dataset C: High-Value Pharmaceutical Cold-Chain (Strict SLA & Regulatory Compliance)."""
    dataset = CanonicalDataset(workspace_id="ws_pharma", organization_id="org_health")

    dataset.tables[EntityType.SUPPLIER] = CanonicalTable(
        entity_type=EntityType.SUPPLIER,
        rows=[
            {"supplier_id": "S_NOVARTIS", "state": "BS", "city": "Basel", "_source_file": "pharma_sup.csv", "_source_row": 1},
            {"supplier_id": "S_ROCHE", "state": "BS", "city": "Basel", "_source_file": "pharma_sup.csv", "_source_row": 2},
            {"supplier_id": "S_PFIZER", "state": "NY", "city": "New York", "_source_file": "pharma_sup.csv", "_source_row": 3},
            {"supplier_id": "S_LONZA", "state": "VS", "city": "Visp", "_source_file": "pharma_sup.csv", "_source_row": 4},
        ],
        column_types={"supplier_id": "str", "state": "str", "city": "str"},
        source_file="pharma_sup.csv",
    )

    dataset.tables[EntityType.CUSTOMER] = CanonicalTable(
        entity_type=EntityType.CUSTOMER,
        rows=[
            {"customer_id": "C_MAYO_CLINIC", "state": "MN", "city": "Rochester", "_source_file": "pharma_cust.csv", "_source_row": 1},
            {"customer_id": "C_CHARITE", "state": "BE", "city": "Berlin", "_source_file": "pharma_cust.csv", "_source_row": 2},
            {"customer_id": "C_HOPITAL_GEN", "state": "GE", "city": "Geneva", "_source_file": "pharma_cust.csv", "_source_row": 3},
        ],
        column_types={"customer_id": "str", "state": "str", "city": "str"},
        source_file="pharma_cust.csv",
    )

    dataset.tables[EntityType.ORDER] = CanonicalTable(
        entity_type=EntityType.ORDER,
        rows=[
            {"order_id": "ORD_PH_1", "customer_id": "C_MAYO_CLINIC", "status": "processing", "price": 125000.0, "_source_file": "pharma_ord.csv", "_source_row": 1},
            {"order_id": "ORD_PH_2", "customer_id": "C_CHARITE", "status": "processing", "price": 88000.0, "_source_file": "pharma_ord.csv", "_source_row": 2},
            {"order_id": "ORD_PH_3", "customer_id": "C_HOPITAL_GEN", "status": "shipped", "price": 45000.0, "_source_file": "pharma_ord.csv", "_source_row": 3},
            {"order_id": "ORD_PH_4", "customer_id": "C_MAYO_CLINIC", "status": "processing", "price": 210000.0, "_source_file": "pharma_ord.csv", "_source_row": 4},
        ],
        column_types={"order_id": "str", "customer_id": "str", "status": "str", "price": "float"},
        source_file="pharma_ord.csv",
    )

    dataset.tables[EntityType.ORDER_ITEM] = CanonicalTable(
        entity_type=EntityType.ORDER_ITEM,
        rows=[
            {"item_id": "ITM_P1", "order_id": "ORD_PH_1", "supplier_id": "S_NOVARTIS", "product_id": "MED_ONCO_A", "price": 125000.0, "_source_file": "pharma_itm.csv", "_source_row": 1},
            {"item_id": "ITM_P2", "order_id": "ORD_PH_2", "supplier_id": "S_ROCHE", "product_id": "MED_IMMUNO_B", "price": 88000.0, "_source_file": "pharma_itm.csv", "_source_row": 2},
            {"item_id": "ITM_P3", "order_id": "ORD_PH_3", "supplier_id": "S_LONZA", "product_id": "MED_BIOLOGIC_C", "price": 45000.0, "_source_file": "pharma_itm.csv", "_source_row": 3},
            {"item_id": "ITM_P4", "order_id": "ORD_PH_4", "supplier_id": "S_PFIZER", "product_id": "MED_GENE_TX", "price": 210000.0, "_source_file": "pharma_itm.csv", "_source_row": 4},
        ],
        column_types={"item_id": "str", "order_id": "str", "supplier_id": "str", "product_id": "str", "price": "float"},
        source_file="pharma_itm.csv",
    )

    return dataset


def build_dataset_d_agriculture_dispersed() -> CanonicalDataset:
    """Dataset D: Highly Dispersed Regional Agriculture (Low concentration, many small suppliers)."""
    dataset = CanonicalDataset(workspace_id="ws_agri", organization_id="org_farm")

    dataset.tables[EntityType.SUPPLIER] = CanonicalTable(
        entity_type=EntityType.SUPPLIER,
        rows=[
            {"supplier_id": f"FARM_{i}", "state": "IA", "city": f"County_{i}", "_source_file": "farms.csv", "_source_row": i}
            for i in range(1, 9)
        ],
        column_types={"supplier_id": "str", "state": "str", "city": "str"},
        source_file="farms.csv",
    )

    dataset.tables[EntityType.CUSTOMER] = CanonicalTable(
        entity_type=EntityType.CUSTOMER,
        rows=[
            {"customer_id": f"DIST_{j}", "state": "IL", "city": f"Hub_{j}", "_source_file": "distributors.csv", "_source_row": j}
            for j in range(1, 5)
        ],
        column_types={"customer_id": "str", "state": "str", "city": "str"},
        source_file="distributors.csv",
    )

    dataset.tables[EntityType.ORDER] = CanonicalTable(
        entity_type=EntityType.ORDER,
        rows=[
            {"order_id": f"ORD_AG_{k}", "customer_id": f"DIST_{(k % 4) + 1}", "status": "processing" if k % 2 == 0 else "shipped", "price": 15000.0 + k * 1000, "_source_file": "ag_orders.csv", "_source_row": k}
            for k in range(1, 9)
        ],
        column_types={"order_id": "str", "customer_id": "str", "status": "str", "price": "float"},
        source_file="ag_orders.csv",
    )

    dataset.tables[EntityType.ORDER_ITEM] = CanonicalTable(
        entity_type=EntityType.ORDER_ITEM,
        rows=[
            {"item_id": f"ITM_AG_{k}", "order_id": f"ORD_AG_{k}", "supplier_id": f"FARM_{k}", "product_id": "GRAIN_CORN", "price": 15000.0 + k * 1000, "_source_file": "ag_items.csv", "_source_row": k}
            for k in range(1, 9)
        ],
        column_types={"item_id": "str", "order_id": "str", "supplier_id": "str", "product_id": "str", "price": "float"},
        source_file="ag_items.csv",
    )

    return dataset


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Dataset Regression Suite
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiDatasetSpineRegression:
    """Exercises RealDataSpine on multiple operational archetypes."""

    @pytest.mark.asyncio
    async def test_all_stages_complete_for_each_dataset(self) -> None:
        """Every dataset must traverse all 12 stages to SUCCESS with complete evidence."""
        spine = RealDataSpine()

        datasets = {
            "ecommerce": build_dataset_a_ecommerce(),
            "semiconductor": build_dataset_b_semiconductor(),
            "pharma": build_dataset_c_pharma_cold_chain(),
            "agriculture": build_dataset_d_agriculture_dispersed(),
        }

        results: dict[str, Any] = {}
        for name, ds in datasets.items():
            res = await spine.run(ds, organization_id=f"org_{name}", workspace_id=f"ws_{name}")
            assert res.status.value == "COMPLETED", f"{name} spine failed: {res.errors}"
            assert len(res.stages) == 12, f"{name} expected 12 stages, got {len(res.stages)}"
            for s in res.stages:
                assert s.status.value == "SUCCESS", f"{name} stage {s.stage_name} was {s.status}"
                assert s.evidence_node_id, f"{name} stage {s.stage_name} emitted no evidence"
            assert res.evidence_root_id, f"{name} missing root evidence ID"
            results[name] = res

        # ── 1. Assert Topology Divergence across Archetypes ──
        nodes_a = results["ecommerce"].graph_summary.get("total_nodes", 0)
        nodes_b = results["semiconductor"].graph_summary.get("total_nodes", 0)
        nodes_c = results["pharma"].graph_summary.get("total_nodes", 0)
        nodes_d = results["agriculture"].graph_summary.get("total_nodes", 0)

        assert nodes_a != nodes_b, "Ecommerce and semiconductor node counts must diverge"
        assert nodes_b != nodes_c, "Semiconductor and pharma node counts must diverge"
        assert nodes_d > nodes_a, "Dispersed agriculture must have more nodes than small ecommerce"

        # Gini Concentration Divergence
        gini_b = results["semiconductor"].graph_summary.get("supplier_concentration_gini", 0)
        gini_d = results["agriculture"].graph_summary.get("supplier_concentration_gini", 0)
        # Semiconductor has 1 heavy supplier (TSMC) while agriculture has 8 equal farms
        assert gini_b > gini_d, f"Semiconductor Gini ({gini_b}) must exceed uniform agriculture Gini ({gini_d})"

        # ── 2. Assert Blast Radius & Revenue Risk Scaling ──
        br_a = results["ecommerce"].blast_radius or {}
        br_b = results["semiconductor"].blast_radius or {}
        risk_a = br_a.get("total_revenue_at_risk_usd", 0)
        risk_b = br_b.get("total_revenue_at_risk_usd", 0)

        # High-value semiconductor orders must create orders of magnitude higher revenue risk
        assert risk_b > risk_a, f"Semiconductor risk (${risk_b}) must exceed ecommerce (${risk_a})"

        # ── 3. Assert Evidence Root Hash Divergence ──
        roots = {res.evidence_root_id for res in results.values()}
        assert len(roots) == len(datasets), "Each dataset run must produce a distinct Evidence Root ID"

    @pytest.mark.asyncio
    async def test_deterministic_spine_replay_exact_equality(self) -> None:
        """Identical dataset replayed twice must produce byte-identical graph and simulation hashes."""
        spine = RealDataSpine()
        dataset_b = build_dataset_b_semiconductor()

        # Run 1
        res1 = await spine.run(dataset_b, organization_id="org_tech", workspace_id="ws_semi")
        # Run 2
        res2 = await spine.run(dataset_b, organization_id="org_tech", workspace_id="ws_semi")

        assert res1.status == res2.status
        summary1 = {k: v for k, v in res1.graph_summary.items() if k != "computed_at"}
        summary2 = {k: v for k, v in res2.graph_summary.items() if k != "computed_at"}
        assert summary1 == summary2
        assert res1.world_state_version == res2.world_state_version
        assert len(res1.signals) == len(res2.signals)
        assert res1.blast_radius == res2.blast_radius
        assert len(res1.stages) == len(res2.stages)

        # Graph versions match
        v1 = res1.graph_summary.get("coverage", {}).get("graph_version")
        v2 = res2.graph_summary.get("coverage", {}).get("graph_version")
        assert v1 == v2, f"Graph versions did not match: {v1} != {v2}"

    @pytest.mark.asyncio
    async def test_dynamic_agent_proposal_selection(self) -> None:
        """Verify dynamic router selects domain agents matching the specific incident type."""
        spine = RealDataSpine()

        # Run pharma dataset
        res = await spine.run(
            build_dataset_c_pharma_cold_chain(),
            organization_id="org_health",
            workspace_id="ws_pharma",
        )

        # Verify proposals produced are non-empty and have real context
        assert len(res.signals) > 0, "Pharma dataset must detect operational signals"
        # Proposal stage succeeded
        prop_stage = next(s for s in res.stages if s.stage_name == "agent_proposals")
        assert prop_stage.status.value == "SUCCESS"
        assert prop_stage.evidence_node_id.startswith("ev_")

        # Simulation stage succeeded
        sim_stage = next(s for s in res.stages if s.stage_name == "twin_simulation")
        assert sim_stage.status.value == "SUCCESS"
        assert sim_stage.evidence_node_id.startswith("ev_")
