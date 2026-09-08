"""J.2.3 — Repository hardening: concurrency sequencing and idempotency

Revision ID: 010_j23_repository_hardening
Revises: 009_mvp_wedge_schema
Create Date: 2026-08-18 00:00:00.000000

Adds:
1. sequence_number to world_versions for monotonic sequencing per workspace/world
2. idempotency_key to world_state_events for deduplication
3. Unique constraints to enforce invariants
"""

import sqlalchemy as sa

from alembic import op

revision = "010_j23_repository_hardening"
down_revision = "009_mvp_wedge_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sequence_number column to world_versions
    op.add_column(
        "world_versions",
        sa.Column("sequence_number", sa.Integer(), nullable=True),
    )

    # Create unique index for monotonic sequencing per (world_id, workspace_id)
    op.create_index(
        "uq_world_versions_sequence",
        "world_versions",
        ["world_id", "workspace_id", "sequence_number"],
        unique=True,
        postgresql_where=sa.text("sequence_number IS NOT NULL"),
    )

    # Add idempotency_key column to world_state_events
    op.add_column(
        "world_state_events",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )

    # Create unique index for idempotency per (world_id, workspace_id, idempotency_key)
    op.create_index(
        "uq_world_state_events_idempotency",
        "world_state_events",
        ["world_id", "workspace_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # Add index on idempotency_key alone for fast lookup
    op.create_index(
        "ix_world_state_events_idempotency_key",
        "world_state_events",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_world_state_events_idempotency_key", table_name="world_state_events")
    op.drop_index("uq_world_state_events_idempotency", table_name="world_state_events")
    op.drop_column("world_state_events", "idempotency_key")

    op.drop_index("uq_world_versions_sequence", table_name="world_versions")
    op.drop_column("world_versions", "sequence_number")
