"""025 — core.users.reset_requested_at: reset requests waiting for an operator

Revision ID: 025_password_reset_requests
Revises: 024_contact_requests
Create Date: 2026-11-18

Cortex sends no email. The sign-in page used to answer a reset request with
"a reset link is on its way", but the link was created and thrown away, so the
user waited for a message that could not arrive.

A request is now recorded on the user row. The team lists the waiting
requests with ``scripts/admin_users.py reset-requests`` and sends each user a
single-use link by hand (``issue-reset``).

Added only when missing: on a database first touched by the API,
``init_db``/``create_all`` may already have created the column.
"""

import sqlalchemy as sa

from alembic import op

revision = "025_password_reset_requests"
down_revision = "024_contact_requests"
branch_labels = None
depends_on = None

_INDEX = "ix_users_reset_requested_at"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names(schema="core"):
        return set()
    return {column["name"] for column in inspector.get_columns("users", schema="core")}


def _indexes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names(schema="core"):
        return set()
    return {index["name"] for index in inspector.get_indexes("users", schema="core")}


def upgrade() -> None:
    columns = _columns()
    if not columns:
        return
    if "reset_requested_at" not in columns:
        op.add_column(
            "users",
            sa.Column("reset_requested_at", sa.DateTime(timezone=True), nullable=True),
            schema="core",
        )
    # Only the few rows that are waiting are indexed, so the daily operator
    # list does not scan every user.
    if _INDEX not in _indexes():
        op.create_index(
            _INDEX,
            "users",
            ["reset_requested_at"],
            schema="core",
            postgresql_where=sa.text("reset_requested_at IS NOT NULL"),
        )


def downgrade() -> None:
    if _INDEX in _indexes():
        op.drop_index(_INDEX, table_name="users", schema="core")
    if "reset_requested_at" in _columns():
        op.drop_column("users", "reset_requested_at", schema="core")
