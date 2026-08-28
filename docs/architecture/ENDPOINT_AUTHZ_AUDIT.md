# Endpoint Authorization Audit — D3 (Production-Gate Item)

**Owner:** Backend
**Generated:** 2026-08-28
**Scope:** every `@router.{get,post,put,patch,delete,websocket}` in `backend/app/**`
**Phase:** Nexus Production Hardening D3

## What this audit covers

For every route handler in the backend, the audit checks whether the
handler enforces an authorization check. The contract: a route is
**gated** if its function body references one of
`require_workspace_access`, `require_auth`, `require_role`,
`get_current_user`, `get_current_principal`, `get_workspace_auth`, or
`AuthContext`. Anything else is **ungated**.

A route may be legitimately ungated only if it is one of the documented
public surfaces: `/healthz`, `/readyz`, `/metrics`, the `/workflo/health`
liveness probe, or other infrastructure-level routes that explicitly
document their public status. A read-only taxonomy or list endpoint is
NOT automatically public — workspace context still matters for any
endpoint that touches tenant data.

## Summary

| Metric | Count |
|---|---|
| Total routes | 150 |
| Gated | 109 |
| Ungateable (legitimate public) | 1 |
| Need investigation / fix | 40 |

The single confirmed-public route is `GET /workflo/health` (the
workflo CLI liveness probe). All other 40 routes are listed below.

## Ungateable (legitimate public, excluded from the gate test)

| File | Method | Path | Function | Reason |
|---|---|---|---|---|
| workflo.py | GET | /workflo/health | health | Liveness probe for the workflo CLI sandbox subsystem |

## Needs investigation

These 40 routes do not currently call an authorization helper. Per
"no silent fixes to frozen surfaces" and the V2.3 freeze rule, the
fixes are deferred to dedicated change sets. The regression test
`tests/test_endpoint_authz_audit.py::TestAuthZGate::test_no_new_ungated_routes`
fails CI if a new route is added without a gate, so the debt cannot
grow — it can only be paid down.

| File | Method | Path | Function | Risk |
|---|---|---|---|---|
| agent_runtime.py | GET | /registry | list_agents | Cross-workspace data leak |
| agents_router.py | GET | /fleet | get_agent_fleet | Workspace ID is optional, not enforced |
| agents_router.py | POST | /train | train_agent | Mutating; any caller can launch training |
| agents_router.py | POST | /evaluate | evaluate_agent | Mutating; any caller can run eval |
| agents_router.py | POST | /deploy | deploy_agent_replicas | Mutating; deployment is auth-critical |
| agents_router.py | POST | /canary | configure_canary | Mutating; canary routing is auth-critical |
| agents_router.py | POST | /supervise | run_supervision_cycle | Mutating |
| agents_router.py | POST | /inject-degradation | inject_simulated_degradation | Chaos; must be admin-only |
| agents_router.py | POST | /tasks | create_and_execute_task | Mutating |
| agents_router.py | GET | /tasks/{task_id} | get_task_graph | Reads task graph |
| agents_router.py | GET | /manifests | get_agent_capability_manifests | Capability manifest leak |
| graph.py | GET | /snapshots/{snapshot_id} | get_snapshot_detail | Snapshot content |
| graph.py | GET | /recommendations/taxonomy | get_recommendation_taxonomy | Closed taxonomy, not tenant-scoped |
| graph.py | GET | /recommendations/types | list_recommendation_types | Closed taxonomy |
| graph.py | GET | /decisions/taxonomy | get_decision_taxonomy | Closed taxonomy |
| intelligence_gateway.py | GET | /baselines | list_baselines | Operational config |
| realtime.py | WEBSOCKET | /ws | realtime_websocket_endpoint | WS auth; token must be checked in handshake |
| realtime.py | GET | /stats | get_realtime_stats | Operational stats |
| spine.py | POST | /run | run_spine | Mutating; uploads files |
| workflo.py | POST | /workflo/sandboxes | create_sandbox | Creates user-owned sandbox |
| workflo.py | GET | /workflo/sandboxes/{sandbox_id} | inspect_sandbox | Reads sandbox |
| workflo.py | DELETE | /workflo/sandboxes/{sandbox_id} | destroy_sandbox | Mutating |
| workflo.py | POST | /workflo/sandboxes/{sandbox_id}/files | write_file | Mutating |
| workflo.py | GET | /workflo/sandboxes/{sandbox_id}/files | list_files | Reads sandbox files |
| workflo.py | GET | /workflo/sandboxes/{sandbox_id}/files/content | read_file | Reads sandbox files |
| workflo.py | POST | /workflo/sandboxes/{sandbox_id}/execute | execute | Mutating; code execution |
| workflo.py | POST | /workflo/agent/plan | agent_plan | Mutating; agent plans code execution |
| workflo.py | POST | /workflo/agent/continue | agent_continue | Mutating; agent plans code execution |
| workflo.py | POST | /workflo/runs | create_run | Mutating |
| workflo.py | GET | /workflo/runs/{run_id} | get_run | Reads run state |
| workflo.py | GET | /workflo/runs/{run_id}/artifacts | list_run_artifacts | Reads run artifacts |
| workflo.py | GET | /workflo/runs/{run_id}/events | stream_events | Reads run events |
| workflow_engine_api.py | POST | /workflow/start | start_workflow | Mutating; workflow creation |
| workflow_engine_api.py | GET | /workflow/{instance_id} | get_workflow | Reads workflow state |
| workflow_engine_api.py | POST | /workflow/{instance_id}/cancel | cancel_workflow | Mutating |
| workflow_engine_api.py | POST | /workflow/{instance_id}/retry | retry_workflow | Mutating |
| workflow_engine_api.py | POST | /workflow/{instance_id}/resume | resume_workflow | Mutating |
| workflow_engine_api.py | POST | /workflow/{instance_id}/approve | approve_gate | Mutating; gates production actions |
| workflow_engine_api.py | GET | /workflow/{instance_id}/timeline | get_timeline | Reads workflow timeline |
| workflow_engine_api.py | GET | /workflow/templates | list_templates | Reads templates |

