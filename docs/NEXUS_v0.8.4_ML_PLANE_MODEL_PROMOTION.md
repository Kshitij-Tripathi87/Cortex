# NEXUS v0.8.4: Real ML Inference & Model Promotion

**Milestone Status:** **CLOSED (2026-09-09)**

---

## 1. Executive Summary & Core Invariant

Nexus v0.8.4 establishes the governed Machine Learning plane for Cortex. 

### Core Invariant
> **A trained model is a governed, immutable production dependency with complete prediction provenance and closed-loop feedback — never an unversioned notebook or in-memory artifact.**

```text
               Training Dataset (Olist / Canonical)
                               │
                               ▼
                  Model Candidate Registered
                (nexus_model_registry: TRAINING)
                               │
                               ▼
                   Evaluation & Shadow Mode
                     (STATUS: EVALUATING / SHADOW)
                               │
                               ▼
                     Promotion Gate Check
           - WAPE <= 0.12, RMSE <= 50.0 (Accuracy)
           - Quantile Coverage P50, P80, P95 (Calibration)
           - Candidate vs Champion Shadow Parity (<= 5% Degradation)
           - Operator/Admin Authorization Gated
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
        Passed                                  Failed
            │                                     │
   Promoted to DEPLOYED                 PromotionGateFailedError
(Previous Champion -> MONITORING)             (Blocked)
            │
            ▼
      Inference Service
   (nexus_forecasts + Outbox)
            │
            ▼
   Observed Actual Value
  (nexus_observations)
            │
            ▼
    Closed Truth Loop
 (Residuals + Containment +
  Systematic Drift Flagging)
            │
            ▼
     Degraded? ──────────> Governed Rollback
                           (Restores Previous Champion)
```

---

## 2. Architecture & Design

### 2.1 State Machine & Immutability

1. **Version Immutability**:
   - Every registered model version `(tenant_id, workspace_id, name, version)` is unique and strictly immutable. Attempting to overwrite an existing version raises `DuplicateModelVersionError` (HTTP 409).
2. **Lifecycle State Machine**:
   ```text
   training ──> evaluating ──> shadow ──> calibrating ──> approved ──> deployed ──> monitoring ──> rolled_back
       │            │             │           │             │            │           │              │
       v            v             v           v             v            v           v              v
    archived     archived      archived    archived      archived     archived    archived       archived / shadow
   ```
   - Transitions strictly validated against `ALLOWED_MODEL_TRANSITIONS`.

### 2.2 Governed Promotion Gate (`PromotionGateValidator`)

Promotion requires explicit evaluation across multiple quality hurdles:
- **Accuracy Hurdle**: For demand forecasting, $WAPE \le 0.12$, $RMSE \le 50.0$. For risk/classification, $F_1 \ge 0.85$, $Accuracy \ge 0.85$.
- **Calibration Hurdle**: Empirical quantile coverage constraints:
  - $P_{50} \in [0.40, 0.60]$
  - $P_{80} \in [0.70, 0.90]$
  - $P_{95} \in [0.90, 0.99]$
- **Shadow Mode Hurdle**: Candidate error must not degrade current champion error by $> 5\%$.
- **Sample Count Hurdle**: Requires at least 10 validation samples.
- **Authorization Gate**: Only `operator` or `admin` principals can execute `nexus.model.promote`.

### 2.3 Real Probabilistic Inference & Provenance Tracking

- **Probabilistic Demand Forecaster (`ProbabilisticDemandForecaster`)**:
  - Implements seasonal decomposition, promotional elasticity, price elasticity, and volatility calibration.
  - Generates full quantile spreads ($P_{10}, P_{25}, P_{50}, P_{75}, P_{80}, P_{90}, P_{95}, P_{99}$, mean, std_dev, confidence).
  - Enforces strict monotonic ordering: $P_{10} \le P_{25} \le P_{50} \le P_{75} \le P_{80} \le P_{90} \le P_{95} \le P_{99}$.
