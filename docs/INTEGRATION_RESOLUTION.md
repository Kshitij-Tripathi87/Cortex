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
- Six files under `frontend/src/app/` stay at their `main` version instead of PR #14's retirement redirects: `app/page.tsx`, `nexus/page.tsx`, `conflicts/page.tsx`, `readiness/page.tsx`, `audit/page.tsx` and `workspace/layout.tsx`. The release E2E specs assert those pages, `/app` holds the only logout and change-password UI, and the Decision Room at `/workspace/agents/decision-room` renders under that layout. Follow-up: `nexus/page.tsx`, `conflicts/page.tsx` and `readiness/page.tsx` have since been retired (see "Follow-up fixes" below).
  - Update 2026-11-18: `workspace/layout.tsx` and the rest of `frontend/src/app/workspace/` have since been removed. The area only showed built-in sample data; its addresses now redirect to `/nexus/cockpit` (task review to `/nexus/decision-room/task`), which is the outcome PR #14's redirect intended.
- PR #14's RC0 release changes are not release-qualified until staging acceptance, disaster-recovery rehearsal and rollback rehearsal are evidenced. Merging the code does not bypass those requirements.

### Frontend dependencies

The consolidation branch carried PR #11's audit gate, which accepts no high or critical production advisories, together with `main`'s Next 14.2.35 manifest. That combination failed the gate. `frontend/package.json` and `frontend/package-lock.json` are taken from PR #11: Next 15.5.28, `eslint-config-next` 15.5.28, PostCSS 8.5.32 with overrides for `postcss` and `source-map-js`.

- Update 2026-11-18: the gate failed on `main` (10 entries), all from one
  advisory against `picomatch` (GHSA-fc5q-39xc-vjpf) for which no fixed
  release exists. It was reached only through Tailwind, which was listed
  under `dependencies` together with PostCSS and Autoprefixer although all
  three only compile the style sheet during `next build`. The image
  (`.next/standalone`, 17 packages, checked) holds neither Tailwind nor
  Autoprefixer; it does hold PostCSS, but as a dependency of Next itself, at
  the patched 8.5.32 the existing override pins. They are now
  `devDependencies`, and the production gate reports nothing. Because the
  `docker` job of `ci.yml` needs the `security` job, no image could be built
  on `main` while the gate failed.
  - Vitest went from 2.1.9 to 4.1.12, which removes two critical advisories
    (Vitest, Tinypool) and those against Vite 5 and esbuild. Vite is held at
    7.x by an override: with Vite 8 in the tree, npm 10 fails on its optional
    developer-tools peer with `Cannot read properties of null (reading
    'edgesOut')`. `npm audit fix` and one in-range update cleared the rest.
    Before: 2 critical, 18 high, 9 moderate. After: the `picomatch` advisory
    alone, in build, lint and test tools.
  - `node scripts/audit-gate.mjs` checks production dependencies and fails on
    high or critical; `--tools` checks every dependency and fails on
    critical. An audit the registry does not answer fails after three
    attempts instead of passing. `scripts/audit-gate.test.ts` covers these
    decisions. The `dependencies` job of `security.yml`, whose two audits
    ended in `|| true`, now runs the same gates, weekly as well.

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

## Follow-up fixes

Found on the merged build and fixed after the integration. All three defects predate it: `main` had them before the merge.

- **Source upload returned HTTP 500 on PostgreSQL.** Eight timestamp columns in `modules/sources/models.py`, `modules/compiler/models.py` and `modules/events/integration_events.py` were declared as bare `Mapped[datetime]`. SQLAlchemy binds such a column as `TIMESTAMP WITHOUT TIME ZONE`, while the migrations create `TIMESTAMP WITH TIME ZONE` and the application writes timezone-aware values, so asyncpg rejected every insert on the intake path: upload, claim extraction, conflict detection, conflict resolution and readiness. The columns now declare `DateTime(timezone=True)`. No migration is needed.
- **Readiness could be stored only once per database.** `POST /api/v1/readiness/batches/{batch_id}` saved every assessment under the primary key `"temp"`. The evidence page requests an assessment on each load, so the second request failed with a duplicate key. The fixed key is removed and the model default generates one.
- **Legacy pages that called missing APIs.** `/nexus` requested the `/api/v1/workspace/*` demo API, which is mounted only when `CORTEX_WORKSPACE_DEMO_ROUTES` is set (off by default). `/conflicts` and `/readiness` requested `GET /api/v1/conflicts` and `GET /api/v1/readiness`, which do not exist. The three pages now carry PR #14's redirects: `/nexus` to `/nexus/cockpit`, the other two to `/upload`.
- **Coverage.** Before this, no test stored an upload: the backend intake tests ran on SQLite, which accepts the values, and none of them called the upload; the browser test only opened the form. Added `tests/test_timestamp_columns_timezone_aware.py` (every ORM timestamp column is timezone-aware; needs no database), `tests/test_source_intake_postgres.py` (upload, prepare, review, conflicts and readiness over HTTP on real PostgreSQL), `tests/test_readiness_api.py`, and a browser test in `frontend/tests/critical-path-e2e.spec.ts` that uploads a file, prepares its claims and reloads the evidence page.