## Triage notes

- **`agents_router.py`** is the highest-risk cluster: every route is
  auth-critical (training, deployment, canary, supervision, chaos) but
  the entire file has no `AuthContext` / `require_workspace_access` at
  all. This is the first cluster to fix in D3 follow-up.
- **`workflow_engine_api.py`** includes `POST /workflow/{instance_id}/approve`,
  which is the only production-gate approval surface. It MUST be
  auth-gated before any pilot (I1).
- **`workflo.py`** operates on per-user sandboxes, so the natural gate
  is "the caller can only see their own sandboxes/runs", enforced by
  matching `caller_user_id` against the sandbox owner. This is a
  different pattern from `require_workspace_access` and may need a
  dedicated helper.
- **`realtime.py::realtime_websocket_endpoint`** auths at WS handshake
  time (token in query string) — the audit cannot detect this from
  function body alone. The follow-up must verify the handshake does
  call `verify_token` before accepting the connection.
- **Closed taxonomies** (`get_recommendation_taxonomy`, `list_recommendation_types`,
  `get_decision_taxonomy`) are legitimately tenant-neutral. They
  should be moved to a public surface explicitly.

## Required follow-ups (Phase 2 → Phase 15)

- **D3a — `agents_router.py`**: add `AuthContext` + `require_workspace_access`
  to all 10 routes. The optional `workspace_id` query param must
  become required, and the caller must be a member of that workspace.
- **D3b — `workflow_engine_api.py`**: add `AuthContext` to all 8 routes;
  `/approve` must additionally require `role: "operator"` or higher.
- **D3c — `workflo.py`**: add a per-sandbox owner check; `create_sandbox`
  must record the `caller_user_id`; reads must filter by owner.
- **D3d — `realtime.py` WS handshake**: verify the bearer token at
  handshake time; reject with 401 if missing or invalid.
- **D3e — Closed taxonomies**: either move to `/v1/public/taxonomies/*`
  with explicit public marker, or add a lightweight `AuthContext`
  that just confirms the request is authenticated (no workspace check).
- **D3f — `realtime.py::get_realtime_stats`**: this returns
  `active_connections`; treat as operational, require `role: "operator"`.

## Verification

- `tests/test_endpoint_authz_audit.py::TestAuthZGate::test_no_new_ungated_routes`
  — fails CI if a new route is added without one of the documented
  authorization helpers. The exclusion list is encoded in the test
  itself, so adding an exception is a deliberate, audited code change.
- The full 1,337-test suite continues to be the regression gate for
  every fix; fixes land in their own PRs (not bundled with V2.4 or
  any frozen-surface change).
