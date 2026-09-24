"""018 — widen idempotency keys for the real Golden Path write path

Revision ID: 018_idempotency_key_width
Revises: 017_nexus_task_runtime
Create Date: 2026-09-22

The deterministic idempotency key format used by the World State write path
(and mirrored by the task execution bookkeeping) is:

    task:{task_id}:capability:{capability_id}:{sha256}

which reaches ~140 characters. The columns were created as VARCHAR(128);
SQLite ignores VARCHAR limits so the acceptance store never caught this,
but real PostgreSQL enforces them and the consequential write failed with
StringDataRightTruncationError. Widens both columns to VARCHAR(255).
"""

import sqlalchemy as sa

from alembic import op

revision = "018_idempotency_key_width"
down_revision = "017_nexus_task_runtime"
branch_labels = None
depends_on = None


def _column_exists(bind: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "world_state_events" in existing and _column_exists(
        bind, "world_state_events", "idempotency_key"
    ):
        op.alter_column(
            "world_state_events",
            "idempotency_key",
            existing_type=sa.String(length=128),
            type_=sa.String(length=255),
            existing_nullable=True,
        )

    if "nexus_task_executions" in existing and _column_exists(
        bind, "nexus_task_executions", "idempotency_key"
    ):
        op.alter_column(
            "nexus_task_executions",
            "idempotency_key",
            existing_type=sa.String(length=128),
            type_=sa.String(length=255),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "nexus_task_executions" in existing:
        op.alter_column(
            "nexus_task_executions",
            "idempotency_key",
            existing_type=sa.String(length=255),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
    if "world_state_events" in existing:
        op.alter_column(
            "world_state_events",
            "idempotency_key",
            existing_type=sa.String(length=255),
            type_=sa.String(length=128),
            existing_nullable=True,
        )
