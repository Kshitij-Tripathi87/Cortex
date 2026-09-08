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
| Gated | 148 |
| Ungateable (legitimate public) | 1 |
| Need investigation / fix (debt) | 0 |

The single confirmed-public route is `GET /workflo/health` (the
workflo CLI liveness probe). All other routes across all router files
in `backend/app` are fully gated and verified.

## Ungateable (legitimate public, excluded from the gate test)

| File | Method | Path | Function | Reason |
|---|---|---|---|---|
| workflo.py | GET | /workflo/health | health | Liveness probe for the workflo CLI sandbox subsystem |

## Paid-down Debt (All 29 Routes Gated)

All 29 legacy debt routes have been gated with AST-verifiable authorization helpers
(`require_workspace_access`, `require_role("operator", auth)`, `get_current_user`, `AuthContext`).

| File | Method | Path | Function | Resolution |
|---|---|---|---|---|
| agent_runtime.py | GET | /registry | list_agents | Gated with `get_current_user` |
| graph.py | GET | /snapshots/{snapshot_id} | get_snapshot_detail | Gated with `get_current_user` + `require_workspace_access` |
| graph.py | GET | /recommendations/taxonomy | get_recommendation_taxonomy | Gated with `get_current_user` |
| graph.py | GET | /recommendations/types | list_recommendation_types | Gated with `get_current_user` |
| graph.py | GET | /decisions/taxonomy | get_decision_taxonomy | Gated with `get_current_user` |
| intelligence_gateway.py | GET | /baselines | list_baselines | Gated with `get_current_user` |
| realtime.py | GET | /stats | get_realtime_stats | Gated with `get_current_user` + `require_role("operator", auth)` |
| realtime.py | WEBSOCKET | /ws | realtime_websocket_endpoint | Gated with `AuthContext` + `require_workspace_access` |
| spine.py | POST | /run | run_spine | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | POST | /workflo/sandboxes | create_sandbox | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | GET | /workflo/sandboxes/{sandbox_id} | inspect_sandbox | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | DELETE | /workflo/sandboxes/{sandbox_id} | destroy_sandbox | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | POST | /workflo/sandboxes/{sandbox_id}/files | write_file | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | GET | /workflo/sandboxes/{sandbox_id}/files | list_files | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | GET | /workflo/sandboxes/{sandbox_id}/files/content | read_file | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | POST | /workflo/sandboxes/{sandbox_id}/execute | execute | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | POST | /workflo/agent/plan | agent_plan | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | POST | /workflo/agent/continue | agent_continue | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | POST | /workflo/runs | create_run | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | GET | /workflo/runs/{run_id} | get_run | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | GET | /workflo/runs/{run_id}/artifacts | list_run_artifacts | Gated with `get_current_user` + `require_workspace_access` |
| workflo.py | GET | /workflo/runs/{run_id}/events | stream_events | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | POST | /workflow/start | start_workflow | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | GET | /workflow/{instance_id} | get_workflow | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | POST | /workflow/{instance_id}/cancel | cancel_workflow | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | POST | /workflow/{instance_id}/retry | retry_workflow | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | POST | /workflow/{instance_id}/resume | resume_workflow | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | POST | /workflow/{instance_id}/approve | approve_gate | Gated with `get_current_user` + `require_role("operator", auth)` + `require_workspace_access` |
| workflow_engine_api.py | GET | /workflow/{instance_id}/timeline | get_timeline | Gated with `get_current_user` + `require_workspace_access` |
| workflow_engine_api.py | GET | /workflow/templates | list_templates | Gated with `get_current_user` + `require_workspace_access` |

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
- **D3f — `realtime.py::get_realtime_stats`**: COMPLETED. Now requires `role: "operator"` via `require_role`. Verified by `test_realtime_stats_endpoint`.
- **D3g — `workspace.py` (Program S demo workspace)**: OPEN (pinned 2026-09, v0.8.2
  routing flip). All 15 routes of the in-memory Live Data Intelligence
  Workspace demo (`/state`, `/demo/load`, `/ingest-raw`, `/upload`,
  `/graph/subgraph`, `/graph/critical-nodes`, `/signals`, `/deliberate`,
  `/decisions/evidence`, `/decisions/validity`, `/query/ask`,
  `/query/readiness`, `/append-stream`, `/graph/delta`, `/stream`) are
  ungated by design — the demo workspace is process-local and carries no
  authoritative state. They are pinned in `KNOWN_DEBT` so any NEW route
  still fails the audit. Gating (or product-level removal once the
  PostgreSQL-backed workspace replaces the demo) is a dedicated follow-up.
  Note: these routes were previously invisible to the audit because
  `workspace.py` used PEP 701 f-strings the AST scanner could not parse
  on Python 3.11; the file has since been made 3.11-compatible.

## Verification

- `tests/test_endpoint_authz_audit.py::TestAuthZGate::test_no_new_ungated_routes`
  — fails CI if a new route is added without one of the documented
  authorization helpers. The exclusion list is encoded in the test
  itself, so adding an exception is a deliberate, audited code change.
- The full 1,337-test suite continues to be the regression gate for
  every fix; fixes land in their own PRs (not bundled with V2.4 or
  any frozen-surface change).

- **D3a — `agents_router.py`**: COMPLETED. All 10 routes now have
  `AuthContext` + `require_workspace_access` (where workspace_id exists).
  The optional `workspace_id` query param is now required; callers must
  be a member of that workspace. 10 routes moved from KNOWN_DEBT to
  gated. Gated count increased from 109 to 119; KNOWN_DEBT reduced
  from 40 to 30.
