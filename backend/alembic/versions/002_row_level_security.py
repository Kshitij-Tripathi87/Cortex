"""Row-Level Security — tenant and workspace isolation policies.

Promotes RLS from a Python documentation string into enforced PostgreSQL
policies. Adds a tenant_id column to all tenant-scoped tables, enables RLS,
creates tenant/workspace isolation policies, and FORCEs RLS so even table
owners are subject to the policies.

Connection code must set the local GUC before issuing queries:
    SET LOCAL app.tenant_id = '<uuid>';
    SET LOCAL app.workspace_id = '<uuid>';

Downgrade drops policies, disables RLS, and removes tenant_id columns
to restore pre-RC-1 behavior. Do not run downgrade in production — it
removes tenant isolation.
"""

import sqlalchemy as sa

from alembic import op

revision = "002_row_level_security"
down_revision = "001_initial"
branch_labels = None
depends_on = None


# Tables that carry tenant_id + workspace_id (full isolation)
_TENANT_WORKSPACE_TABLES = [
    "source_batches",
    "source_files",
    "source_column_profiles",
    "evidence_claims",
    "evidence_conflicts",
    "conflict_resolutions",
    "readiness_assessments",
    "integration_outbox",
]

# Audit events: tenant_id required, workspace_id nullable (system events)
_TENANT_ONLY_TABLES = ["audit_events"]


def upgrade() -> None:
    # The transactional outbox table (ORM: app.modules.events.integration_events
    # IntegrationOutbox) is not created by any prior migration, so create it here
    # before applying RLS policies to it.
    op.create_table(
        "integration_outbox",
        sa.Column("outbox_id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("partner_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_integration_outbox_workspace_id",
        "integration_outbox",
        ["workspace_id"],
        unique=False,
    )
    # 1. Add tenant_id column (nullable for backfill; FORCEd RLS still gates access)
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(36)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)"
        )

    # 2. Enable RLS on every tenant-scoped table
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # 3. Tenant isolation policy (USING clause) on every table
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('app.tenant_id', true)::text)"
        )

    # 4. Workspace isolation policy (additional predicate) on workspace-scoped tables
    for table in _TENANT_WORKSPACE_TABLES:
        op.execute(
            f"CREATE POLICY workspace_isolation ON {table} "
            f"USING (workspace_id = current_setting('app.workspace_id', true)::text)"
        )

    # 5. Audit events: tenant gate + optional workspace (system events have NULL workspace)
    op.execute(
        "CREATE POLICY audit_workspace_isolation ON audit_events "
        "USING (workspace_id IS NULL OR "
        "workspace_id = current_setting('app.workspace_id', true)::text)"
    )

    # 6. FORCE RLS so table owners are also subject to policies
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Drop policies first
    for table in _TENANT_WORKSPACE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS workspace_isolation ON {table}")
    op.execute("DROP POLICY IF EXISTS audit_workspace_isolation ON audit_events")
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    # Disable and un-force RLS
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # Drop tenant_id columns
    for table in _TENANT_WORKSPACE_TABLES + _TENANT_ONLY_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_tenant_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS tenant_id")

    # Drop the integration_outbox table created by this migration
    op.drop_index("ix_integration_outbox_workspace_id", table_name="integration_outbox")
    op.drop_table("integration_outbox")
