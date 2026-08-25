# Cortex — Baseline Debt Register

**Last updated:** 2026-08-22
**Rule:** Debt items are tracked separately from milestone work. No debt item
may be silently fixed inside another milestone's changeset, and no test may be
weakened or deleted to make a dashboard green.

---

## D-1 — J.3.3 KPI seed semantics (BLOCKED on design decision)

| Field | Value |
|---|---|
| Failing test | `tests/test_j3_3_kpi_engine.py::TestKPIReproducibility::test_different_seed_yields_different_kpi_hash` |
| Failure mode | Seeds 1 vs 999 produce identical 14-field KPI contract blocks ⇒ identical `kpi_hash` (`c2b0b002…` for both). Seed non-vacuousness is broken. |
| Root cause | The J.3.2 `supplier_delay` scenario generator/runtime applies no seed-derived variance to any variable the J.3.3 KPI engine measures. |
| Why blocked | Fixing it means making scenario trajectories seed-sensitive in measured variables — that touches **frozen J.3.2/J.3.3 semantics**. Requires its own design decision + regression suite per the V2.3 freeze rule. Do NOT fold seed into the hash to mask it; do NOT quietly alter Twin behavior as "cleanup". |
| Treatment | Separate debt project: ADR for where seed variance enters the measured state, then engine fix, then unblock this test. |
| Owner | TBD |
| Status | OPEN — not a blocker for V2.4 |

## D-2 — J.3.3 KPI provenance stamp missing in twin metadata

| Field | Value |
|---|---|
| Failing test | `tests/test_j3_3_kpi_engine.py::TestKPIPersistence::test_run_stamps_kpi_hash_in_metadata` |
| Failure mode | `KeyError: 'trajectory_ref_hash'` — `TwinService.run()` metadata stamps `kpi_hash`, `kpi_formula_version`, `kpi_canonical_engine_version`, `trajectory_hash`, but not `trajectory_ref_hash`. |
| Root cause | Omission at `app/modules/twin/twin_service.py` metadata dict (~line 426–438). `KPIComputation` already carries the value (`kpi_engine.py:114`, set at `:326`). |
| Fix path | One-line metadata stamp: `"trajectory_ref_hash": kpi.trajectory_ref_hash`. Mechanical maintenance fix. |
| Constraint | Touches `twin_service.py` which sits under frozen J.3.x surfaces — bundle review with D-1's project OR do as an isolated, explicitly-labeled maintenance commit. Not during V2.4. |
| Owner | TBD |
| Status | OPEN — not a blocker for V2.4 |

## D-3 — Orchestrator attribute name drift

| Field | Value |
|---|---|
| Failing test | `tests/test_nexus_data_intelligence_platform.py::test_nexus_data_to_decision_orchestration` |
| Failure mode | `AttributeError: 'GraphAnalyticsSummary' object has no attribute 'top_critical_sellers'. Did you mean: 'top_critical_suppliers'?` |
| Root cause | `app/modules/data_intelligence/orchestrator.py:133` reads `summary.top_critical_sellers`; the dataclass field is `top_critical_suppliers`. |
| Fix path | Rename the attribute access (or add a compatibility alias if external consumers exist). Small, isolated bug fix. |
| Constraint | Keep the correction isolated from V2.4 so provenance work stays easy to audit. |
| Owner | TBD |
| Status | OPEN — not a blocker for V2.4 |

---

## Verification snapshot at registration

```text
Full suite (2026-08-22):   1271 passed / 3 failed / 17 skipped / 2 deselected
The 3 failures above are exactly D-1, D-2, D-3. No other failures.
Milestone gates:           V1 62/62 · V2.1 11/11 · V2.2 42/42 · V2.3 53/53 · V2.4 57/57
```
