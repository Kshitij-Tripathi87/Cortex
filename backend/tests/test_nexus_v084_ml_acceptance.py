"""Nexus v0.8.4 — Real ML Inference & Model Promotion Acceptance Test Matrix (M1–M15).

Tests running against PostgreSQL verifying:
  M1:  Immutable Model Registration & Versioning
  M2:  Lifecycle State Machine Transitions & Validation
  M3:  Promotion Gate — Metric Hurdle Rejection
  M4:  Promotion Gate — Calibration Coverage Hurdle Rejection
  M5:  Governed Promotion Swap & Champion Demotion
  M6:  Governed Rollback & Champion Restoration
  M7:  Real Probabilistic Inference & Quantile Monotonicity
  M8:  Prediction Provenance Tracking (Model ID, Feature Hash, World State Version)
  M9:  Outbox Event Fabric Integration (forecast.generated, model.promoted, sequential seq)
  M10: Closed-Loop Truth Pairing & Residual Calculation
  M11: Systematic Bias & Model Drift Detection
  M12: Shadow Mode Comparison
  M13: Tenant & Workspace Isolation
  M14: Role-Based AuthZ Security (Viewer vs Analyst vs Operator)
  M15: Multi-Worker Persistence & Restart Survival
"""

from __future__ import annotations

import contextlib
import os
import sys

import pytest
from fastapi import Request
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.infrastructure.database import Base
from app.modules.nexus_spine.p0_migration import (
    AuthoritativeInferenceEngine,
    AuthoritativeModelRegistry,
    AuthoritativeTruthLoop,
    DuplicateModelVersionError,
    InvalidModelTransitionError,
    ModelLifecycleStatus,
    NexusRole,
    PermissionDenied,
    Principal,
    ProbabilisticDemandForecaster,
    PromotionGateConfig,
    PromotionGateFailedError,
    compute_feature_hash,
    get_authoritative_inference_engine,
    get_authoritative_model_registry,
    get_authoritative_truth_loop,
)
from app.modules.nexus_spine.persistence.models import (
    EventRecordDB,
    ForecastRecordDB,
)

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
WS_A = "ws-ml-01"
WS_B = "ws-ml-02"


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    """Connection URL to real PostgreSQL server."""
    env_url = os.environ.get("CORTEX_TEST_PG_RACE_URL") or os.environ.get(
        "CORTEX_TEST_DATABASE_URL"
    )
    if env_url and "postgres" in env_url:
        return env_url

    try:
        import pgserver
    except ImportError:
        pytest.skip("no PostgreSQL available (pgserver or CORTEX_TEST_PG_RACE_URL required)")

    data_dir = tmp_path_factory.mktemp("nexus-v084-pg")
    db = pgserver.get_server(str(data_dir))
    sock_dir = str(data_dir)
    with contextlib.suppress(Exception):
        db.psql("CREATE DATABASE nexus_v084;")
    return f"postgresql+asyncpg://postgres@/nexus_v084?host={sock_dir}"