- **GNN Graph Risk Scorer (`GNNRiskScorer`)**:
  - Multi-hop supply chain propagation risk, single-source vulnerability, and blast-radius revenue exposure.
- **Prediction Provenance**:
  - Each inference transaction writes to `nexus_forecasts` with `(forecast_id, model_id, model_version, feature_hash, world_state_version, confidence)`.
  - Emits `forecast.generated` to `nexus_events` via DB sequence authority.

### 2.4 Closed-Loop Truth & Drift Engine (`AuthoritativeTruthLoop`)

- Links realization observations in `nexus_observations` with prediction records.
- Computes residuals: $e = y - P_{50}$, $APE = \frac{|y - P_{50}|}{\max(1.0, y)}$, and quantile containment indicators ($I(y \le P_{80})$, $I(y \le P_{95})$).
- Continuous Drift Analysis:
  - Rolling WAPE and empirical coverage across SKU segments.
  - Systematic bias detection flagging under/over-predicting SKUs ($|MPE| > \text{bias\_threshold}$).

---

## 3. Database Schema & Migration 014

### `nexus_model_registry` (Authoritative)
- `model_id VARCHAR(64) PRIMARY KEY`
- `tenant_id VARCHAR(64) NOT NULL`
- `workspace_id VARCHAR(64) NOT NULL`
- `name VARCHAR(128) NOT NULL`
- `version VARCHAR(64) NOT NULL`
- `model_type VARCHAR(64) NOT NULL` (forecast, risk, gnn, rl, eta, sla)
- `metrics JSON NOT NULL`
- `calibration JSON NOT NULL`
- `status VARCHAR(40) NOT NULL` (training, evaluating, shadow, calibrating, approved, deployed, monitoring, rolled_back, archived)
- `approval_status VARCHAR(40) NOT NULL`
- `shadow_metrics JSON NULL`
- `promotion_gates JSON NULL`
- `deployed_at TIMESTAMPTZ NULL`
- `rolled_back_at TIMESTAMPTZ NULL`
- `rollback_reason TEXT NULL`
- `UNIQUE(tenant_id, workspace_id, name, version)`

### `nexus_forecasts` (Authoritative Provenance)
- `model_id VARCHAR(64) NULL`
- `confidence FLOAT NULL`
- `feature_hash VARCHAR(64) NULL`

---

## 4. Acceptance Test Matrix (M1–M15)

All 15 acceptance scenarios validated against PostgreSQL in `backend/tests/test_nexus_v084_ml_acceptance.py`:

| Test ID | Scenario Description | Result |
|---|---|---|
| **M1** | Immutable Model Registration & Versioning | **PASSED** |
| **M2** | Lifecycle State Machine Transitions & Validation | **PASSED** |
| **M3** | Promotion Gate — Metric Hurdle Rejection (WAPE/RMSE) | **PASSED** |
| **M4** | Promotion Gate — Calibration Coverage Hurdle Rejection | **PASSED** |
| **M5** | Governed Promotion Swap & Champion Demotion | **PASSED** |
| **M6** | Governed Rollback & Champion Restoration | **PASSED** |
| **M7** | Real Probabilistic Inference & Quantile Monotonicity | **PASSED** |
| **M8** | Prediction Provenance (Model ID, Feature Hash, World State Version) | **PASSED** |
| **M9** | Outbox Event Fabric Integration (`forecast.generated`, `model.promoted`) | **PASSED** |
| **M10** | Closed-Loop Truth Pairing & Quantile Containment | **PASSED** |
| **M11** | Systematic Bias & Model Drift Detection | **PASSED** |
| **M12** | Shadow Mode Comparison Recording | **PASSED** |
| **M13** | Tenant & Workspace Isolation | **PASSED** |
| **M14** | Role-Based AuthZ Security (Viewer vs Analyst vs Operator) | **PASSED** |
| **M15** | Multi-Worker Persistence & Restart Survival | **PASSED** |
| **HTTP** | Canonical REST API Lifecycle (Register, Promote, Infer, Drift, Rollback) | **PASSED** |
