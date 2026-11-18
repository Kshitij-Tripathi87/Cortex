# How customers are kept apart

Status on 2026-11-18. This page describes what the code does today. The
numbered design documents (`docs/06-database-strategy.md` §5,
`docs/09-security.md` §3) describe a stronger target that is not built; where
they disagree with this page, this page is the current state.

## In one paragraph

All organizations share one PostgreSQL database and one file store. What
keeps one organization's data from another is the application: on every
request it compares the workspace asked for with the workspace in the
caller's sign-in, and every query filters on that workspace. The database
itself adds no second barrier. A query that forgot its workspace filter
would return another customer's rows, and nothing below the application
would stop it.

## What enforces the separation

- **Sign-in.** Each signup creates one organization with one workspace. The
  sign-in token carries that single workspace id
  (`backend/app/infrastructure/security.py`, `_auth_context_from_claims`).
  In every environment except `dev` and `test` a request without a valid
  token is refused, and identity headers supplied by the caller are ignored.
- **The check on each request.** Routes call
  `require_workspace_access(workspace_id, auth)`. A workspace that is not the
  caller's own is answered with 403; a record that belongs to another
  workspace with 404.
- **A gate on new routes.** `backend/tests/test_endpoint_authz_audit.py`
  reads every route and fails when one is added without an authorization
  helper (`docs/architecture/ENDPOINT_AUTHZ_AUDIT.md`).
- **Queries.** Services and repositories filter on `workspace_id`.
- **Files.** Uploads are stored under `workspaces/{workspace_id}/uploads/…`
  in one bucket. A browser never talks to the file store: a file is read by
  the API, for a batch that has passed the workspace check.
- **Live updates.** A stream or socket is opened for one workspace after the
  same check.

## How it is tested

Tests that sign in as one workspace and reach for another, among them:

- `backend/tests/test_nexus_golden_path.py` (cross-workspace reads answer
  403 or 404),
- `backend/tests/test_ask_grounded_answers.py::test_answers_never_cross_workspaces`
  and `backend/tests/test_ask_workspace_evidence_postgres.py::test_another_workspace_sees_nothing`,
- `backend/tests/test_source_claim_review_api.py` and
  `test_source_claim_review.py` (review and conflict resolution),
- `backend/tests/test_agent_routes_tenant_isolation.py`,
- `backend/tests/test_nexus_v085_b4_reliability.py` (replay, streams and
  sockets),
- `frontend/tests/realtime-e2e.spec.ts` (foreign workspace → 403, bad
  token → 401).

These tests cover the routes they call. They cannot prove that no query
anywhere lacks its filter.

## What does not exist: a barrier inside the database

Migrations 002 and 003 created row-level security policies on fourteen
tables and forced them on the table owner. They compared each row with two
session settings, `app.tenant_id` and `app.workspace_id`. They never
protected anything:

- The application wrote those settings in one place (the audit log). It never
  filled the `tenant_id` column that thirteen of the fourteen tables were
  compared on.
- Connected as a superuser, which is how the compose files and the test
  suite connect, PostgreSQL skips every policy.
- Connected as any other role, the first upload failed with
  `new row violates row-level security policy for table "source_batches"`.
  Reproduced on 2026-11-18 with a role that owned the database: sign-up
  worked, the first upload returned a server error.
- The policies were permissive, so PostgreSQL combined them with OR, not
  AND: a row was visible when the tenant matched *or* the workspace matched.
  On the audit log, every event without a workspace was visible to everyone.
- The other 82 tables, among them users, organizations, risks, scenarios
  and decisions, had no policy at all.

So the product only worked where its database role bypassed the policies,
which pushed deployments towards running the API as a database superuser.
Migration 026 removes the policies. Nothing that was enforced before is lost.

`backend/tests/test_ordinary_database_role.py` now runs upload, review and
publish with every connection signed in as a role that is neither a
superuser nor exempt from row security, and fails if a later migration
switches row security on for a table without the application satisfying it.

## The database role

The API does not need a superuser. A role that owns the database and its
tables is enough, for the migrations and for the API alike (checked: all 26
migrations and the full path from sign-up to a published workspace, as a
role created with `NOSUPERUSER NOBYPASSRLS`). Use such a role where you can.
`docker-compose.prod.yml` still connects as the superuser the PostgreSQL
image creates; a managed database usually hands you an ordinary role
already.

## What a real database barrier would take

Listed so that nobody mistakes a partial version for the real thing:

1. A role for the API that cannot bypass row security, separate from the
   role that owns the tables and runs migrations.
2. The workspace written into the session at the start of **every
   transaction**. A request here commits more than once, and a setting made
   with `SET LOCAL` ends with the transaction.
3. A way through for the code that legitimately reads across workspaces:
   the outbox relay, the operator scripts, the workers.
4. Policies on every table that holds customer data, written as restrictive
   policies or as one policy per table, so that two rules do not weaken each
   other.
5. The test suite and CI running as the restricted role, so a missed code
   path fails a test and not a customer.

Until that exists, say "enforced by the application" and nothing stronger.
The public Security page (`frontend/src/app/security/page.tsx`) says exactly
that.
