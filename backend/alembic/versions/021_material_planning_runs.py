"""021 — persist reproducible material-planning runs.

Revision ID: 021_material_planning_runs
Revises: 020_p1_p2_operational_planning
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "021_material_planning_runs"
down_revision = "020_p1_p2_operational_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "material_planning_runs" in inspector.get_table_names(schema="inventory"):
        return

    op.create_table(
        "material_planning_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema="inventory",
    )
    op.create_index(
        "ix_material_planning_runs_workspace_created",
        "material_planning_runs",
        ["workspace_id", "created_at"],
        schema="inventory",
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "material_planning_runs" in inspector.get_table_names(schema="inventory"):
        op.drop_table("material_planning_runs", schema="inventory")