## Grounded answers and review integrity

Fixed after the follow-up fixes above. All of these defects predate this work.

- **The Ask box did not answer from uploaded data.** With the built-in assistant (no model configured: dev, test and CI) most questions about a workspace's own records returned "I didn't catch that", a static architecture text, or tool output as JSON cut at 300 characters. `POST /api/v1/nexus/vanessa/ask` now passes the question to the read tools (`nexus.graph.read`, `nexus.cockpit.read`, `nexus.risk.read`, `nexus.recommend`), which return evidence about what was asked under `workspace_data`: the records the question names (by identifier or by name), orders and shipments that are late, stock below its own safety-stock or reorder field, the trace from late supply to parts, stock and customer orders, what the latest publish added and changed, and where each upload stands. The built-in assistant renders that evidence as plain sentences; a configured model receives the same evidence. No tool name or permission changed; `INTENT_TO_TOOL` remains the capability boundary. Code: `modules/nexus_spine/p0_migration/question_focus.py`, `workspace_facts.py`, `workspace_evidence.py`, `answer_rendering.py`.
- **What an answer does not claim.** Lateness is judged against the current UTC date, which the answer states. A date that is not written as `YYYY-MM-DD`, or a quantity in an ambiguous notation, is reported as unreadable instead of being guessed. When no sales orders, bill of materials or inventory are published, the answer says which link it could not follow. "What should I do" questions get the facts that bear on the decision (other open orders for the part, other suppliers on record, stock above threshold) and no chosen action. At most 2,000 records per kind and 12,000 in total are read for one answer; a partial read is stated in the answer.
- **How a question is read.** With no model configured, the words of the question are read with fixed rules (`question_focus.py`): the topic (late, short, exposed, changed, upload status, overview), the kinds of record named, identifiers and names. Conversational openers ("can you tell me ...", "hey Cortex, ...") do not change the reading. Open questions ("what needs my attention?", "any problems?") get the overview, which leads with what is late, short or flagged; a summary request that names a record is about that record. A value the question spells out narrows a list ("tier 1 suppliers", "orders in transit"). A two-letter value such as a country code counts only when written in capitals ("suppliers in DE"), so that "in" or "us" as ordinary words never filter. A question that cannot be read gets example questions, not a guess.
- **A role without a tool got "no evidence".** A viewer asking for a recommendation was told no evidence existed. The pipeline now reports the denial (`permission_denied`) for any tool the role lacks, not only for operational tools.
- **A failed lookup exposed internal error text.** When a tool raised, the text of the exception (which can name internal hosts and ports) was placed in the answer and in the evidence returned to the client, and nothing was logged. The exception is now logged with the request's trace id; the answer and the evidence say only that the lookup failed. A recommendation no longer fails when signals cannot be computed (their caches default to Redis): it is built from the published records, risks, scenarios and decisions, with signals marked unavailable.
- **Publishing rebuilt rows from profile samples outside staging, pilot and production.** The publish route gave the graph compiler no object-storage client in dev and test, so the compiler rebuilt rows from column profiles, which keep five values per column in no row order: rows went missing and values landed on the wrong record. The route now passes the stored upload in every environment and answers 503 when it cannot be read.
- **A rejected value was published anyway.** The compiler published every column of every row once any claim of the file was accepted. Claims prepared from an upload identify one cell each; the compiler now publishes only cells whose claim is accepted, and skips a row whose identifier cell was not accepted.
- **Conflict resolution rule.** One value per field of a record reaches the graph. The record a claim describes is identified by the primary-key cell of its own row (the server derives it; the evidence page never sent an entity key, so no conflict was ever raised there and the first of two disagreeing rows was published without notice). Different accepted values for one field of one record raise one blocking conflict, which grows as further rows join it. `approved` keeps the selected claim and supersedes the others, accepted or pending; `rejected` rejects the selected claim, or all of them; `suppressed` records that the finding is not a real conflict, after which the first row's value is published; `escalated` keeps publishing blocked. Previously `approved` and `rejected` answered HTTP 409 for every conflict, because they required a pending claim while conflicts only form between accepted ones. Rows that share a key are merged field by field, so a later row can supply a field an earlier row lacks, and a record's own row is no longer dropped when an earlier row only referred to it.
- **Staging accepted unauthenticated requests.** Only `prod`, `production` and `pilot` enforced Bearer tokens. `staging` now does too, compared without regard to case or surrounding spaces. `deploy/staging/docker-compose.yml` did not pass `CORTEX_JWT_SECRET` to the outbox relay or any `CORTEX_LLM_*` variable to the API, while the settings require them in staging, so neither container could start; they are now passed through.
- **Unreadable text on the evidence page.** The page is a light surface inside the dark theme and inherited near-white body text wherever an element had no colour class (the published-snapshot figures, the confidence column, form controls), and its signed-out and no-batch states put dark text on the dark page background. Every state of the page now uses one light surface with a dark base text colour.
- **Coverage.** `tests/test_ask_question_focus.py`, `test_ask_workspace_facts.py`, `test_ask_answer_rendering.py`, `test_ask_grounded_answers.py` (upload, review, publish and ask over HTTP, including a stubbed model gateway), `test_ask_workspace_evidence_postgres.py` (every evidence query on real PostgreSQL), `test_publish_uses_uploaded_rows.py`, `test_conflict_resolution_rule.py`, `test_staging_requires_authentication.py`, `frontend/src/lib/nexus/ask.test.ts`, and a browser test in `frontend/tests/critical-path-e2e.spec.ts` that publishes a file and asks about it in the cockpit.

