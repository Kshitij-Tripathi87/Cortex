"""Append-only history, enforced by PostgreSQL.

The plan versions and the supplier commitment versions are the audit record
of the platform: docs/architecture/domain-model.md, invariant 8. Until this
revision that was a rule of the service layer only — no operation updates or
deletes a version, and the tests check that — but nothing in the database
refused such a write. A stray SQL session, a future service defect or a
script with the connection string could silently rewrite history
(docs/engineering/known-limitations.md, L-34).

This revision adds a BEFORE trigger to both version tables that refuses
UPDATE, DELETE and TRUNCATE with SQLSTATE 23000, naming the trigger as the
constraint. Maintenance that genuinely has to remove rows — the test-suite
cleanup and the confirmed development reset of the demo seed — says so
explicitly by setting ``nexus.allow_history_rewrite = 'on'`` in its
transaction; every other session is refused. A superuser can still drop the
trigger; revoking that needs separate roles, which is a deployment concern
(L-05).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HISTORY_TABLES = ("milestone_plan_versions", "supplier_commitment_versions")
FUNCTION_NAME = "reject_history_rewrite"
BYPASS_SETTING = "nexus.allow_history_rewrite"

_FUNCTION = f"""
CREATE FUNCTION {FUNCTION_NAME}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('{BYPASS_SETTING}', true) = 'on' THEN
        -- A maintenance transaction that said so: let the write through.
        IF TG_OP = 'UPDATE' THEN
            RETURN NEW;
        ELSIF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NULL;  -- the return of a statement-level TRUNCATE trigger is ignored
    END IF;
    RAISE EXCEPTION '% is append-only: % is refused', TG_TABLE_NAME, TG_OP
        USING ERRCODE = '23000', CONSTRAINT = TG_TABLE_NAME || '_append_only';
END;
$$
"""


def upgrade() -> None:
    op.execute(_FUNCTION)
    for table in HISTORY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {FUNCTION_NAME}()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION {FUNCTION_NAME}()
            """
        )


def downgrade() -> None:
    for table in HISTORY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION_NAME}()")
