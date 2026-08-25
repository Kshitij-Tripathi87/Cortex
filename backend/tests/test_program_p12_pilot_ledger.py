"""Test Design Partner Pilot Ledger & Portfolio ROI Aggregator — Program P.12.

Verifies:
- Multi-incident portfolio accumulation across 3 historical/live operational incidents
- Aggregate Net Economic Value Created calculation
- Multi-incident win-rate and error trajectory evaluation
- Commercial deployment recommendation gating
"""

from __future__ import annotations

from app.modules.production_validation.pilot_ledger import DesignPartnerPilotLedger
from app.modules.production_validation.validation_models import ValidationEnvironment
from app.modules.production_validation.validation_report import PilotValidationReportGenerator


class TestDesignPartnerPilotLedger:
    def test_multi_incident_portfolio_accumulation(self) -> None:
        """Ledger accumulates multiple design partner incidents and computes aggregate commercial ROI."""
        ledger = DesignPartnerPilotLedger()
        gen = PilotValidationReportGenerator()

        # Incident 1: Fab Supply Delay (Net: $4,678,000)
        rep1 = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Semiconductor Fab 4 Microcontroller Delay",
            data_source_summary="ERP BOM + Purchase Orders",
            predicted_revenue_risk_usd=4850000.0,
            actual_revenue_loss_usd=4720000.0,
            predicted_stockout_hours=36.0,
            actual_stockout_hours=38.0,
            predicted_orders_impacted=2,
            actual_orders_impacted=2,
            predicted_recovery_days=14.0,
            actual_recovery_days=12.0,
            cortex_action_name="NexChip Air Expedite",
            cortex_cost_usd=42000.0,
            cortex_protected_revenue_usd=4720000.0,
            human_action_name="Do Nothing / Line Stoppage",
            human_cost_usd=0.0,
            human_protected_revenue_usd=0.0,
            environment_type=ValidationEnvironment.LIVE_CUSTOMER,
            customer_workspace_id="ws_apex_verified_pilot",
            provenance_audit_hash="sha256_rep1_hash",
        )
        ledger.record_incident_report(rep1)

        # Incident 2: Long Beach Port Congestion (Net: $1,240,000)
        rep2 = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Long Beach Container Port Bottleneck",
            data_source_summary="TMS Container Telemetry + WMS Inventory",
            predicted_revenue_risk_usd=1300000.0,
            actual_revenue_loss_usd=1280000.0,
            predicted_stockout_hours=48.0,
            actual_stockout_hours=52.0,
            predicted_orders_impacted=1,
            actual_orders_impacted=1,
            predicted_recovery_days=8.0,
            actual_recovery_days=7.0,
            cortex_action_name="Intermodal Rail Re-Route (Oakland Hub)",
            cortex_cost_usd=18000.0,
            cortex_protected_revenue_usd=1258000.0,
            human_action_name="Wait for Port Clearance",
            human_cost_usd=0.0,
            human_protected_revenue_usd=0.0,
            environment_type=ValidationEnvironment.LIVE_CUSTOMER,
            customer_workspace_id="ws_apex_verified_pilot",
            provenance_audit_hash="sha256_rep2_hash",
        )
        ledger.record_incident_report(rep2)

        # Incident 3: Detroit Assembly Line Power Substation Glitch (Net: $890,000)
        rep3 = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Detroit Plant Transformer Trip",
            data_source_summary="MES Plant Capacity Logs",
            predicted_revenue_risk_usd=950000.0,
            actual_revenue_loss_usd=920000.0,
            predicted_stockout_hours=24.0,
            actual_stockout_hours=24.0,
            predicted_orders_impacted=1,
            actual_orders_impacted=1,
            predicted_recovery_days=3.0,
            actual_recovery_days=3.0,
            cortex_action_name="Capacity Rebalance to Stuttgart Plant",
            cortex_cost_usd=25000.0,
            cortex_protected_revenue_usd=915000.0,
            human_action_name="Emergency Weekend Overtime",
            human_cost_usd=45000.0,
            human_protected_revenue_usd=600000.0,
            environment_type=ValidationEnvironment.LIVE_CUSTOMER,
            customer_workspace_id="ws_apex_verified_pilot",
            provenance_audit_hash="sha256_rep3_hash",
        )
        ledger.record_incident_report(rep3)

        # Generate Portfolio Summary
        summary = ledger.generate_portfolio_summary("Apex Mobility Global")

        assert summary.customer_name == "Apex Mobility Global"
        assert summary.total_incidents_evaluated == 3
        assert summary.cumulative_unmitigated_exposure_usd == (4720000.0 + 1280000.0 + 920000.0)
        assert summary.cumulative_net_economic_value_usd == (
            (4720000.0 - 42000.0) + (1258000.0 - 18000.0) + (915000.0 - 25000.0)
        )  # $6,798,000.00
        assert summary.cortex_win_rate_pct == 100.0
        assert summary.mean_revenue_prediction_error_pct < 5.0
        assert summary.is_commercial_deployment_recommended is True
        assert "Commercial deployment verified" in summary.executive_recommendation
