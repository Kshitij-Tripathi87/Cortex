# Release Candidate 0 — Canonical Cortex

**Scope:** one authenticated supplier-disruption decision journey  
**Release rule:** this gate must pass on fresh workspace data without demo fixtures or manual database repair.

## Customer journey

1. Create an organization and workspace.
2. Authenticate and establish the server-owned workspace context.
3. Upload the supported supplier-disruption data contract.
4. Validate schema, provenance, conflicts, idempotency, and readiness.
5. Build or update the authoritative World State and operational graph.
6. Inspect persisted risks/signals and their evidence.
7. Open a Decision Room and inspect decision, evidence, approval, and scenario records.
8. Compare isolated scenarios without mutating production state.
9. Approve or reject through server-side authorization and record the actor.
10. Reconstruct the Decision Receipt from durable records.

## Required evidence

| Area | Required evidence | Command or artifact |
| --- | --- | --- |
| Backend import/startup | Application imports after the root `product/` removal | `python -c "from app.main import app"` |
| Backend quality | Full backend tests, lint, formatting, and typecheck | `pytest tests/`, `ruff`, `mypy` |
| Frontend quality | Typecheck, lint, unit tests, and production build | `npm run typecheck`, `npm run lint`, `npm run test`, `npm run build` |
| Auth/tenancy | Negative cross-workspace and unauthorized-action tests | backend auth/workspace suites |
| Data | Fresh upload → validation → readiness → World State/graph | RC0 integration test with the eight-file contract |
| Decision | Risk → evidence → scenario → decision lifecycle | canonical `/nexus/*` API test |
| Receipt | Source, state, calculation, policy, approval, execution, and outcome references | Decision Room/trace reconstruction test |
| Recovery | Interrupted work resumes without duplicate consequential action | worker restart/retry test |
| Deployment | Staging smoke, migration, restore, and rollback records | staging runbook artifacts |

## Release thresholds

- No customer-facing canonical route loads demo data.
- No customer-facing canonical mutation silently succeeds after an API failure.
- Repeated ingestion is idempotent and does not duplicate canonical state.
- Every consequential recommendation has inspectable source or derivation references.
- Scenario execution cannot mutate production World State.
- Unauthorized cross-tenant reads and actions are denied and auditable.
- Interrupted tasks resume without duplicate consequential actions.
- Historical partner backtests meet the agreed threshold; the initial reference target is `0.8`.
- A design-partner operator can complete the journey without engineering intervention.

## Current implementation status

- Frontend canonical cockpit, authenticated upload, workspace-derived tenancy, calibration view, and Decision Room are implemented locally.
- Frontend checks currently pass: typecheck, lint, 14 Vitest tests, and production build.
- The backend Workflo package/import repair is implemented locally but backend verification is blocked in this worker because the available Python installation has no standard library/dependencies and Docker is unavailable.
- GitHub `main` remains at `15edf97`; the referenced stress run is failed. Local changes are not considered remotely verified until a branch/PR runs the backend and staging gates.
