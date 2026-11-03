"""019 — widen audit_events.subject_id for prefixed domain IDs

Revision ID: 019_audit_subject_id_width
Revises: 018_idempotency_key_width
Create Date: 2026-09-28

The governed-denial audit path writes subject_ids like decision IDs, which
carry the domain prefix (``D-`` + 36-char UUID = 39 chars). The column was
created as VARCHAR(36); SQLite ignores VARCHAR limits so the acceptance
store never caught this, but real PostgreSQL enforces them and the audit
INSERT failed with StringDataRightTruncationError — the denial produced no
durable audit trail. Widens subject_id to VARCHAR(64).
"""

import sqlalchemy as sa

from alembic import op

revision = "019_audit_subject_id_width"
down_revision = "018_idempotency_key_width"
branch_labels = None
depends_on = None


def _column_exists(bind: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "audit_events" in existing and _column_exists(bind, "audit_events", "subject_id"):
        op.alter_column(
            "audit_events",
            "subject_id",
            existing_type=sa.String(length=36),
            type_=sa.String(length=64),
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "audit_events" in existing:
        op.alter_column(
            "audit_events",
            "subject_id",
            existing_type=sa.String(length=64),
            type_=sa.String(length=36),
            existing_nullable=True,
        )
