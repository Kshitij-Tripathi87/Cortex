"""004_decision_memory.py

Add decision memory tables for Program H.

Revision ID: 004
Revises: 003_operational_graph
Create Date: 2026-07-19

"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003_operational_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create decision_records table
    op.create_table(
        "decision_records",
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("scenario_id", sa.String(36), nullable=False, index=True),
        sa.Column("recommendation_snapshot_id", sa.String(36), nullable=False),
        sa.Column("selected_recommendation_id", sa.String(36), nullable=True),
        sa.Column("decision_type", sa.String(64), nullable=False),
        sa.Column("decision_status", sa.String(32), nullable=False, default="pending"),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("modification_notes", sa.Text, nullable=True),
        sa.Column("source_propagation_id", sa.String(36), nullable=True),
        sa.Column("source_signal_ids", sa.JSON, nullable=False, default=list),
        sa.Column("evidence_claim_ids", sa.JSON, nullable=False, default=list),
        sa.Column("graph_version", sa.Integer, nullable=True),
        sa.Column("context_version", sa.Integer, nullable=True),
        sa.Column("feature_snapshot_version", sa.Integer, nullable=True),
        sa.Column("scenario_snapshot_version", sa.Integer, nullable=True),
        sa.Column("recommendation_snapshot_version", sa.Integer, nullable=True),
        sa.Column("tags", sa.JSON, nullable=False, default=list),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("decision_id"),
    )

    # Create decision_outcomes table
    op.create_table(
        "decision_outcomes",
        sa.Column("outcome_id", sa.String(36), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("outcome_status", sa.String(32), nullable=False),
        sa.Column("outcome_summary", sa.Text, nullable=False),
        sa.Column("actual_impact_description", sa.Text, nullable=True),
        sa.Column("actual_financial_impact", sa.Float, nullable=True),
        sa.Column("actual_recovery_hours", sa.Float, nullable=True),
        sa.Column("actual_service_level_impact_pct", sa.Float, nullable=True),
        sa.Column("met_expectations", sa.Boolean, nullable=True),
        sa.Column("would_decide_again", sa.Boolean, nullable=True),
        sa.Column("outcome_recorded_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("outcome_id"),
    )

    # Create decision_lessons table
    op.create_table(
        "decision_lessons",
        sa.Column("lesson_id", sa.String(36), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("outcome_id", sa.String(36), nullable=True),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("what_happened", sa.Text, nullable=False),
        sa.Column("what_expected", sa.Text, nullable=False),
        sa.Column("what_learned", sa.Text, nullable=False),
        sa.Column("policy_or_assumption_wrong", sa.Text, nullable=True),
        sa.Column("what_to_change_next_time", sa.Text, nullable=True),
        sa.Column("should_export_for_training", sa.Boolean, nullable=False, default=False),
        sa.Column("recorded_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("lesson_id"),
    )

    # Create indexes for efficient querying
    op.create_index(
        "ix_decision_records_workspace_scenario",
        "decision_records",
        ["workspace_id", "scenario_id"],
    )
    op.create_index(
        "ix_decision_records_reviewer",
        "decision_records",
        ["reviewer_id"],
    )
    op.create_index(
        "ix_decision_records_created_at",
        "decision_records",
        ["created_at"],
    )
    op.create_index(
        "ix_decision_outcomes_decision_id",
        "decision_outcomes",
        ["decision_id"],
    )
    op.create_index(
        "ix_decision_outcomes_created_at",
        "decision_outcomes",
        ["created_at"],
    )
    op.create_index(
        "ix_decision_lessons_decision_id",
        "decision_lessons",
        ["decision_id"],
    )
    op.create_index(
        "ix_decision_lessons_exportable",
        "decision_lessons",
        ["should_export_for_training"],
        postgresql_where=text("should_export_for_training = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_decision_lessons_exportable", table_name="decision_lessons")
    op.drop_index("ix_decision_lessons_decision_id", table_name="decision_lessons")
    op.drop_index("ix_decision_outcomes_created_at", table_name="decision_outcomes")
    op.drop_index("ix_decision_outcomes_decision_id", table_name="decision_outcomes")
    op.drop_index("ix_decision_records_created_at", table_name="decision_records")
    op.drop_index("ix_decision_records_reviewer", table_name="decision_records")
    op.drop_index("ix_decision_records_workspace_scenario", table_name="decision_records")

    op.drop_table("decision_lessons")
    op.drop_table("decision_outcomes")
    op.drop_table("decision_records")
