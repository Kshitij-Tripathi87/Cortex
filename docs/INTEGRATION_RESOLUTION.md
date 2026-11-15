# Cortex PR consolidation — integration record

Date: 2026-11-15
Integration branch: `arena/a62d5cb3-cortex`, which continues `integration/cortex-pr-consolidation-2026-11-15` (PR #19)
Target: `main`

## Scope

All seven open pull requests land together.

| PR | Branch | How it is included |
| --- | --- | --- |
| #10 | `rc1/production-qualification` | ancestor of #19 |
| #11 | `rc1/production-qualification-2026-11-03` | ancestor of #19; its Next.js 15 dependency set was added afterwards |
| #12 | `feat/p1-p2-operational-foundation` | ancestor of #19 |
| #19 | `integration/cortex-pr-consolidation-2026-11-15` | base of the integration branch |
| #8 | `arena/nexus-v0.8.5-productization` | merge commit on top of #19 |
| #13 | `codex/priority-1-2-foundation-2026-11-04` | merge commit on top of #19 |
| #14 | `rc0-canonical-rewire` | merge commit on top of #19 |

Every PR head commit is an ancestor of the integration head. Merging the integration branch into `main` with a merge commit (not squash or rebase) therefore closes all seven.

## Conflict-resolution decisions

### Consolidation branch (PR #19, covering #10, #11 and #12)

- Start from the then-current `main` snapshot and preserve its newer authentication, LLM adapter, canonical routes, safe SQLAlchemy metadata handling, CI configuration, Docker, frontend build and Kubernetes changes.
- Bring forward the non-overlapping Workflo package repair from PR #11; do not reintroduce obsolete root `product.workflo_*` imports.
- Bring forward the durable task runtime, Decision Room projection, billing gate and manufacturing planning foundation from PR #12. Integrate overlapping files with the current-main implementation rather than replacing them.
- Port row-level source evidence compilation and ingestion hardening from PR #13 while preserving the current authenticated/audited claim-review endpoints.
- PR #13's original migration `017_ingestion_file_digest` conflicts with the task-runtime migration `017_nexus_task_runtime`. Its digest change is therefore re-numbered as `022_ingestion_file_digest`, after `021_material_planning_runs`.

### PR #8 — Device Mesh, mobile and voice

- All ten conflicting files keep the consolidation side: `api/v1/nexus_persistent.py`, `infrastructure/database.py`, `modules/audit/service.py`, `pyproject.toml` (no `<2.1` pin on SQLAlchemy), three Nexus and billing test files, `docker-compose.prod.yml` (SeaweedFS object storage), `frontend/Dockerfile` and `frontend/next.config.js`. The frontend lockfile merged without a conflict but into an inconsistent hybrid, so it also keeps the consolidation side.
- Added: the `/devices`, `/mobile` and `/voice` routers (mounted; every route depends on `get_current_user`), `app/modules/devices`, `app/modules/notifications`, `scripts/mobile_day25_drill.py` and the React Native client under `apps/mobile/`.
- PR #8's migration `020_device_mesh` collided with `020_p1_p2_operational_planning`. It is re-chained as `023_device_mesh`; the DDL is unchanged.
- The earlier version of this record held the mobile client back. It is now included because the instruction was to land every open PR. The review it called for is still open; see "Open items".

### PR #13 — deterministic material planning and ingestion tests

- `app/modules/ingestion/service.py` and `backend/pyproject.toml` keep the consolidation side, which already carried the hand-ported ingestion hardening. PR #13's `_parse_csv_from_tempfile` structural parser is added to it.
- `017_ingestion_file_digest.py` is dropped: `022_ingestion_file_digest` applies the same DDL.
- Added: `app/modules/supply_chain/planning.py`, `tests/test_ingestion_transactions.py`, `tests/test_material_planning.py` and the `priority-1-2-focused` CI job.

### PR #14 — RC0 canonical rewire

- Consolidation side kept for `api/v1/nexus_persistent.py`, `modules/compiler/service.py`, `ci.yml`, the SQLAlchemy requirement, `lib/auth/client.ts`, `DisruptionCockpit.tsx` and the `nexus/decision-room`, `evidence`, `upload` and root pages.
- PR #14's side taken for `config.py`, `agents_router.py`, `stress.yml`, the eleven `workflo_backend` files, the restored `tests/test_workflo.py` and `tests/test_workflo_api.py`, and the `agents/[id]` redirect.
- Applied without conflict: the frontend library rewire (`http.ts` delegates to the auth client; signals, graph, realtime, `WorkspaceContext`, `AskNexusBar`), removal of seven demo clients, `/nexus/cockpit` on `DisruptionCockpit`, and redirects for `/agents`, `/decisions`, `/graph`, `/mvp`, `/propagation`, `/recommendations`, `/scenarios` and `/signals`.
- The Workflo router is **not** mounted. `main` removed the mount in 8357310 and that decision is kept; `app/api/v1/router.py` documents how to re-enable it. The package and its tests remain in the tree.
- Six files under `frontend/src/app/` stay at their `main` version instead of PR #14's retirement redirects: `app/page.tsx`, `nexus/page.tsx`, `conflicts/page.tsx`, `readiness/page.tsx`, `audit/page.tsx` and `workspace/layout.tsx`. The release E2E specs assert those pages, `/app` holds the only logout and change-password UI, and the Decision Room at `/workspace/agents/decision-room` renders under that layout.
- PR #14's RC0 release changes are not release-qualified until staging acceptance, disaster-recovery rehearsal and rollback rehearsal are evidenced. Merging the code does not bypass those requirements.

### Frontend dependencies

The consolidation branch carried PR #11's audit gate, which accepts no high or critical production advisories, together with `main`'s Next 14.2.35 manifest. That combination failed the gate. `frontend/package.json` and `frontend/package-lock.json` are taken from PR #11: Next 15.5.28, `eslint-config-next` 15.5.28, PostCSS 8.5.32 with overrides for `postcss` and `source-map-js`.

### CI workflows

- `workflo-cli.yml` now triggers only on changes under `workflo-cli/`. Its push filter also matched `backend/app/api/v1/workflo.py`, which this integration restores, so the merge would have started that gate on `main` for the first time. The gate builds a CLI package in `workflo-cli/`, which is not in the tree, and every step runs from that directory, so it would have failed before testing anything.
- `ci.yml` gains PR #13's `priority-1-2-focused` job, `nexus-staging-verify.yml` is new on `main`, and `stress.yml` changes in comments only. No other gate is removed or relaxed.

## Migration order

`016_outbox_claim_lease` → `017_nexus_task_runtime` → `018_idempotency_key_width` → `019_audit_subject_id_width` → `020_p1_p2_operational_planning` → `021_material_planning_runs` → `022_ingestion_file_digest` → `023_device_mesh`.

The chain has a single head. Two revision identifiers that existed only on PR branches are gone, so a database that was migrated from one of those branches must be re-pointed before `alembic upgrade head`. A plain `alembic stamp` fails on the unknown revision; `--purge` is required. Both paths were rehearsed on PostgreSQL 16 against a database built from the PR branch.

| Database was migrated from | It records | Re-point with |
| --- | --- | --- |
| PR #8 (`arena/nexus-v0.8.5-productization`) | `020_device_mesh` | `alembic stamp --purge 019_audit_subject_id_width` |
| PR #13 (`codex/priority-1-2-foundation-2026-11-04`) | `017_ingestion_file_digest` | `alembic stamp --purge 016_outbox_claim_lease` |

Migrations 022 and 023 create only what is missing, so the objects such a database already has are left in place.

## Defects found and fixed during integration

- **CSV ingestion never completed.** `_apply_ingestion_rows` called `session.begin_nested()` without awaiting it, so finalising any import raised `AsyncContextNotStarted`. Present in PR #13 and in the hand-port on the consolidation branch.
- **`ci.yml` was invalid YAML on PR #13.** An unquoted `sqlite+aiosqlite:///:memory:` value ends in a colon and parsed as a mapping key, so none of the `ci.yml` jobs ran on that PR.
- **Six structural CSV parser tests could not pass.** Their payloads were double-escaped.
- **Audit events failed on SQLite.** `audit.emit()` resolved the tenant from `core.organizations` and wrote the RLS session GUCs on every dialect. Both steps now run on PostgreSQL only; the PostgreSQL path is unchanged.
- **Every readiness computation raised `TypeError`.** The row-level compiler rewrite dropped `ReadinessResult.explanation`, which broke batch compile, the readiness endpoint and the graph publish check.
- **Brief generation failed for scenarios with an affected warehouse.** Migration 020 changed inventory quantity and safety stock to `NUMERIC(18, 4)`, and the disruption engines multiply those values by floats. The brief adapter now converts to whole units; a fractional remainder is dropped.
- **Two retry-idempotency tests used the previous `extract_claims()` signature.** They now pass the parsed rows. Their assertions are unchanged.
- `mypy app` reported 27 errors and `ruff format --check .` rejected 16 files. Both are clean, with no new typing-ratchet override.
- The committed OpenAPI schema and TypeScript types were stale. They are regenerated: 190 paths, including the device, mobile, voice, planning, task-runtime and claim-review routes, and without the unmounted `/workflo` routes.

## Implementation completed on the integration branch

- Durable task endpoints and Decision Room projection are integrated while the current LLM-backed Vanessa route remains authoritative.
- Planning API routing and task/manufacturing ORM registration are included.
- Source evidence compilation records row-level locators and SHA-256 provenance. Conflict detection requires a resolved canonical entity, field and entity key.
- CSV ingestion enforces UTF-8, strict quoting, unique non-blank headers and exact row width. Per-row savepoints isolate partial failures; strict mode rolls back all entity rows. Error logs do not store uploaded row values.
- Uploaded ingestion artifacts record SHA-256 using migration 022.
- The Alembic environment imports both task-runtime and manufacturing ORM models.
- Device Mesh, mobile bootstrap and provider-agnostic voice sessions are served from the canonical API and migrated by 023.

## Validation on the integration head

Run locally before the pull request was opened, on Python 3.11 and Node 22 (CI uses Python 3.12 and Node 20).

| Gate | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | pass |
| `mypy app` | no issues in 537 source files |
| `app.deferred` import tripwire, `scripts/check_budgets.py` | pass |
| `alembic upgrade head` on an empty PostgreSQL 16 database | pass, through `023_device_mesh` |
| `pytest tests/` with PostgreSQL and Redis (`ci.yml`) | 2194 passed, 1 skipped |
| `pytest tests/` with PostgreSQL, no Redis (`test.yml`) | 2193 passed, 2 skipped |
| `pytest` with no services (`nexus-staging-verify.yml`) | 2119 passed, 76 skipped |
| `priority-1-2-focused` job commands | pass, 39 tests |
| `pip-audit` on the resolved dependency set | no known vulnerabilities |
| Frontend typecheck, lint, unit tests | pass, 34 tests |
| Frontend production build on Next 15.5.28 | pass |
| `node scripts/audit-gate.mjs` | pass, one moderate advisory reported |
| Playwright release specs (`critical-path`, `auth`, `realtime`) against a local stack | 30 passed |

Docker image builds, Compose validation, the secrets scan and the object-storage-backed paths can only run in CI.

## Open items

These are not resolved by this integration.

- **Mobile client security review.** `apps/mobile/App.tsx` keeps tokens in an in-memory map and uses placeholder identity values (an empty workspace id, a fixed `phone-001` device id). It needs secure on-device storage and real identity wiring before it is distributed.
- **RC0 release qualification.** Staging customer journey, backup/restore and rollback evidence are still required before RC0 production behaviour is activated.
- **Workflo API.** Unmounted by decision; re-enabling it is a product decision.
- **Legacy page retirement.** The six pages listed under PR #14 can be retired once the E2E specs and the logout and change-password UI move to the canonical routes.
- **Workflo CLI gate.** When the `workflo-cli/` package lands, add the backend Workflo paths back to the trigger filters in `workflo-cli.yml`.
- **`openapi-types` CI gate.** The job runs `git diff --exit-code` from `backend/` with paths relative to the repository root, so it matches no files and cannot fail. The artifacts had drifted on `main` for that reason.

No production deployment or customer data migration is part of this integration branch.
