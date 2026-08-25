"""Test Pilot Validation Report Generator & API — Program P.11.3, P.11.4, P.11.10.

Verifies:
- Boardroom-ready CFO/COO Pilot Validation Report generation
- Metric comparisons (Predicted vs Actual vs Error %)
- REST API endpoint POST /api/v1/validation/pilot-report
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.validation import router as val_router
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.production_validation.validation_models import ValidationEnvironment
from app.modules.production_validation.validation_report import (
    PilotValidationReportGenerator,
)


class TestPilotValidationReport:
    def test_validation_report_generator_unit(self) -> None:
        """Report generator constructs comprehensive report with granular errors and environment type."""
        gen = PilotValidationReportGenerator()

        report = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Semiconductor Fab 4 Delay",
            data_source_summary="Exported ERP CSV tables (BOM, PO, Inventory)",
            predicted_revenue_risk_usd=4850000.0,
            actual_revenue_loss_usd=4720000.0,
            predicted_stockout_hours=36.0,
            actual_stockout_hours=38.0,
            predicted_orders_impacted=2,
            actual_orders_impacted=2,
            predicted_recovery_days=14.0,
            actual_recovery_days=12.0,
            cortex_action_name="Supplier Air Expedite",
            cortex_cost_usd=42000.0,
            cortex_protected_revenue_usd=4720000.0,
            human_action_name="Do Nothing / Absorb Delay",
            human_cost_usd=0.0,
            human_protected_revenue_usd=0.0,
            environment_type="SYNTHETIC_CONTROLLED_BENCHMARK",
        )

        assert report.customer_name == "Apex Mobility Global"
        assert report.environment_type == ValidationEnvironment.CONTROLLED_SYNTHETIC
        assert len(report.metric_comparisons) == 5
        assert report.net_economic_value_usd == (4720000.0 - 42000.0)
        assert report.would_cortex_have_improved_decision is True
        assert report.human_benchmark.winner == "CORTEX"
        assert "[Controlled Synthetic Pilot Benchmark]" in report.executive_verdict
        assert "revenue exposure within 2.75%" in report.executive_verdict
        assert "recovery-time error was 16.67%" in report.executive_verdict

    async def test_pilot_report_and_portfolio_summary_api_endpoints(self, db_session) -> None:
        """REST API endpoints POST /pilot-report and GET /portfolio-summary return audited reports."""
        auth_user = AuthContext(
            user_id="cfo_user",
            email="cfo@apexmobility.com",
            roles=["executive"],
            workspace_ids=[],
            is_anonymous=False,
        )

        test_app = FastAPI()
        test_app.include_router(val_router, prefix="/api/v1/validation")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return auth_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Post incident 1 report
            res1 = await client.post(
                "/api/v1/validation/pilot-report",
                json={
                    "workspace_id": "ws_pilot_val",
                    "customer_name": "Apex Mobility Global",
                    "incident_title": "BMS Chip Supply Shock",
                    "data_source_summary": "ERP table snapshots",
                    "predicted_revenue_risk_usd": 4850000.0,
                    "actual_revenue_loss_usd": 4720000.0,
                    "predicted_stockout_hours": 36.0,
                    "actual_stockout_hours": 38.0,
                    "predicted_orders_impacted": 2,
                    "actual_orders_impacted": 2,
                    "predicted_recovery_days": 14.0,
                    "actual_recovery_days": 12.0,
                    "cortex_action_name": "NexChip Air Expedite",
                    "cortex_cost_usd": 42000.0,
                    "cortex_protected_revenue_usd": 4720000.0,
                    "human_action_name": "Production Stoppage",
                    "human_cost_usd": 0.0,
                    "human_protected_revenue_usd": 0.0,
                },
            )
            assert res1.status_code == 200, res1.text
            data1 = res1.json()
            assert data1["customer_name"] == "Apex Mobility Global"
            assert data1["net_economic_value_usd"] == 4678000.0

            # 2. Get Portfolio Summary
            sum_res = await client.get(
                "/api/v1/validation/portfolio-summary?customer_name=Apex+Mobility+Global&workspace_id=ws_pilot_val"
            )
            assert sum_res.status_code == 200, sum_res.text
            sum_data = sum_res.json()
            assert sum_data["total_incidents_evaluated"] >= 1
            assert sum_data["cumulative_net_economic_value_usd"] >= 4678000.0
            assert sum_data["cortex_win_rate_pct"] == 100.0
            assert sum_data["is_commercial_deployment_recommended"] is True
