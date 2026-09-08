"""J.3.1 — Digital Twin Lifecycle and Sandbox Isolation tables

Revision ID: 012_j31_twin_lifecycle
Revises: 011_j23_identifier_width
Create Date: 2026-08-18 00:00:00.000000

Adds the twin namespace (Program J.3.1):
1. twins — twin identity + IMMUTABLE lineage + lifecycle status
   (lineage columns are frozen at creation; only `status`/`updated_at` mutate)
2. twin_runs — append-only execution log; each run persists its final
   twin-namespace state (never writes to production world_* tables)

Isolation guarantee by construction: these tables live in the twin namespace
and no world_states / world_state_events / world_snapshots / world_versions
columns or triggers reference them for writes.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "012_j31_twin_lifecycle"
down_revision = "011_j23_identifier_width"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "twins",
        sa.Column("twin_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("parent_world_id", sa.String(length=64), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("fork_of_twin_id", sa.String(length=36), nullable=True),
        sa.Column("fork_from_run_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar[]"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("lineage_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("twin_id"),
    )
    op.create_index("ix_twins_created_at", "twins", ["created_at"], unique=False)
    op.create_index(
        "ix_twins_parent_world", "twins", ["parent_world_id", "workspace_id"], unique=False
    )
    op.create_index("ix_twins_snapshot_id", "twins", ["snapshot_id"], unique=False)
    op.create_index("ix_twins_status", "twins", ["status"], unique=False)
    op.create_index("ix_twins_org_ws", "twins", ["organization_id", "workspace_id"], unique=False)
    op.create_index(
        "ix_twins_lineage",
        "twins",
        ["parent_world_id", "parent_version", "snapshot_id"],
        unique=False,
    )

    op.create_table(
        "twin_runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("twin_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_type", sa.String(length=64), nullable=False, server_default="custom"),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="succeeded"),
        sa.Column(
            "injected_events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "final_variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("final_state_hash", sa.String(length=64), nullable=False),  # index: explicit below
        sa.Column("final_version", sa.Integer(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_twin_runs_twin_id", "twin_runs", ["twin_id"], unique=False)
    op.create_index(
        "ix_twin_runs_twin_ordered", "twin_runs", ["twin_id", "created_at"], unique=False
    )
    op.create_index("ix_twin_runs_workspace_id", "twin_runs", ["workspace_id"], unique=False)
    op.create_index(
        "ix_twin_runs_final_state_hash", "twin_runs", ["final_state_hash"], unique=False
    )

    op.create_table(
        "twin_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("twin_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_twin_events_run_id", "twin_events", ["run_id"], unique=False)
    op.create_index("ix_twin_events_twin_id", "twin_events", ["twin_id"], unique=False)
    op.create_index("ix_twin_events_workspace_id", "twin_events", ["workspace_id"], unique=False)

    op.create_table(
        "twin_versions",
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("twin_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("variable_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index("ix_twin_versions_twin_id", "twin_versions", ["twin_id"], unique=False)
    op.create_index("ix_twin_versions_workspace_id", "twin_versions", ["workspace_id"], unique=False)

    op.create_table(
        "twin_state",
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("twin_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "variables",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("graph_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("state_id"),
    )
    op.create_index("ix_twin_state_twin_id", "twin_state", ["twin_id"], unique=False)
    op.create_index("ix_twin_state_workspace_id", "twin_state", ["workspace_id"], unique=False)

    op.create_table(
        "twin_results",
        sa.Column("result_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("twin_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("final_state_hash", sa.String(length=64), nullable=False),
        sa.Column("final_version", sa.Integer(), nullable=False),
        sa.Column("events_processed", sa.Integer(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "timeline",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("result_id"),
    )
    op.create_index("ix_twin_results_run_id", "twin_results", ["run_id"], unique=True)
    op.create_index("ix_twin_results_twin_id", "twin_results", ["twin_id"], unique=False)
    op.create_index("ix_twin_results_workspace_id", "twin_results", ["workspace_id"], unique=False)
    # NOTE: the twin_runs indexes are created right after twin_runs above; a
    # duplicated block here (copy-paste) made upgrade() fail with
    # DuplicateObject on a fresh database. Never applied anywhere before the
    # fix — the file has been syntactically broken since it was committed.


def downgrade() -> None:
    op.drop_index("ix_twin_results_workspace_id", table_name="twin_results")
    op.drop_index("ix_twin_results_twin_id", table_name="twin_results")
    op.drop_index("ix_twin_results_run_id", table_name="twin_results")
    op.drop_table("twin_results")

    op.drop_index("ix_twin_state_workspace_id", table_name="twin_state")
    op.drop_index("ix_twin_state_twin_id", table_name="twin_state")
    op.drop_table("twin_state")

    op.drop_index("ix_twin_versions_workspace_id", table_name="twin_versions")
    op.drop_index("ix_twin_versions_twin_id", table_name="twin_versions")
    op.drop_table("twin_versions")

    op.drop_index("ix_twin_events_workspace_id", table_name="twin_events")
    op.drop_index("ix_twin_events_twin_id", table_name="twin_events")
    op.drop_index("ix_twin_events_run_id", table_name="twin_events")
    op.drop_table("twin_events")

    op.drop_index("ix_twin_runs_final_state_hash", table_name="twin_runs")
    op.drop_index("ix_twin_runs_workspace_id", table_name="twin_runs")
    op.drop_index("ix_twin_runs_twin_ordered", table_name="twin_runs")
    op.drop_index("ix_twin_runs_twin_id", table_name="twin_runs")
    op.drop_table("twin_runs")

    op.drop_index("ix_twins_lineage", table_name="twins")
    op.drop_index("ix_twins_status", table_name="twins")
    op.drop_index("ix_twins_snapshot_id", table_name="twins")
    op.drop_index("ix_twins_parent_world", table_name="twins")
    op.drop_index("ix_twins_org_ws", table_name="twins")
    op.drop_index("ix_twins_created_at", table_name="twins")
    op.drop_table("twins")
