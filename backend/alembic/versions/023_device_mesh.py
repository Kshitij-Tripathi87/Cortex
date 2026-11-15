"""023 — Device Mesh tables (Day 25 phone client)

Revision ID: 023_device_mesh
Revises: 022_ingestion_file_digest
Create Date: 2026-09-28

    Re-chained during the 2026-11-15 PR consolidation. This migration was
    authored on the v0.8.5 productization branch (PR #8) as
    ``020_device_mesh`` (revises ``019_audit_subject_id_width``), which
    collided with ``020_p1_p2_operational_planning`` (PR #12) and produced
    two Alembic heads. It now follows ``022_ingestion_file_digest`` so the
    history stays linear. The DDL is unchanged and idempotent.

    A database that already ran the original ``020_device_mesh`` records a
    revision this tree no longer contains, so ``alembic upgrade head`` stops
    with "Can't locate revision identified by '020_device_mesh'". Re-point
    it first, then upgrade::

        alembic stamp --purge 019_audit_subject_id_width
        alembic upgrade head

    ``--purge`` is required: a plain ``stamp`` fails on the same unknown
    revision. The "create only when missing" guards below skip the tables
    such a database already has.

    Creates the capability-bearing device tables:

    vanessa_devices             device identity, capabilities, presence
    vanessa_sessions            User / Voice / Task session separation
    vanessa_voice_sessions      the voice state machine (provider-agnostic)
    vanessa_push_registrations  push-token enrollment per device + provider
    vanessa_notifications       policy-gated notification deliveries

Each table is created only when missing (same idempotent guard style as
migrations 013/016/017); fresh databases are owned by init_db/create_all.
"""

import sqlalchemy as sa

from alembic import op

revision = "023_device_mesh"
down_revision = "022_ingestion_file_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "vanessa_devices" not in existing:
        op.create_table(
            "vanessa_devices",
            sa.Column("device_id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("owner_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("public_key", sa.String(length=512), nullable=True),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("agent_version", sa.String(length=32), nullable=False),
            sa.Column("capabilities", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, index=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_vanessa_devices_owner_status",
            "vanessa_devices",
            ["owner_id", "status"],
        )

    if "vanessa_sessions" not in existing:
        op.create_table(
            "vanessa_sessions",
            sa.Column("session_id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("device_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("session_type", sa.String(length=16), nullable=False, index=True),
            sa.Column("ref_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_vanessa_sessions_type_user",
            "vanessa_sessions",
            ["session_type", "user_id"],
        )

    if "vanessa_voice_sessions" not in existing:
        op.create_table(
            "vanessa_voice_sessions",
            sa.Column("voice_session_id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("device_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("state", sa.String(length=32), nullable=False, index=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "vanessa_push_registrations" not in existing:
        op.create_table(
            "vanessa_push_registrations",
            sa.Column("registration_id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("device_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("push_token", sa.String(length=512), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "vanessa_notifications" not in existing:
        op.create_table(
            "vanessa_notifications",
            sa.Column("notification_id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("user_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("device_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("event_type", sa.String(length=64), nullable=False, index=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("delivered_via", sa.String(length=32), nullable=False),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in (
        "vanessa_notifications",
        "vanessa_push_registrations",
        "vanessa_voice_sessions",
        "vanessa_sessions",
        "vanessa_devices",
    ):
        if table in existing:
            op.drop_table(table)