## Open items

These are not resolved by this integration.

- **Mobile client security review.** `apps/mobile/App.tsx` keeps tokens in an in-memory map and uses placeholder identity values (an empty workspace id, a fixed `phone-001` device id). It needs secure on-device storage and real identity wiring before it is distributed.
- **RC0 release qualification.** Staging customer journey, backup/restore and rollback evidence are still required before RC0 production behaviour is activated.
- **Workflo API.** Unmounted by decision; re-enabling it is a product decision.
- **Legacy page retirement.** Three of the six pages listed under PR #14 are retired (`/nexus`, `/conflicts`, `/readiness`; see "Follow-up fixes"). The remaining three (`app/page.tsx`, `audit/page.tsx`, `workspace/layout.tsx`) can be retired once the E2E specs and the logout and change-password UI move to the canonical routes.
- **Signal engine false alerts.** `concentration_risk` is 1.0 for every record with no incoming relationship, so `concentration_risk_alert` fires as "blocking" for each such record (29 alerts on a 28-record sample workspace, none reflecting a delay or shortage). Signals are derived from graph structure only. The Ask box says so when it lists them and leaves them out of other answers; the engine itself is unchanged.
- **Signal context error.** Building the operational context calls `get_next_snapshot_version` on its repository (`graph/context_engine.py`). `SqlOperationalStateRepository` does not define it; the in-memory repository returns the constant 1 and the graph repository's method of the same name increments a database counter. Which behaviour a read should have is undecided, so the error is unchanged.
- **Claim review has no bulk action.** Review is one decision per cell (row and column), each with a typed mapping and rationale, so a large file cannot practically be reviewed on the evidence page.
- **Model-backed answers are verified against a stub only.** The Ask route's model path is tested with a stubbed gateway; no real model was called.
- **Limits of the rule-based question reader.** It matches words and does not paraphrase. A value spelled differently from the stored one ("Germany" where the file says `DE`) does not narrow a list, and the answer then lists every record of that kind without saying that the condition was not applied. It lists records and does not add quantities up across them. "Show me decisions" is not read as a question: an existing authorization test relies on that phrase being unknown.
- **No purchase order to product relationship.** `ENTITY_FOREIGN_KEYS` links a purchase order to its supplier, ship-to facility and buyer, not to the product in its `sku` column, so the dependency graph has no link from an order to its part. The Ask box resolves the part from the order's `sku` field.
- **Nexus pages on narrow screens.** At a width of 390 pixels the cockpit is 1,069 pixels wide: the mobile navigation bar (`components/nexus/NexusNav.tsx`) does not shrink and content runs off the screen. Present before this work and unchanged.
- **Cockpit "World state" figure.** The card takes its version from the open risks, so a workspace with published data and no recorded risk shows "Not available". The Ask response reports the published version.
- **Workflo CLI gate.** When the `workflo-cli/` package lands, add the backend Workflo paths back to the trigger filters in `workflo-cli.yml`.
- **`openapi-types` CI gate.** The job runs `git diff --exit-code` from `backend/` with paths relative to the repository root, so it matches no files and cannot fail. The artifacts had drifted on `main` for that reason.

No production deployment or customer data migration is part of this integration branch.
