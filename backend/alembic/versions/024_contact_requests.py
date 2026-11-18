"""024 — contact_requests: requests sent through the public site

Revision ID: 024_contact_requests
Revises: 023_device_mesh
Create Date: 2026-11-18

The demo request form used to show "Your request was received" with a random
reference number and save nothing, and the contact pages listed placeholder
email addresses. Requests are now stored in this table by
``POST /api/v1/public/contact-requests`` and read by the team with
``scripts/contact_requests.py``.

Not customer data: the sender has no account, so there is no ``workspace_id``
and no row-level policy. The table is never read through the API.

Created only when missing (same idempotent guard as migration 023): on a
database first touched by the API, ``init_db``/``create_all`` may already
have created it.
"""

import sqlalchemy as sa

from alembic import op

revision = "024_contact_requests"
down_revision = "023_device_mesh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "contact_requests" not in existing:
        op.create_table(
            "contact_requests",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("reference", sa.String(length=16), nullable=False),
            sa.Column("topic", sa.String(length=32), nullable=False),
            sa.Column("full_name", sa.String(length=200), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("company", sa.String(length=200), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("consent", sa.Boolean(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("handled_note", sa.String(length=500), nullable=True),
            sa.UniqueConstraint("reference", name="uq_contact_requests_reference"),
        )
        op.create_index("ix_contact_requests_topic", "contact_requests", ["topic"])
        op.create_index(
            "ix_contact_requests_status_created_at",
            "contact_requests",
            ["status", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "contact_requests" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("contact_requests")
