"""005_snapshot_versioning.py

Add snapshot_sequences table for DB-backed monotonic versioning.

Revision ID: 005
Revises: 004
Create Date: 2026-07-20

"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create snapshot_sequences table
    op.create_table(
        "snapshot_sequences",
        sa.Column("sequence_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("snapshot_type", sa.String(64), nullable=False),
        sa.Column("next_version", sa.Integer, nullable=False, default=1),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("sequence_id"),
        sa.UniqueConstraint("workspace_id", "snapshot_type", name="uq_workspace_snapshot_type"),
    )

    # Initialize sequences for existing workspaces with graph snapshots
    # This ensures existing workspaces continue from their current version
    op.execute("""
        INSERT INTO snapshot_sequences (sequence_id, workspace_id, snapshot_type, next_version, updated_at)
        SELECT
            gen_random_uuid(),
            workspace_id,
            'graph',
            MAX(version) + 1,
            NOW()
        FROM graph_snapshots
        GROUP BY workspace_id
        ON CONFLICT (workspace_id, snapshot_type) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("snapshot_sequences")
