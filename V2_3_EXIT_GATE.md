# V2.3 Governed Execution — Exit Gate / Freeze Record

**Date:** 2026-08-22
**Status:** ✅ FROZEN — **PASS WITH KNOWN BASELINE DEBT**
**Scope:** Execution as a separately governed capability boundary.
An agent proposal is **not** an authorization to execute. All authorization
verification is server-side, fail-closed, and independent of the operator UI.

> ⚠️ This milestone is NOT "all tests pass." The broader regression suite
> carries documented baseline debt (see §Known Baseline Debt). The V2.3
> surface itself is fully green. Debt owners/fix paths are tracked below —
> do **not** weaken those tests to get a green dashboard.

---

## 1. What V2.3 Establishes

### 1.1 The governed spine

```text
REAL DATA → WORLD STATE → OPERATIONAL INTELLIGENCE → SPECIALIST AGENTS
  → PROPOSAL (proposal_hash)
  → DIGITAL TWIN (simulation_hash)
  → POLICY GATE
  → HUMAN APPROVAL (approval_hash)
  → EXECUTION AUTHORIZATION (authorization_hash)   ← V2.3 boundary
  → [15+ checks]
  → EXECUTION
  → OUTCOME EVENT (outcome_hash)
  → WORLD STATE UPDATE
  → EVIDENCE CHAIN HASH
```

### 1.2 The fail-closed execution boundary

```text
Agent ──X──> Execution
               │
               ▼
       GovernedExecutionService        (server-side only)
               │
        ┌──────┴──────┐
     VERIFY         DENY
        │
        ▼
   AUTHORIZATION (authorization_hash)
        │
        ▼
     DISPATCH → OUTCOME (outcome_hash, full provenance chain)
```

`GovernedExecutionService.authorize_and_execute()`
(`app/modules/nexus_spine/governed_execution_service.py:50`) builds an
`ExecutionAuthorization`, computes `authorization_hash` over all verification
fields, runs `ExecutionAuthorization.verify()` — fail-closed on ANY failure —
then dispatches and records an `ExecutionOutcome` linking
`proposal_hash → simulation_hash → approval_hash → authorization_hash → outcome_hash`.

The frontend/operator UI has zero authority at this boundary.

---

## 2. Exit Gate Checklist

✅ = Implemented & Verified

### GE-1 Authorization checks are server-side and independent

- [x] All checks live in the backend execution service
      (`governed_execution_models.py:161` `verify()`), not in Next.js or
      the operator UI
- [x] Fail-closed: any missing/invalid field blocks execution and returns
      structured failure codes (`GovernedExecutionError` with `failures[]`)
- [x] The service is stateless; no approval state cached client-side

Verified check families (16):

| # | Check | Failure code |
|---|---|---|
| 1 | organization | `TENANT_MISSING` |
| 2 | workspace | `WORKSPACE_MISSING` |
| 3 | decision | `DECISION_ID_MISSING` |
| 4 | proposal hash | `PROPOSAL_HASH_MISSING` |
| 5 | simulation hash | `SIMULATION_HASH_MISSING` |
| 6 | world-state version | `WORLD_STATE_VERSION_INVALID` |
| 7 | world-state hash | `WORLD_STATE_HASH_MISSING` |
| 8 | policy decision | `POLICY_NOT_APPROVED` |
| 9 | policy version | `POLICY_VERSION_MISSING` |
| 10 | human approval (+approval hash) | `HUMAN_APPROVAL_MISSING` / `HUMAN_APPROVAL_DENIED` / `APPROVAL_HASH_MISSING` |
| 11 | approval expiry | `APPROVAL_EXPIRED` |
| 12 | agent identity | `AGENT_IDENTITY_MISSING` |
| 13 | agent capability (`EXECUTE`) | `AGENT_CAPABILITY_MISSING` / `CAPABILITY_MISSING` |
| 14 | execution budget | `EXECUTION_BUDGET_NEGATIVE` / `BUDGET_EXCEEDED` |
| 15 | evidence root | `EVIDENCE_ROOT_MISSING` |
| 16 | freshness/staleness | `STALE_DECISION` |

