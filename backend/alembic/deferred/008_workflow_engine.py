"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Create workflow engine tables.

Revision ID: 008
Revises: 007
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("workflow_name", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("triggered_by", sa.String(36), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_index("ix_workflow_runs_workspace_id", "workflow_runs", ["workspace_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "workflow_step_runs",
        sa.Column("stage_instance_id", sa.String(36), nullable=False),
        sa.Column("workflow_instance_id", sa.String(36), nullable=False),
        sa.Column("stage_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("verb", sa.String(64), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("gate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("stage_instance_id"),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"],
            ["workflow_runs.instance_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_workflow_step_runs_workflow_instance_id",
        "workflow_step_runs",
        ["workflow_instance_id"],
    )
    op.create_index(
        "ix_workflow_step_runs_status",
        "workflow_step_runs",
        ["status"],
    )

    op.create_table(
        "workflow_step_artifacts",
        sa.Column("artifact_id", sa.String(36), nullable=False),
        sa.Column("workflow_instance_id", sa.String(36), nullable=False),
        sa.Column("stage_instance_id", sa.String(36), nullable=False),
        sa.Column("artifact_key", sa.String(256), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
        sa.ForeignKeyConstraint(
            ["workflow_instance_id"],
            ["workflow_runs.instance_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stage_instance_id"],
            ["workflow_step_runs.stage_instance_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_workflow_step_artifacts_workflow_instance_id",
        "workflow_step_artifacts",
        ["workflow_instance_id"],
    )
    op.create_index(
        "ix_workflow_step_artifacts_key",
        "workflow_step_artifacts",
        ["artifact_key"],
    )


def downgrade() -> None:
    op.drop_table("workflow_step_artifacts")
    op.drop_table("workflow_step_runs")
    op.drop_table("workflow_runs")
