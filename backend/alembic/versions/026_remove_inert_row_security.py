"""026 — remove row-level security policies the application never satisfied

Revision ID: 026_remove_inert_row_security
Revises: 025_password_reset_requests
Create Date: 2026-11-18

Migrations 002 and 003 put forced row-level security on fourteen tables. The
policies compare each row with two session settings, ``app.tenant_id`` and
``app.workspace_id``. The application sets those settings in one place only
(the audit log), and it never fills the ``tenant_id`` column that thirteen of
the fourteen tables are compared on. So the policies could act in two ways,
and neither protected anyone:

* connected as a superuser (the compose files, the test suite), PostgreSQL
  skips every policy: nothing was enforced;
* connected as an ordinary role (a managed database, a least-privilege role),
  the first upload fails with ``new row violates row-level security policy
  for table "source_batches"``. Reproduced on 2026-11-18: sign-up works, the
  first upload returns a server error.

The product therefore worked only where its database role bypassed the
policies, which pushed deployments towards running the API as a database
superuser. This migration removes the policies and switches row security off
on those tables. What an ordinary role may see is unchanged in practice: it
could not use these tables at all before.

Separation between customers is enforced by the application, on every
request (``docs/architecture/TENANT_ISOLATION.md``). A database-level barrier
is a project of its own; that document lists what it needs. The ``tenant_id``
columns stay: the audit log fills its own, and dropping the others would only
make a later, complete implementation harder.

The downgrade restores the policies exactly as 002 and 003 created them,
including their faults.
"""

import sqlalchemy as sa

from alembic import op

revision = "026_remove_inert_row_security"
down_revision = "025_password_reset_requests"
branch_labels = None
depends_on = None

# Migration 002: a tenant policy and a workspace policy each.
_WORKSPACE_TABLES = (
    "source_batches",
    "source_files",
    "source_column_profiles",
    "evidence_claims",
    "evidence_conflicts",
    "conflict_resolutions",
    "readiness_assessments",
    "integration_outbox",
)
# Migration 002: a tenant policy and its own workspace rule.
_AUDIT_TABLE = "audit_events"
# Migration 003: a tenant policy only.
_GRAPH_TABLES = (
    "graph_nodes",
    "graph_edges",
    "graph_snapshots",
    "graph_write_events",
    "provenance_links",
)
_ALL_TABLES = (*_WORKSPACE_TABLES, _AUDIT_TABLE, *_GRAPH_TABLES)
_POLICIES = ("tenant_isolation", "workspace_isolation", "audit_workspace_isolation")

_TENANT_RULE = "tenant_id = current_setting('app.tenant_id', true)::text"
_WORKSPACE_RULE = "workspace_id = current_setting('app.workspace_id', true)::text"


def _present() -> list[str]:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    return [table for table in _ALL_TABLES if table in existing]


def upgrade() -> None:
    for table in _present():
        for policy in _POLICIES:
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    present = _present()
    for table in present:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_TENANT_RULE})")
    for table in present:
        if table in _WORKSPACE_TABLES:
            op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
            op.execute(f"CREATE POLICY workspace_isolation ON {table} USING ({_WORKSPACE_RULE})")
    if _AUDIT_TABLE in present:
        op.execute(f"DROP POLICY IF EXISTS audit_workspace_isolation ON {_AUDIT_TABLE}")
        op.execute(
            f"CREATE POLICY audit_workspace_isolation ON {_AUDIT_TABLE} "
            f"USING (workspace_id IS NULL OR {_WORKSPACE_RULE})"
        )
    for table in present:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