**Verification:** `TestExecutionAuthorization.verify_fails_on_*` (15 tests),
`TestGovernedExecutionService.denied_when_*` (9 tests)

### GE-2 Hash determinism across the spine

- [x] `authorization_hash`: SHA-256 over canonical JSON of all verification
      fields (`compute_authorization_hash`, `governed_execution_models.py:235`);
      deterministic; sensitive to every input field
- [x] `outcome_hash`: deterministic; provenance-linked to
      `proposal_hash/simulation_hash/approval_hash/authorization_hash`
      (`compute_outcome_hash`, `governed_execution_models.py:305` region)

**Verification:** `TestExecutionAuthorization.test_authorization_hash_determinism`,
`TestExecutionOutcome.test_outcome_hash_sensitivity`,
`TestGovernedExecutionService.test_outcome_hash_is_deterministic`

### GE-3 Outcome carries complete provenance

- [x] Every outcome records `world_state_version_before/after`,
      adapter result, idempotency key, and the full hash chain
- [x] Evidence-chain completion hash changes when any node is added or
      modified (tamper-evident lineage)

**Verification:** `TestExecutionOutcome` (4 tests), `TestEvidenceChainCompletion` (5 tests),
`TestSpineIntegration` (10 tests incl. `test_evidence_chain_hash_deterministic`)

### GE-4 Spine integration (orchestrator wiring)

- [x] `spine_orchestrator.py:62-68` imports the service; execution stage
      routes through `GovernedExecutionService` (`spine_orchestrator.py:705`)
- [x] Decision card exposes approval record + outcome data end-to-end

**Verification:** `TestSpineIntegration.test_all_v2_3_fields_consistent`,
`test_decision_card_includes_approval_record`,
`test_execution_stage_has_outcome_data`

### GE-5 Approval lifecycle semantics

- [x] `ApprovalRecord` produces stable `approval_hash`; deferral supported;
      hash sensitive to decision and proposal hash
- [x] Expired approvals deny execution (never silently re-approved)

**Verification:** `TestApprovalRecord` (6 tests),
`TestExecutionAuthorization.test_verify_fails_on_expired_approval`

---

## 3. Verified Test Evidence (2026-08-22, this machine)

| Suite | File | Result |
|---|---|---:|
| V1 Real Data Spine | `test_real_data_vertical_slice.py` | **62/62** ✅ |
| V2.1 Persistent World State | `test_v2_world_state_persistence.py` | **11/11** ✅ |
| V2.2 Proposal→Twin→Policy | `test_v2_proposal_twin_policy.py` | **42/42** ✅ |
| V2.3 Governed Execution | `test_v2_3_governed_execution.py` | **53/53** ✅ |
| **Combined relevant suites** | | **168/168** ✅ |
| Broader regression (`pytest tests/`) | | **1214 passed / 3 failed / 17 skipped** ⚠️ |

All counts above were executed and verified during the freeze review, not
carried forward from prior reports.

---

## 4. Known Baseline Debt (explicitly recorded — NOT part of V2.3)

**V2.3 status = PASS WITH KNOWN BASELINE DEBT.** Three failures exist in the
broader suite. None are in the V2.3 surface. They are recorded here so the
dashboard stays honest. **Do not weaken or delete these tests to go green.**

