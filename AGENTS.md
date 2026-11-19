# Rules for coding contributors and coding agents

This repository is a greenfield build. Read this file, then
`docs/architecture/system-boundaries.md` and
`docs/architecture/domain-model.md`, before changing anything. The sprint
playbook ("Three-Day Greenfield Engineering Execution Playbook", v2.0) is the
authority these files are derived from; where they disagree, raise it with
the lead instead of choosing.

The playbook itself is not in this repository: the repository is public and
the playbook is a planning document of the project lead. Ask the lead for it.
Everything a change needs is restated in `docs/architecture/` and
`docs/engineering/`, and every place where the build departs from the
playbook is listed in `docs/engineering/implementation-log.md`.

## Invariants you must not break

1. **PostgreSQL is the source of truth.** Responses are projections of stored
   rows. No fixture, constant or cache answers a request.
2. **Every query is workspace-scoped.** Load a record with its id *and* its
   `workspace_id`. Never `session.get(Model, id)` and check ownership later.
3. **Preview does not change canonical records.** It writes the ingestion
   ledger only.
4. **Commit is all-or-nothing and idempotent.** One transaction for the valid
   rows of a batch; a replay returns the recorded result.
5. **History is append-only.** A new planned date or commitment date is a new
   version row. Never update or delete a version.
6. **Money and quantity are `Decimal`/`NUMERIC`.** Never `float`.
7. **Services own transactions.** Repositories never commit. Endpoints never
   run SQL.
8. **Facts and inference stay apart.** No risk score, lateness, probability or
   recommendation in a table, a schema or the World State.
9. **Timestamps are UTC and come from `app.core.clock`.** No naive datetimes,
   no scattered `datetime.now()`.
10. **Nothing leaks.** No secret, SQL, stack trace, path or submitted value in
    a response; no credentials or row payloads in a log line.

## Rules of work

1. Do not look for, assume or depend on files of the earlier Cortex Nexus
   codebase. Nothing from it is used here.
2. Do not change the stack (see `docs/architecture/decisions/ADR-001-backend-stack.md`)
   and do not add a second ORM, migration tool or API framework.
3. Do not add a dependency without stating the need first; update `uv.lock`
   in the same commit.
4. Do not change a model field, enumeration or response shape without
   changing the domain document, the Pydantic schema, the migration, the
   exported OpenAPI document and the tests together.
5. Do not create a migration unless you are the migration owner for the task.
   There is one migration stream.
6. Do not put SQL in endpoints, HTTP in services, or database access in
   `app/ingestion`.
7. Do not bypass workspace filtering, and do not treat a workspace id from a
   request as proof of access.
8. Do not write to canonical tables from the demo seed: it calls the preview
   and commit services, like the API does.
9. Do not create fake World State data or hard-coded counts.
10. Do not add an agent, LLM, vector store, queue or cache in this phase.
11. Do not remove or weaken a test to make a check pass.
12. Do not report a task as passing after reading the code only. Run the
    checks and report the exact commands and results.
13. List every file you changed and every limitation you know of.

## Checks to run before handing work over

From the repository root, with the databases up (`make db-up`) and migrated
(`make migrate`):

```bash
make lint format-check typecheck
make test-unit
make test-api test-integration
make openapi-check
make verify            # the whole chain, stops at the first failure
```

Status words: `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, `PASS`, `DEFERRED`.
Generated code, a created file or a green unit test alone is not `PASS`.

## File ownership

| Area | Path | Notes |
|---|---|---|
| Models | `services/api/app/models/` | One file per table group; `models/__init__.py` registers them and has one owner |
| Migrations | `services/api/alembic/versions/` | One owner; reviewed by hand before merge |
| Schemas | `services/api/app/schemas/` | The external contract |
| Repositories | `services/api/app/repositories/` | Scoped queries; no commit, no policy |
| Services | `services/api/app/services/` | Rules and transactions |
| Pure ingestion | `services/api/app/ingestion/` | No database, no HTTP |
| Endpoints | `services/api/app/api/v1/endpoints/` | Registered only in `api/v1/router.py` |
| Tests | `services/api/tests/` | Written against the documented contract, not against private details |
| Demo data | `data/samples/nexus_demo/` | Synthetic; fictional names only |

## Task card

Every delegated task states:

```markdown
# Task ID: D2-A-03
## Objective
## Context          (which sections of the contracts apply)
## Allowed files
## Forbidden files
## Contract         (fields, rules and shapes the task must follow)
## Required behavior
## Required tests
## Acceptance criteria
## Output           (summary, changed files, commands run and their results, open issues)
```

A contributor may propose a change to a shared contract. Only the lead
approves it, and the contract document changes before the code does.
