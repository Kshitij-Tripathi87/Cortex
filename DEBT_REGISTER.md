# Cortex — Baseline Debt Register

**Last updated:** 2026-08-28 (post-hardening-checkpoint re-verification)
**Rule:** Debt items are tracked separately from milestone work. No debt item
may be silently fixed inside another milestone's changeset, and no test may be
weakened or deleted to make a dashboard green.

> **2026-08-28 re-verification:** D-1, D-2, D-3 below were each re-run against
> the post-checkpoint (`acdd197`) tree and **all three pass**. They are
> therefore marked RESOLVED — the entries below remain for audit history
> (root-cause + fix-path are preserved so the resolution is traceable).

---

## D-1 — J.3.3 KPI seed semantics (RESOLVED 2026-08-28)

| Field | Value |
|---|---|
| Failing test | `tests/test_j3_3_kpi_engine.py::TestKPIReproducibility::test_different_seed_yields_different_kpi_hash` |
| Original failure mode | Seeds 1 vs 999 produced identical 14-field KPI contract blocks ⇒ identical `kpi_hash` (`c2b0b002…` for both). Seed non-vacuousness was broken. |
| Original root cause | The J.3.2 `supplier_delay` scenario generator/runtime applied no seed-derived variance to any variable the J.3.3 KPI engine measured. |
| Why it was blocked | Fixing it meant making scenario trajectories seed-sensitive in measured variables — that touches frozen J.3.2/J.3.3 semantics. |
| Resolution | Re-run on `acdd197` → test passes. The seed now produces seed-dependent measured state. |
| Status | **RESOLVED** — verified passing in full suite (1519/0/20, 2026-08-28). |

## D-2 — J.3.3 KPI provenance stamp missing in twin metadata (RESOLVED 2026-08-28)

| Field | Value |
|---|---|
| Failing test | `tests/test_j3_3_kpi_engine.py::TestKPIPersistence::test_run_stamps_kpi_hash_in_metadata` |
| Original failure mode | `KeyError: 'trajectory_ref_hash'` — `TwinService.run()` metadata stamped `kpi_hash`, `kpi_formula_version`, `kpi_canonical_engine_version`, `trajectory_hash`, but not `trajectory_ref_hash`. |
| Original root cause | Omission at `app/modules/twin/twin_service.py` metadata dict. `KPIComputation` already carried the value. |
| Resolution | Re-run on `acdd197` → test passes. `trajectory_ref_hash` is now stamped in the metadata. |
| Status | **RESOLVED** — verified passing in full suite (1519/0/20, 2026-08-28). |

## D-3 — Orchestrator attribute name drift (RESOLVED 2026-08-28)

| Field | Value |
|---|---|
| Failing test | `tests/test_nexus_data_intelligence_platform.py::test_nexus_data_to_decision_orchestration` |
| Original failure mode | `AttributeError: 'GraphAnalyticsSummary' object has no attribute 'top_critical_sellers'. Did you mean: 'top_critical_suppliers'?` |
| Original root cause | `app/modules/data_intelligence/orchestrator.py:133` read `summary.top_critical_sellers`; the dataclass field was `top_critical_suppliers`. |
| Resolution | Re-run on `acdd197` → test passes. The attribute access now matches the canonical field name. Lands in the G1–G4 taxonomy-unification track (`5bc2b69`). |
| Status | **RESOLVED** — verified passing in full suite (1519/0/20, 2026-08-28). |

---

## New debt opened by the hardening checkpoint (2026-08-28)

The three baseline failures above were not the only ones. The Nexus production
hardening checkpoint (`acdd197`) brought in a fresh surface area (the F1–F4 /
H1–H2 / E1–E3 hardening track) which introduced three **new** failing tests
that are tracked under the production-hardening program (`NEXUS_PRODUCTION_HARDENING_PROGRAM.md`)
and were resolved in Steps 2–4:

| # | Test (resolved) | Surface |
|---|---|---|
| D-4 (resolved) | `test_nexus_enterprise_production_release.py::test_realtime_state_pipeline_end_to_end` | Redis latency regression in `state_pipeline` (cache.set blocking on dead Redis) |
| D-5 (resolved) | `test_production_qualification_load.py::test_load_state_pipeline_throughput` | Same root cause as D-4, load-test variant |
| D-6 (resolved) | `test_slo_catalog.py::test_slo_module_buckets_match_prometheus_histogram` | `prometheus_client` was missing from `pyproject.toml`, so `metrics.py` was a `_DummyMetric` |

**Remaining hardening-track debt** (not part of baseline; tracked in the
production-hardening phase ledger):

- **D3a–D3f (authz)** — 40 ungated routes identified by `ENDPOINT_AUTHZ_AUDIT.md`. The regression test `test_endpoint_authz_audit.py::TestAuthZGate::test_no_new_ungated_routes` prevents growth; the existing debt is paid down by Phase 12/15.
- **G4b (Digital Twin runtime)** — counterfactual simulations + shipment telemetry remain declared scenario inputs; the real Digital Twin runtime wiring is unwired. Phase 13.
- **Ruff 379 errors** (Step 6) — mostly `F401` unused imports + `I001` import order in the new hardening test files.
- **D3f specifically (realtime stats operator role)** — deferred to Step 7 (authz debt).

---

## Verification snapshot at registration (2026-08-22)

```text
Full suite (2026-08-22):   1271 passed / 3 failed / 17 skipped / 2 deselected
The 3 failures above were exactly D-1, D-2, D-3. No other failures.
Milestone gates:           V1 62/62 · V2.1 11/11 · V2.2 42/42 · V2.3 53/53 · V2.4 57/57
```

## Verification snapshot after hardening checkpoint (2026-08-28)

```text
Full suite (2026-08-28):   1519 passed / 0 failed / 20 skipped / 46 warnings (572 s)
Pre-Step-1 baseline (08-25):  1336 passed / 1 failed / 17 skipped / 2 deselected
The 1 failure (08-25) and 3 failures (08-22) were all D-1/D-2/D-3 — confirmed resolved.
Three additional failures (D-4/D-5/D-6 above) were introduced by the checkpoint
and resolved in Steps 2–4 of the hardening track. No tests weakened, no tests deleted.
Milestone gates:           V1 62/62 · V2.1 11/11 · V2.2 42/42 · V2.3 53/53 · V2.4 57/57
                           H2 23/23 (verified 2026-08-28)
                           F1 (SLO catalog) green · F2 (health) green · F3 (trace) green
                           F4 (security hardening) green · H1 (chaos) green
                           (full F1–F4/H1 counts to be confirmed in Step 9 review)
```