| # | Failing test | Root cause (verified) | Fix path | Owner |
|---|---|---|---|---|
| D-1 | `test_j3_3_kpi_engine.py::TestKPIReproducibility::test_different_seed_yields_different_kpi_hash` | Seed non-vacuousness broken: seeds 1 vs 999 produce identical KPI contract blocks ⇒ identical `kpi_hash`. The J.3.2 supplier-delay generator/runtime applies no seed-derived variance to any variable the J.3.3 KPI engine measures. | Fix engine semantics (preferred): make seed affect a measured variable in the scenario trajectory. Do **not** fold seed into the hash to mask it. | TBD — assign before V2.4 exit |
| D-2 | `test_j3_3_kpi_engine.py::TestKPIPersistence::test_run_stamps_kpi_hash_in_metadata` | `TwinService.run()` metadata stamps `kpi_hash/kpi_formula_version/kpi_canonical_engine_version/trajectory_hash` but omits `trajectory_ref_hash` (`twin_service.py:426-438`); `KPIComputation` already carries the value (`kpi_engine.py:114,326`). | One-line metadata stamp: `"trajectory_ref_hash": kpi.trajectory_ref_hash`. Mechanical; bundle with D-1. | TBD — assign before V2.4 exit |
| D-3 | `test_nexus_data_intelligence_platform.py::test_nexus_data_to_decision_orchestration` | Attribute name drift: `orchestrator.py:133` reads `GraphAnalyticsSummary.top_critical_sellers`; field is `top_critical_suppliers`. `AttributeError`. | Rename attribute access (or add alias if external consumers exist). Trivial. | TBD — assign before V2.4 exit |

**Reporting discrepancy note:** earlier reports cited "1190 passed, 1 failed"
and separately "two pre-existing KPI failures." Verified state at freeze time
is **1214 passed / 3 failed / 17 skipped**: the two J.3.3 KPI failures (D-1,
D-2) plus one orchestrator attribute bug (D-3). Recorded as-is.

---

## 5. Runtime Boundary Model (locked by this freeze)

Cortex's runtime is now treated as five hard boundaries:

```text
┌─────────────────────────────────────────────┐
│  1. DATA BOUNDARY                           │
│  Upload → Canonical Data → World State      │
├─────────────────────────────────────────────┤
│  2. REASONING BOUNDARY                      │
│  World State → Graph → Signals → Agents     │
├─────────────────────────────────────────────┤
│  3. SIMULATION BOUNDARY                     │
│  Agent Proposal → Digital Twin              │
├─────────────────────────────────────────────┤
│  4. GOVERNANCE BOUNDARY                     │
│  Twin → Policy → Human Approval             │
├─────────────────────────────────────────────┤
│  5. EXECUTION BOUNDARY          ← V2.3      │
│  Authorization → Capability → Execution     │
│                    ↓                        │
│              Outcome → World State          │
└─────────────────────────────────────────────┘
```

Cortex is a **data-first operational decision system with a governed agent
execution layer** — not "an AI agent platform."

---

## 6. What V2.3 Deliberately Does Not Include

- No real enterprise adapters (dispatch is a simulated internal adapter;
  production adapters are post-V2.5 work)
- No evidence-chain replay/query API (that is V2.4)
- No real specialist agent families (structurally correct agents only until V2.5)
- No frontend observation surface for the authorization ledger (frontend
  expansion frozen per roadmap)

---

## 7. Freeze Point

```text
J.2.3   World State              FROZEN
J.3.1   Twin Lifecycle           FROZEN
J.3.2   Scenario Runtime         FROZEN
V1      Real Data Spine          FROZEN
V2.1    Persistent World State   FROZEN
V2.2    Proposal → Twin → Policy FROZEN
V2.3    Governed Execution       FROZEN   ← this document
        │
        ▼
V2.4    Evidence → Outcome       NEXT     (see V2_4_PLAN.md)
        │
        ▼
V2.5    Real Specialist Agents
        │
        ▼
V2.6    Agent Tooling + Memory
        │
        ▼
V2.7    Adversarial Security
        │
        ▼
V2.8    Production Deployment
```

**Rule:** No cosmetic frontend expansion until V2.4/V2.5 has a genuinely
trustworthy backend contract. The frontend becomes the observation and control
surface for this runtime — not a separate product that simulates what the
backend is doing.
