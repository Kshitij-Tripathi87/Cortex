"""013 — Outbox sequence authority and realtime event fabric

Revision ID: 013_outbox_sequence_authority
Revises: 012_j31_twin_lifecycle
Create Date: 2026-09-09 00:00:00.000000

Adds:
1. nexus_events table (if not exists) or adds seq, published_at, publish_attempts, published_by
2. Unique constraint (tenant_id, workspace_id, seq) for per-workspace sequence authority
3. Indexes for fast unpublished sweep and replay
"""

import sqlalchemy as sa

from alembic import op

revision = "013_outbox_sequence_authority"
down_revision = "012_j31_twin_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "nexus_events" not in tables:
        op.create_table(
            "nexus_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("workspace_id", sa.String(length=64), nullable=False),
            sa.Column("seq", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=40), nullable=True),
            sa.Column("entity_id", sa.String(length=128), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("causation_id", sa.String(length=64), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("world_state_version", sa.Integer(), nullable=True),
            sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "publish_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column("published_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("event_id", name="uq_nexus_events_event_id"),
            sa.UniqueConstraint(
                "tenant_id", "workspace_id", "seq", name="uq_nexus_events_tenant_workspace_seq"
            ),
        )
        op.create_index("ix_nexus_events_tenant_id", "nexus_events", ["tenant_id"])
        op.create_index("ix_nexus_events_workspace_id", "nexus_events", ["workspace_id"])
        op.create_index("ix_nexus_events_seq", "nexus_events", ["seq"])
        op.create_index("ix_nexus_events_event_type", "nexus_events", ["event_type"])
        op.create_index("ix_nexus_events_entity_id", "nexus_events", ["entity_id"])
        op.create_index("ix_nexus_events_correlation_id", "nexus_events", ["correlation_id"])
        op.create_index("ix_nexus_events_published", "nexus_events", ["published"])
        op.create_index("ix_nexus_events_published_at", "nexus_events", ["published_at"])
        op.create_index("ix_nexus_events_created_at", "nexus_events", ["created_at"])
        op.create_index("ix_nexus_events_unpublished", "nexus_events", ["published_at", "seq"])
    else:
        cols = [c["name"] for c in inspector.get_columns("nexus_events")]
        if "seq" not in cols:
            op.add_column(
                "nexus_events",
                sa.Column("seq", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
            )
        if "published_at" not in cols:
            op.add_column(
                "nexus_events", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "publish_attempts" not in cols:
            op.add_column(
                "nexus_events",
                sa.Column(
                    "publish_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
                ),
            )
        if "published_by" not in cols:
            op.add_column(
                "nexus_events", sa.Column("published_by", sa.String(length=128), nullable=True)
            )

        existing_uqs = [uq["name"] for uq in inspector.get_unique_constraints("nexus_events")]
        if "uq_nexus_events_tenant_workspace_seq" not in existing_uqs:
            op.create_unique_constraint(
                "uq_nexus_events_tenant_workspace_seq",
                "nexus_events",
                ["tenant_id", "workspace_id", "seq"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "nexus_events" in tables:
        op.drop_table("nexus_events")