@pytest.fixture
async def pg_engine(pg_url):
    """Fresh database engine with clean tables for each test."""
    engine = create_async_engine(pg_url, pool_size=15, max_overflow=10)

    nexus_metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("nexus_"):
            table.to_metadata(nexus_metadata)

    async with engine.begin() as conn:
        await conn.run_sync(nexus_metadata.drop_all)
        await conn.run_sync(nexus_metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
def session_maker(pg_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)


# ─────────────────────────────────────────────────────────────────────
# Principals
# ─────────────────────────────────────────────────────────────────────

OPERATOR_A = Principal(
    user_id="usr-operator-01",
    tenant_id=TENANT_A,
    organization_id="org-a",
    workspace_id=WS_A,
    role=NexusRole.OPERATOR,
    display_name="Lead Supply Chain Operator",
)

ANALYST_A = Principal(
    user_id="usr-analyst-01",
    tenant_id=TENANT_A,
    organization_id="org-a",
    workspace_id=WS_A,
    role=NexusRole.ANALYST,
    display_name="Data Analyst",
)

VIEWER_A = Principal(
    user_id="usr-viewer-01",
    tenant_id=TENANT_A,
    organization_id="org-a",
    workspace_id=WS_A,
    role=NexusRole.VIEWER,
    display_name="Read-Only Stakeholder",
)

OPERATOR_B = Principal(
    user_id="usr-operator-02",
    tenant_id=TENANT_B,
    organization_id="org-b",
    workspace_id=WS_B,
    role=NexusRole.OPERATOR,
    display_name="Tenant B Operator",
)


# ─────────────────────────────────────────────────────────────────────
# M1: Immutable Model Registration & Versioning
# ─────────────────────────────────────────────────────────────────────


class TestM1ModelRegistrationAndImmutability:
    @pytest.mark.asyncio
    async def test_m1_model_registration_and_immutability(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # 1. Register candidate
            model_v1 = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="nexus-demand-deepar",
                version="v1.0.0",
                model_type="forecast",
                description="DeepAR demand model",
                feature_schema={"sku": "string", "price": "float", "promotion": "bool"},
                world_state_version=1,
                metrics={"wape": 0.08, "rmse": 12.4},
                actor_principal=ANALYST_A,
            )
            await session.commit()

            assert model_v1["model_id"].startswith("MDL-")
            assert model_v1["name"] == "nexus-demand-deepar"
            assert model_v1["version"] == "v1.0.0"
            assert model_v1["status"] == ModelLifecycleStatus.EVALUATING
            assert model_v1["tenant_id"] == TENANT_A
            assert model_v1["workspace_id"] == WS_A

            # 2. Attempt duplicate version registration -> MUST raise DuplicateModelVersionError
            with pytest.raises(DuplicateModelVersionError):
                await registry.register_candidate(
                    session,
                    tenant_id=TENANT_A,
                    workspace_id=WS_A,
                    name="nexus-demand-deepar",
                    version="v1.0.0",
                    model_type="forecast",
                    actor_principal=ANALYST_A,
                )

            # 3. Registering new version succeeds
            model_v2 = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="nexus-demand-deepar",
                version="v1.1.0",
                model_type="forecast",
                metrics={"wape": 0.065, "rmse": 9.8},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            assert model_v2["version"] == "v1.1.0"


# ─────────────────────────────────────────────────────────────────────
# M2: Lifecycle State Machine Transitions & Validation
# ─────────────────────────────────────────────────────────────────────


class TestM2LifecycleStateMachine:
    @pytest.mark.asyncio
    async def test_m2_lifecycle_state_machine_valid_and_invalid(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # Create in training
            model = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="state-test-model",
                version="v1.0.0",
                model_type="risk",
                actor_principal=ANALYST_A,
            )
            await session.commit()
            model_id = model["model_id"]
            assert model["status"] == ModelLifecycleStatus.TRAINING

            # 1. Illegal transition training -> deployed directly
            with pytest.raises(InvalidModelTransitionError):
                await registry.evaluate_candidate(
                    session,
                    model_id=model_id,
                    metrics={"f1": 0.9},
                    target_status=ModelLifecycleStatus.DEPLOYED,
                    actor_principal=ANALYST_A,
                )

            # 2. Legal sequence: training -> evaluating -> shadow -> calibrating -> approved
            eval_res = await registry.evaluate_candidate(
                session,
                model_id=model_id,
                metrics={"f1": 0.91, "accuracy": 0.93},
                target_status=ModelLifecycleStatus.EVALUATING,
                actor_principal=ANALYST_A,
            )
            assert eval_res["status"] == ModelLifecycleStatus.EVALUATING

            shadow_res = await registry.evaluate_candidate(
                session,
                model_id=model_id,
                metrics={"sample_count": 20},
                target_status=ModelLifecycleStatus.SHADOW,
                actor_principal=ANALYST_A,
            )
            assert shadow_res["status"] == ModelLifecycleStatus.SHADOW

            calib_res = await registry.evaluate_candidate(
                session,
                model_id=model_id,
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            assert calib_res["status"] == ModelLifecycleStatus.CALIBRATING

            appr_res = await registry.approve_model(
                session,
                model_id=model_id,
                actor_principal=OPERATOR_A,
            )
            assert appr_res["status"] == ModelLifecycleStatus.APPROVED
            assert appr_res["approval_status"] == "approved"
            assert appr_res["approved_by"] == OPERATOR_A.user_id
            await session.commit()


# ─────────────────────────────────────────────────────────────────────
# M3 & M4: Promotion Gate Hurdles Rejection
# ─────────────────────────────────────────────────────────────────────


class TestM3M4PromotionGateRejections:
    @pytest.mark.asyncio
    async def test_m3_promotion_gate_metric_hurdle_rejection(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # Candidate with degraded WAPE (0.19 > 0.12 hurdle)
            model = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="degraded-wape-model",
                version="v1.0.0",
                model_type="forecast",
                metrics={"wape": 0.19, "rmse": 75.0, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            model_id = model["model_id"]

            await registry.evaluate_candidate(
                session,
                model_id=model_id,
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(session, model_id=model_id, actor_principal=OPERATOR_A)
            await session.commit()

            # Attempt promotion -> MUST fail with PromotionGateFailedError
            with pytest.raises(PromotionGateFailedError) as exc_info:
                await registry.promote_model(
                    session,
                    model_id=model_id,
                    actor_principal=OPERATOR_A,
                    custom_gates=PromotionGateConfig(max_wape=0.12),
                )

            assert any("WAPE" in f for f in exc_info.value.failures)

    @pytest.mark.asyncio
    async def test_m4_promotion_gate_calibration_hurdle_rejection(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # Candidate with good WAPE but severely miscalibrated quantiles (P95 coverage = 0.65 instead of >= 0.90)
            model = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="miscalibrated-model",
                version="v1.0.0",
                model_type="forecast",
                metrics={"wape": 0.07, "rmse": 15.0, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.65},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            model_id = model["model_id"]

            await registry.evaluate_candidate(
                session,
                model_id=model_id,
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(session, model_id=model_id, actor_principal=OPERATOR_A)
            await session.commit()

            with pytest.raises(PromotionGateFailedError) as exc_info:
                await registry.promote_model(
                    session,
                    model_id=model_id,
                    actor_principal=OPERATOR_A,
                    custom_gates=PromotionGateConfig(min_p95_coverage=0.90),
                )

            assert any("P95 coverage" in f for f in exc_info.value.failures)


# ─────────────────────────────────────────────────────────────────────
# M5 & M6: Governed Promotion Swap & Rollback
# ─────────────────────────────────────────────────────────────────────


class TestM5M6PromotionAndRollback:
    @pytest.mark.asyncio
    async def test_m5_governed_promotion_atomic_swap(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # 1. Deploy Model A (initial champion)
            mod_a = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="forecast-champion",
                version="v1.0.0",
                model_type="forecast",
                metrics={"wape": 0.095, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            await registry.evaluate_candidate(
                session,
                model_id=mod_a["model_id"],
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(
                session, model_id=mod_a["model_id"], actor_principal=OPERATOR_A
            )
            prom_a = await registry.promote_model(
                session, model_id=mod_a["model_id"], actor_principal=OPERATOR_A
            )
            await session.commit()
            assert prom_a["model"]["status"] == ModelLifecycleStatus.DEPLOYED

            # 2. Register Model B (better candidate)
            mod_b = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="forecast-challenger",
                version="v2.0.0",
                model_type="forecast",
                metrics={"wape": 0.062, "sample_count": 50},
                calibration={"p50_coverage": 0.51, "p80_coverage": 0.81, "p95_coverage": 0.96},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            await registry.evaluate_candidate(
                session,
                model_id=mod_b["model_id"],
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(
                session, model_id=mod_b["model_id"], actor_principal=OPERATOR_A
            )

            # 3. Promote Model B -> Model B is DEPLOYED, Model A is MONITORING
            prom_b = await registry.promote_model(
                session, model_id=mod_b["model_id"], actor_principal=OPERATOR_A
            )
            await session.commit()

            assert prom_b["model"]["status"] == ModelLifecycleStatus.DEPLOYED
            assert prom_b["previous_champion_id"] == mod_a["model_id"]

            # Verify in DB
            a_db = await registry.get_model(session, mod_a["model_id"])
            b_db = await registry.get_model(session, mod_b["model_id"])
            assert a_db["status"] == ModelLifecycleStatus.MONITORING
            assert b_db["status"] == ModelLifecycleStatus.DEPLOYED

    @pytest.mark.asyncio
    async def test_m6_governed_rollback_restores_previous_champion(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # Setup champion A (monitoring) and active candidate B (deployed)
            mod_a = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="champion-to-restore",
                version="v1.0.0",
                model_type="forecast",
                metrics={"wape": 0.08, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            await registry.evaluate_candidate(
                session,
                model_id=mod_a["model_id"],
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(
                session, model_id=mod_a["model_id"], actor_principal=OPERATOR_A
            )
            await registry.promote_model(
                session, model_id=mod_a["model_id"], actor_principal=OPERATOR_A
            )
            await session.commit()

            mod_b = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="degraded-in-prod",
                version="v2.0.0",
                model_type="forecast",
                metrics={"wape": 0.075, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            await registry.evaluate_candidate(
                session,
                model_id=mod_b["model_id"],
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(
                session, model_id=mod_b["model_id"], actor_principal=OPERATOR_A
            )
            await registry.promote_model(
                session, model_id=mod_b["model_id"], actor_principal=OPERATOR_A
            )
            await session.commit()

            # Execute Rollback on Model B
            rollback_res = await registry.rollback_model(
                session,
                model_id=mod_b["model_id"],
                actor_principal=OPERATOR_A,
                reason="Severe latency spike & anomalous drift on category X",
            )
            await session.commit()

            assert rollback_res["status"] == "rolled_back"
            assert rollback_res["restored_model_id"] == mod_a["model_id"]

            b_db = await registry.get_model(session, mod_b["model_id"])
            a_db = await registry.get_model(session, mod_a["model_id"])
            assert b_db["status"] == ModelLifecycleStatus.ROLLED_BACK
            assert b_db["rollback_reason"] == "Severe latency spike & anomalous drift on category X"
            assert a_db["status"] == ModelLifecycleStatus.DEPLOYED


# ─────────────────────────────────────────────────────────────────────
# M7, M8, M9: Real Probabilistic Inference, Provenance, Outbox
# ─────────────────────────────────────────────────────────────────────


class TestM7M8M9InferenceProvenanceAndOutbox:
    @pytest.mark.asyncio
    async def test_m7_probabilistic_inference_quantile_monotonicity(self):
        forecaster = ProbabilisticDemandForecaster()
        features = {
            "base_demand": 250.0,
            "price": 45.0,
            "reference_price": 50.0,
            "promotion": True,
            "promo_lift_pct": 0.30,
            "volatility": 0.18,
            "lead_time_days": 7.0,
        }

        pred = forecaster.predict(sku="SKU-PROMO-001", features=features, horizon_days=14)

        # Invariant: Strict quantile monotonicity
        assert (
            pred.p10
            <= pred.p25
            <= pred.p50
            <= pred.p75
            <= pred.p80
            <= pred.p90
            <= pred.p95
            <= pred.p99
        )
        assert pred.confidence > 0.5
        assert pred.baseline_demand == 250.0
        assert len(pred.drivers) >= 3

        # Price sensitivity check: Higher price should lower demand
        high_price_pred = forecaster.predict(
            sku="SKU-PROMO-001",
            features={**features, "price": 70.0, "promotion": False},
            horizon_days=14,
        )
        assert high_price_pred.p50 < pred.p50

    @pytest.mark.asyncio
    async def test_m8_m9_prediction_provenance_and_outbox_emission(self, session_maker):
        registry = get_authoritative_model_registry()
        inference_engine = get_authoritative_inference_engine()

        async with session_maker() as session:
            # 1. Register & Deploy specific model version
            model = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="nexus-forecast-v3",
                version="v3.2.1",
                model_type="forecast",
                metrics={"wape": 0.05, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session.commit()
            await registry.evaluate_candidate(
                session,
                model_id=model["model_id"],
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await registry.approve_model(
                session, model_id=model["model_id"], actor_principal=OPERATOR_A
            )
            await registry.promote_model(
                session, model_id=model["model_id"], actor_principal=OPERATOR_A
            )
            await session.commit()

            # 2. Run inference
            input_features = {"base_demand": 320.0, "price": 40.0, "promotion": False}
            pred = await inference_engine.predict_demand(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-ELEC-99",
                features=input_features,
                horizon_days=14,
                world_state_version=5,
                actor_principal=ANALYST_A,
            )
            await session.commit()

            assert pred["model_id"] == model["model_id"]
            assert pred["model_version"] == "v3.2.1"
            assert pred["world_state_version"] == 5
            expected_hash = compute_feature_hash(input_features)
            assert pred["feature_hash"] == expected_hash

            # 3. Check ForecastRecordDB in PG
            fcst_stmt = select(ForecastRecordDB).where(
                ForecastRecordDB.forecast_id == pred["forecast_id"]
            )
            fcst_rec = (await session.execute(fcst_stmt)).scalar_one()
            assert fcst_rec.model_id == model["model_id"]
            assert fcst_rec.model_version == "v3.2.1"
            assert fcst_rec.feature_hash == expected_hash
            assert fcst_rec.world_state_version == 5

            # 4. Check Outbox event in nexus_events with DB-allocated seq
            evt_stmt = select(EventRecordDB).where(
                EventRecordDB.tenant_id == TENANT_A,
                EventRecordDB.workspace_id == WS_A,
                EventRecordDB.event_type == "forecast.generated",
                EventRecordDB.entity_id == pred["forecast_id"],
            )
            evt_rec = (await session.execute(evt_stmt)).scalar_one()
            assert evt_rec.seq >= 1
            assert evt_rec.payload["model_id"] == model["model_id"]
            assert evt_rec.payload["feature_hash"] == expected_hash


# ─────────────────────────────────────────────────────────────────────
# M10 & M11: Closed-Loop Truth Pairing & Drift Detection
# ─────────────────────────────────────────────────────────────────────


class TestM10M11TruthLoopAndDrift:
    @pytest.mark.asyncio
    async def test_m10_closed_loop_truth_pairing_and_containment(self, session_maker):
        truth_loop = get_authoritative_truth_loop()

        async with session_maker() as session:
            # 1. Record forecast: P50=100, P80=120, P95=140
            await truth_loop.record_forecast(
                session,
                forecast_id="FCST-TL-001",
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-TRUTH-1",
                p50=100.0,
                p80=120.0,
                p95=140.0,
                mean=100.0,
                std_dev=15.0,
                model_version="v1.0",
                world_state_version=1,
            )
            await session.commit()

            # 2. Record observation inside P80 (Actual = 110)
            obs1 = await truth_loop.observe(
                session,
                forecast_id="FCST-TL-001",
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-TRUTH-1",
                actual_value=110.0,
            )
            await session.commit()

            assert obs1["absolute_error"] == 10.0
            assert obs1["percentage_error"] == 0.10
            assert obs1["is_within_p80"] is True
            assert obs1["is_within_p95"] is True

            # 3. Record forecast & observation exceeding P80 but within P95 (Actual = 130)
            await truth_loop.record_forecast(
                session,
                forecast_id="FCST-TL-002",
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-TRUTH-1",
                p50=100.0,
                p80=120.0,
                p95=140.0,
                mean=100.0,
                std_dev=15.0,
            )
            obs2 = await truth_loop.observe(
                session,
                forecast_id="FCST-TL-002",
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-TRUTH-1",
                actual_value=130.0,
            )
            await session.commit()

            assert obs2["is_within_p80"] is False
            assert obs2["is_within_p95"] is True

    @pytest.mark.asyncio
    async def test_m11_systematic_bias_and_drift_detection(self, session_maker):
        truth_loop = get_authoritative_truth_loop()

        async with session_maker() as session:
            # Insert 6 observations that consistently under-predict actual demand by 25%
            for i in range(6):
                fid = f"FCST-DRIFT-{i}"
                await truth_loop.record_forecast(
                    session,
                    forecast_id=fid,
                    tenant_id=TENANT_A,
                    workspace_id=WS_A,
                    sku="SKU-DRIFT-A",
                    p50=100.0,
                    p80=115.0,
                    p95=125.0,
                    mean=100.0,
                    std_dev=10.0,
                )
                await truth_loop.observe(
                    session,
                    forecast_id=fid,
                    tenant_id=TENANT_A,
                    workspace_id=WS_A,
                    sku="SKU-DRIFT-A",
                    actual_value=125.0,  # 25% error
                )
            await session.commit()

            # Check systematic bias detection
            flagged = await truth_loop.systematic_bias(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                min_samples=5,
                bias_threshold=0.10,
            )
            assert len(flagged) >= 1
            assert flagged[0]["sku"] == "SKU-DRIFT-A"
            assert flagged[0]["direction"] == "under-predicting"

            # Check drift analysis
            drift = await truth_loop.detect_drift(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                min_samples=5,
                wape_drift_threshold=0.15,
            )
            assert drift["drift_detected"] is True
            assert drift["status"] in ("drift_detected", "degraded")
            assert len(drift["flagged_skus"]) >= 1


# ─────────────────────────────────────────────────────────────────────
# M12: Shadow Mode Comparison
# ─────────────────────────────────────────────────────────────────────


class TestM12ShadowModeComparison:
    @pytest.mark.asyncio
    async def test_m12_shadow_mode_evaluation_recording(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            model = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="shadow-candidate",
                version="v1.0",
                model_type="forecast",
                actor_principal=ANALYST_A,
            )
            await session.commit()

            # Record shadow evaluation
            shadow_metrics = {
                "shadow_evaluations": 100,
                "shadow_wape": 0.058,
                "shadow_rmse": 8.1,
                "champion_wape": 0.082,
                "improvement_pct": 0.29,
            }
            res = await registry.evaluate_candidate(
                session,
                model_id=model["model_id"],
                metrics={"wape": 0.058, "sample_count": 100},
                shadow_metrics=shadow_metrics,
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                target_status=ModelLifecycleStatus.SHADOW,
                actor_principal=ANALYST_A,
            )
            await session.commit()

            assert res["shadow_metrics"]["shadow_wape"] == 0.058
            assert res["shadow_metrics"]["improvement_pct"] == 0.29
            assert res["status"] == ModelLifecycleStatus.SHADOW


# ─────────────────────────────────────────────────────────────────────
# M13: Tenant & Workspace Isolation
# ─────────────────────────────────────────────────────────────────────


class TestM13TenantWorkspaceIsolation:
    @pytest.mark.asyncio
    async def test_m13_tenant_isolation_in_model_governance(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # Model registered under Tenant A / WS A
            mod_a = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="isolated-model",
                version="v1.0",
                model_type="forecast",
                actor_principal=ANALYST_A,
            )
            await session.commit()

            # Tenant B operator cannot promote Tenant A model
            with pytest.raises(PermissionDenied):
                await registry.promote_model(
                    session,
                    model_id=mod_a["model_id"],
                    actor_principal=OPERATOR_B,
                )

            # Tenant B listing does not leak Tenant A model
            models_b = await registry.list_models(
                session,
                tenant_id=TENANT_B,
                workspace_id=WS_B,
            )
            assert not any(m["model_id"] == mod_a["model_id"] for m in models_b)


# ─────────────────────────────────────────────────────────────────────
# M14: Role-Based AuthZ Security
# ─────────────────────────────────────────────────────────────────────


class TestM14RoleBasedAuthZ:
    @pytest.mark.asyncio
    async def test_m14_role_based_permissions_enforced(self, session_maker):
        registry = get_authoritative_model_registry()

        async with session_maker() as session:
            # 1. Viewer cannot register model
            with pytest.raises(PermissionDenied):
                await registry.register_candidate(
                    session,
                    tenant_id=TENANT_A,
                    workspace_id=WS_A,
                    name="unauthorized-model",
                    version="v1.0",
                    model_type="forecast",
                    actor_principal=VIEWER_A,
                )

            # 2. Analyst can register model
            mod = await registry.register_candidate(
                session,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="analyst-registered-model",
                version="v1.0",
                model_type="forecast",
                metrics={"wape": 0.08, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session.commit()

            # 3. Analyst cannot promote model
            with pytest.raises(PermissionDenied):
                await registry.promote_model(
                    session,
                    model_id=mod["model_id"],
                    actor_principal=ANALYST_A,
                )

            # 4. Operator can promote model
            prom = await registry.promote_model(
                session,
                model_id=mod["model_id"],
                actor_principal=OPERATOR_A,
            )
            await session.commit()
            assert prom["model"]["status"] == ModelLifecycleStatus.DEPLOYED


# ─────────────────────────────────────────────────────────────────────
# M15: Multi-Worker Persistence & Restart Survival
# ─────────────────────────────────────────────────────────────────────


class TestM15MultiWorkerPersistence:
    @pytest.mark.asyncio
    async def test_m15_multi_worker_restart_and_persistence(self, session_maker):
        # Worker 1: registers and promotes Model V1
        worker1_registry = AuthoritativeModelRegistry()
        async with session_maker() as session1:
            mod = await worker1_registry.register_candidate(
                session1,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                name="durable-forecast-engine",
                version="v1.0",
                model_type="forecast",
                metrics={"wape": 0.07, "sample_count": 50},
                calibration={"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
                actor_principal=ANALYST_A,
            )
            await session1.commit()
            await worker1_registry.evaluate_candidate(
                session1,
                model_id=mod["model_id"],
                metrics={},
                target_status=ModelLifecycleStatus.CALIBRATING,
                actor_principal=ANALYST_A,
            )
            await worker1_registry.approve_model(
                session1, model_id=mod["model_id"], actor_principal=OPERATOR_A
            )
            await worker1_registry.promote_model(
                session1, model_id=mod["model_id"], actor_principal=OPERATOR_A
            )
            await session1.commit()

        # SIMULATE CRASH: Worker 1 dies, memory is destroyed.
        del worker1_registry

        # Worker 2: starts fresh with empty in-memory state
        worker2_registry = AuthoritativeModelRegistry()
        worker2_inference = AuthoritativeInferenceEngine()
        worker2_truth = AuthoritativeTruthLoop()

        async with session_maker() as session2:
            # Query deployed model from PostgreSQL
            deployed = await worker2_registry.get_active_deployed(
                session2,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                model_type="forecast",
            )
            assert deployed is not None
            assert deployed["name"] == "durable-forecast-engine"
            assert deployed["status"] == ModelLifecycleStatus.DEPLOYED

            # Run inference with Worker 2
            pred = await worker2_inference.predict_demand(
                session2,
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-RESTART-001",
                features={"base_demand": 200.0, "price": 50.0},
                actor_principal=ANALYST_A,
            )
            await session2.commit()

            assert pred["model_id"] == deployed["model_id"]

            # Record observation with Worker 2
            obs = await worker2_truth.observe(
                session2,
                forecast_id=pred["forecast_id"],
                tenant_id=TENANT_A,
                workspace_id=WS_A,
                sku="SKU-RESTART-001",
                actual_value=pred["p50"] + 5.0,
            )
            await session2.commit()
            assert obs["absolute_error"] == 5.0


# ─────────────────────────────────────────────────────────────────────
# HTTP REST API Surface Acceptance Tests
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def api_client(pg_engine):
    from httpx import ASGITransport, AsyncClient

    from app.infrastructure.database import get_db as _real_get_db
    from app.infrastructure.security import AuthContext, get_current_user
    from app.main import create_app

    app = create_app()
    sf = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_db():
        async with sf() as session:
            yield session

    async def _fake_user(request: Request) -> AuthContext:
        return AuthContext(
            user_id="http-operator-01",
            email="operator@example.com",
            roles=["operator"],
            workspace_ids=[],
            is_anonymous=False,
        )

    app.dependency_overrides[_real_get_db] = _override_db
    app.dependency_overrides[get_current_user] = _fake_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class TestHttpApiSurface:
    @pytest.mark.asyncio
    async def test_http_model_lifecycle_full_cycle(self, api_client):
        # 1. Register candidate
        reg_payload = {
            "name": "http-demand-model",
            "version": "v1.0.0",
            "model_type": "forecast",
            "description": "Demand forecasting model via HTTP",
            "metrics": {"wape": 0.08, "rmse": 14.5, "sample_count": 50},
            "calibration": {"p50_coverage": 0.50, "p80_coverage": 0.80, "p95_coverage": 0.95},
        }
        res = await api_client.post(
            f"/api/v1/nexus/models/register?workspace_id={WS_A}",
            json=reg_payload,
        )
        assert res.status_code == 201, res.text
        model_data = res.json()["data"]["model"]
        model_id = model_data["model_id"]
        assert model_data["name"] == "http-demand-model"

        # 2. Duplicate registration -> 409 Conflict
        dup_res = await api_client.post(
            f"/api/v1/nexus/models/register?workspace_id={WS_A}",
            json=reg_payload,
        )
        assert dup_res.status_code == 409

        # 3. Get model
        get_res = await api_client.get(
            f"/api/v1/nexus/models/{model_id}?workspace_id={WS_A}",
        )
        assert get_res.status_code == 200
        assert get_res.json()["data"]["model"]["model_id"] == model_id

        # 4. List models
        list_res = await api_client.get(
            f"/api/v1/nexus/models?workspace_id={WS_A}&model_type=forecast",
        )
        assert list_res.status_code == 200
        assert list_res.json()["data"]["count"] >= 1

        # 5. Evaluate / Shadow
        eval_res = await api_client.post(
            f"/api/v1/nexus/models/{model_id}/evaluate?workspace_id={WS_A}",
            json={
                "metrics": {"wape": 0.075, "sample_count": 60},
                "target_status": "calibrating",
            },
        )
        assert eval_res.status_code == 200
        assert eval_res.json()["data"]["model"]["status"] == "calibrating"

        # 6. Promote model
        prom_res = await api_client.post(
            f"/api/v1/nexus/models/{model_id}/promote?workspace_id={WS_A}",
            json={"skip_gate_validation": False},
        )
        assert prom_res.status_code == 200
        assert prom_res.json()["data"]["status"] == "deployed"

        # 7. Demand Inference with Provenance
        infer_res = await api_client.post(
            f"/api/v1/nexus/inference/demand?workspace_id={WS_A}",
            json={
                "sku": "SKU-HTTP-001",
                "features": {"base_demand": 150.0, "price": 40.0, "promotion": True},
                "horizon_days": 14,
                "world_state_version": 2,
            },
        )
        assert infer_res.status_code == 201
        pred = infer_res.json()["data"]["prediction"]
        assert pred["model_id"] == model_id
        assert pred["model_version"] == "v1.0.0"
        assert pred["p10"] <= pred["p50"] <= pred["p95"]

        # 8. Intelligence Health Summary
        health_res = await api_client.get(
            f"/api/v1/nexus/models/health?workspace_id={WS_A}",
        )
        assert health_res.status_code == 200
        health = health_res.json()["data"]["health"]
        assert "Demand forecast" in health
        assert health["Demand forecast"]["model_id"] == model_id

        # 9. Rollback Model
        roll_res = await api_client.post(
            f"/api/v1/nexus/models/{model_id}/rollback?workspace_id={WS_A}",
            json={"reason": "Testing HTTP rollback capability"},
        )
        assert roll_res.status_code == 200
        assert roll_res.json()["data"]["status"] == "rolled_back"
