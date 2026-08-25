"""Test Enterprise Data Readiness & Hardened Pilot Ledger — Program Q.

Verifies:
- Programmatic validation environment classification (LIVE_CUSTOMER requires provenance hash)
- Enterprise Data Readiness Pre-Flight Quality Auditor (Q.2)
- REST API endpoint POST /api/v1/validation/data-readiness
- Decision coverage metrics and multi-class outcome distribution in Pilot Ledger
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.validation import router as val_router
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.production_validation.data_readiness import EnterpriseDataReadinessAuditor
from app.modules.production_validation.pilot_ledger import DesignPartnerPilotLedger
from app.modules.production_validation.validation_models import (
    MinimalEnterpriseContract,
    ValidationEnvironment,
)
from app.modules.production_validation.validation_report import PilotValidationReportGenerator


class TestProgramQDataReadinessAndLedger:
    def test_programmatic_environment_provenance_enforcement(self) -> None:
        """Claiming LIVE_CUSTOMER without customer_workspace_id/provenance drops to CONTROLLED_SYNTHETIC."""
        gen = PilotValidationReportGenerator()

        # 1. Unverified live claim -> Drops to CONTROLLED_SYNTHETIC
        rep_unverified = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Semiconductor Fab Delay",
            data_source_summary="Synthetic tables",
            predicted_revenue_risk_usd=4850000.0,
            actual_revenue_loss_usd=4720000.0,
            predicted_stockout_hours=36.0,
            actual_stockout_hours=38.0,
            predicted_orders_impacted=2,
            actual_orders_impacted=2,
            predicted_recovery_days=14.0,
            actual_recovery_days=12.0,
            cortex_action_name="Air Expedite",
            cortex_cost_usd=42000.0,
            cortex_protected_revenue_usd=4720000.0,
            human_action_name="Do Nothing",
            human_cost_usd=0.0,
            human_protected_revenue_usd=0.0,
            environment_type=ValidationEnvironment.LIVE_CUSTOMER,
            customer_workspace_id=None,  # Missing!
            provenance_audit_hash=None,  # Missing!
        )
        assert rep_unverified.environment_type == ValidationEnvironment.CONTROLLED_SYNTHETIC
        assert "[Controlled Synthetic Pilot Benchmark]" in rep_unverified.executive_verdict

        # 2. Verified live claim -> Retains LIVE_CUSTOMER
        rep_verified = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Semiconductor Fab Delay",
            data_source_summary="ERP CSV Exports",
            predicted_revenue_risk_usd=4850000.0,
            actual_revenue_loss_usd=4720000.0,
            predicted_stockout_hours=36.0,
            actual_stockout_hours=38.0,
            predicted_orders_impacted=2,
            actual_orders_impacted=2,
            predicted_recovery_days=14.0,
            actual_recovery_days=12.0,
            cortex_action_name="Air Expedite",
            cortex_cost_usd=42000.0,
            cortex_protected_revenue_usd=4720000.0,
            human_action_name="Do Nothing",
            human_cost_usd=0.0,
            human_protected_revenue_usd=0.0,
            environment_type=ValidationEnvironment.LIVE_CUSTOMER,
            customer_workspace_id="ws_apex_verified_pilot",
            provenance_audit_hash="sha256_9f83ac01...",
        )
        assert rep_verified.environment_type == ValidationEnvironment.LIVE_CUSTOMER
        assert "[Live Customer Pilot Validation]" in rep_verified.executive_verdict

    def test_data_readiness_preflight_auditor(self) -> None:
        """Data readiness auditor identifies missing lead times, computes domain completeness, and emits warnings."""
        auditor = EnterpriseDataReadinessAuditor()

        # Contract with 1 missing lead time and 1 missing quantity
        contract = MinimalEnterpriseContract(
            suppliers=[
                {"supplier_id": "sup_1", "lead_time_days": 12.0, "health_score": 0.9},
                {
                    "supplier_id": "sup_2",
                    "lead_time_days": None,
                    "health_score": 0.8,
                },  # Missing lead time!
            ],
            components=[{"component_id": "c1", "name": "Component 1"}],
            bill_of_materials=[{"parent_sku": "prod_1", "component_id": "c1"}],
            warehouses=[{"warehouse_id": "wh_1"}],
            inventory_levels=[
                {"warehouse_id": "wh_1", "component_id": "c1", "quantity": 500.0},
                {
                    "warehouse_id": "wh_1",
                    "component_id": "c2",
                    "quantity": None,
                },  # Missing quantity!
            ],
            factories=[{"factory_id": "fac_1"}],
            purchase_orders=[{"order_id": "ord_1", "quantity_ordered": 100.0}],
            source_checksum_sha256="sha256_audit_mock",
        )

        report = auditor.audit_customer_data("Apex Mobility Global", contract)

        assert report.customer_name == "Apex Mobility Global"
        assert report.overall_readiness_pct > 60.0
        assert report.domain_completeness_pct["suppliers"] == 75.0  # 100 - (1/2 * 50)
        assert report.domain_completeness_pct["inventory"] == 70.0  # 100 - (1/2 * 60)
        assert len(report.warnings) >= 2
        assert any("lead-time" in w.warning_text for w in report.warnings)
        assert any("stock quantity" in w.warning_text for w in report.warnings)

    def test_decision_coverage_and_honest_outcome_distribution(self) -> None:
        """Ledger accurately tracks decision coverage, exclusions, and multi-class win/loss distribution."""
        ledger = DesignPartnerPilotLedger()
        gen = PilotValidationReportGenerator()

        # Record an incident where Cortex won
        rep_cortex_win = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Disruption 1",
            data_source_summary="ERP Exports",
            predicted_revenue_risk_usd=1000000.0,
            actual_revenue_loss_usd=1000000.0,
            predicted_stockout_hours=24.0,
            actual_stockout_hours=24.0,
            predicted_orders_impacted=1,
            actual_orders_impacted=1,
            predicted_recovery_days=5.0,
            actual_recovery_days=5.0,
            cortex_action_name="Air Expedite",
            cortex_cost_usd=20000.0,
            cortex_protected_revenue_usd=900000.0,
            human_action_name="Delayed Transfer",
            human_cost_usd=5000.0,
            human_protected_revenue_usd=400000.0,
        )
        ledger.record_incident_report(rep_cortex_win)

        # Record an incident where Human won (Honest outcome tracking)
        rep_human_win = gen.generate_pilot_validation_report(
            customer_name="Apex Mobility Global",
            incident_title="Disruption 2",
            data_source_summary="ERP Exports",
            predicted_revenue_risk_usd=500000.0,
            actual_revenue_loss_usd=500000.0,
            predicted_stockout_hours=12.0,
            actual_stockout_hours=12.0,
            predicted_orders_impacted=1,
            actual_orders_impacted=1,
            predicted_recovery_days=2.0,
            actual_recovery_days=2.0,
            cortex_action_name="Expensive Air Charter",
            cortex_cost_usd=80000.0,
            cortex_protected_revenue_usd=200000.0,
            human_action_name="Localized Line Rebalance",
            human_cost_usd=5000.0,
            human_protected_revenue_usd=300000.0,
        )
        ledger.record_incident_report(rep_human_win)

        # Record an excluded incident
        ledger.record_excluded_disruption(
            customer_name="Apex Mobility Global",
            incident_id="disruption_3_missing_data",
            reason="INSUFFICIENT_DATA",
        )

        summary = ledger.generate_portfolio_summary(
            "Apex Mobility Global", total_eligible_disruptions=3
        )

        assert summary.total_incidents_evaluated == 2
        assert summary.coverage_metrics.incidents_excluded == 1
        assert summary.coverage_metrics.exclusion_breakdown["INSUFFICIENT_DATA"] == 1
        assert abs(summary.coverage_metrics.decision_coverage_pct - 66.67) < 0.1
        assert summary.outcome_distribution["cortex_wins"] == 1
        assert summary.outcome_distribution["human_wins"] == 1
        assert summary.cortex_win_rate_pct == 50.0

    async def test_data_readiness_api_endpoint(self, db_session) -> None:
        """REST API endpoint POST /api/v1/validation/data-readiness returns audit score."""
        auth_user = AuthContext(
            user_id="it_lead",
            email="it@apexmobility.com",
            roles=["operator"],
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
            res = await client.post(
                "/api/v1/validation/data-readiness",
                json={
                    "workspace_id": "ws_apex_pilot",
                    "customer_name": "Apex Mobility Global",
                    "suppliers": [
                        {"supplier_id": "s1", "lead_time_days": 10.0, "health_score": 0.95}
                    ],
                    "inventory_levels": [
                        {"warehouse_id": "w1", "component_id": "c1", "quantity": 100.0}
                    ],
                    "bill_of_materials": [{"parent_sku": "p1", "component_id": "c1"}],
                    "purchase_orders": [{"order_id": "o1", "quantity_ordered": 50.0}],
                },
            )
            assert res.status_code == 200, res.text
            data = res.json()
            assert data["customer_name"] == "Apex Mobility Global"
            assert data["overall_readiness_pct"] >= 80.0
            assert data["is_pilot_ready"] is True
