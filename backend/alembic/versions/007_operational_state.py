"""Persist operational state records.

Revision ID: 007
Revises: 006
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_state_records",
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("state_type", sa.String(64), nullable=False),
        sa.Column("state_data", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint("workspace_id", "node_id", name="uq_operational_state_workspace_node"),
    )
    op.create_index("ix_operational_state_records_workspace_id", "operational_state_records", ["workspace_id"])
    op.create_index("ix_operational_state_records_node_id", "operational_state_records", ["node_id"])


def downgrade() -> None:
    op.drop_table("operational_state_records")
