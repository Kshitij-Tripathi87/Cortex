"""Test End-to-End Enterprise Pilot Walkthrough Integration.

Verifies:
- Complete execution of the 8-stage enterprise pilot demonstration
- Proper stage progression from raw ingestion to closed-loop memory capture
- Net Economic Value calculation: (Protected Revenue - Intervention Cost)
"""

from __future__ import annotations

from app.modules.production_validation.pilot_demo_harness import EnterprisePilotDemoHarness


class TestEnterprisePilotDemo:
    def test_full_enterprise_pilot_demo_execution(self) -> None:
        """Complete 8-stage pilot demonstration executes cleanly and validates all invariants."""
        harness = EnterprisePilotDemoHarness()
        report = harness.run_demo(
            workspace_id="ws_apex_pilot_test",
            world_id="world_apex_pilot_test",
            operator_id="vp_supply_chain_executive",
        )

        assert report.demonstration_successful is True
        assert report.company_name == "Apex Mobility Global"
        assert len(report.stages) == 8

        # Stage 1: Ingestion
        assert report.stages[0].stage_number == 1
        assert "sha256_integrity" in report.stages[0].key_metrics

        # Stage 2: GNN Forecast
        assert report.stages[1].stage_number == 2
        assert report.stages[1].key_metrics["revenue_at_risk_usd"] == 4850000.0

        # Stage 3: Multi-Agent Deliberation
        assert report.stages[2].stage_number == 3
        assert report.stages[2].key_metrics["evidence_grounding_rate"] == "100%"

        # Stage 4: Policy Engine
        assert report.stages[3].stage_number == 4
        assert report.stages[3].key_metrics["policy_verdict"] == "PASS"

        # Stage 5: Twin Simulation
        assert report.stages[4].stage_number == 5
        assert report.stages[4].key_metrics["gate_decision"] == "PASS"

        # Stage 6: Human Decision
        assert report.stages[5].stage_number == 6
        assert report.stages[5].key_metrics["operator_decision"] == "APPROVE"

        # Stage 7: Enterprise Adapter
        assert report.stages[6].stage_number == 7
        assert (
            "EDI_850_" in report.stages[6].key_metrics["external_transaction_id"]
            or "SAP_" in report.stages[6].key_metrics["external_transaction_id"]
        )

        # Stage 8: Memory & Telemetry
        assert report.stages[7].stage_number == 8
        assert report.net_economic_value_created_usd > 4000000.0
        assert report.final_decision_lifecycle.prediction_error_pct < 10.0
