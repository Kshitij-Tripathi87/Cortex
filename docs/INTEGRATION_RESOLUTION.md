# Cortex PR consolidation — integration record

Date: 2026-11-15
Integration branch: `integration/cortex-pr-consolidation-2026-11-15`
Target: `main`

## Conflict-resolution decisions

- Start from the then-current `main` snapshot and preserve its newer authentication, LLM adapter, canonical routes, safe SQLAlchemy metadata handling, CI configuration, Docker, frontend build and Kubernetes changes.
- Bring forward the non-overlapping Workflo package repair from PR #11; do not reintroduce obsolete root `product.workflo_*` imports.
- Bring forward the durable task runtime, Decision Room projection, billing gate and manufacturing planning foundation from PR #12. Integrate overlapping files with the current-main implementation rather than replacing them.
- Port row-level source evidence compilation and ingestion hardening from PR #13 while preserving the current authenticated/audited claim-review endpoints.
- PR #13's original migration `017_ingestion_file_digest` conflicts with the task-runtime migration `017_nexus_task_runtime`. Its digest change is therefore re-numbered as `022_ingestion_file_digest`, after `021_material_planning_runs`.
- PR #8's older mobile client is not included wholesale: its current diff contains placeholder identity/workspace values and in-memory token storage. It needs a separate mobile security review.
- PR #14's RC0 release changes are not considered release-qualified until staging acceptance, disaster-recovery rehearsal and rollback rehearsal are evidenced. Those requirements are recorded in the source PR and are not bypassed here.

## Migration order

`016_outbox_claim_lease` → `017_nexus_task_runtime` → `018_idempotency_key_width` → `019_audit_subject_id_width` → `020_p1_p2_operational_planning` → `021_material_planning_runs` → `022_ingestion_file_digest`.

## Validation required before merge

- Backend lint, format, typecheck and test suite on the exact integration head.
- Alembic upgrade rehearsal on PostgreSQL from the currently supported baseline through revision 022.
- PostgreSQL-backed tenant/RLS tests and planning API integration tests.
- Frontend lint, typecheck, test and production build.
- Security scan and release E2E.
- Staging customer journey, backup/restore and rollback evidence before activating RC0 production behavior.

No production deployment or customer data migration is part of this integration branch.
