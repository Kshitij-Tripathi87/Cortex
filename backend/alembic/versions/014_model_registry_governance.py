"""014 — Model registry governance and prediction provenance

Revision ID: 014_model_registry_governance
Revises: 013_outbox_sequence_authority
Create Date: 2026-09-09 12:00:00.000000

Adds:
1. nexus_model_registry table (if not exists) or adds tenant_id, workspace_id, promotion_gates, rollback_reason
2. Unique constraint (tenant_id, workspace_id, name, version) for model version immutability
3. Indexes for fast model lookup by tenant, workspace, type, and status
4. Forecast provenance columns: model_id, confidence, feature_hash in nexus_forecasts
"""

import sqlalchemy as sa

from alembic import op

revision = "014_model_registry_governance"
down_revision = "013_outbox_sequence_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # 1. nexus_model_registry
    if "nexus_model_registry" not in tables:
        op.create_table(
            "nexus_model_registry",
            sa.Column("model_id", sa.String(length=64), nullable=False),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("'default'"),
            ),
            sa.Column(
                "workspace_id",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("'default'"),
            ),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("model_type", sa.String(length=64), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("training_dataset", sa.String(length=256), nullable=True),
            sa.Column("feature_schema", sa.JSON(), nullable=False),
            sa.Column("world_state_version", sa.Integer(), nullable=True),
            sa.Column("training_data_range", sa.JSON(), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=False),
            sa.Column("calibration", sa.JSON(), nullable=False),
            sa.Column("gnn_config", sa.JSON(), nullable=True),
            sa.Column("rl_config", sa.JSON(), nullable=True),
            sa.Column(
                "status", sa.String(length=40), nullable=False, server_default=sa.text("'training'")
            ),
            sa.Column(
                "approval_status",
                sa.String(length=40),
                nullable=False,
                server_default=sa.text("'pending'"),
            ),
            sa.Column("shadow_metrics", sa.JSON(), nullable=True),
            sa.Column("promotion_gates", sa.JSON(), nullable=True),
            sa.Column(
                "created_by",
                sa.String(length=128),
                nullable=False,
                server_default=sa.text("'system'"),
            ),
            sa.Column("approved_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rollback_reason", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("model_id"),
            sa.UniqueConstraint(
                "tenant_id",
                "workspace_id",
                "name",
                "version",
                name="uq_nexus_model_tenant_ws_name_ver",
            ),
        )
        op.create_index("ix_nexus_model_registry_tenant_id", "nexus_model_registry", ["tenant_id"])
        op.create_index(
            "ix_nexus_model_registry_workspace_id", "nexus_model_registry", ["workspace_id"]
        )
        op.create_index("ix_nexus_model_registry_status", "nexus_model_registry", ["status"])
        op.create_index(
            "ix_nexus_model_registry_approval_status", "nexus_model_registry", ["approval_status"]
        )
        op.create_index(
            "ix_nexus_model_tenant_ws_type_status",
            "nexus_model_registry",
            ["tenant_id", "workspace_id", "model_type", "status"],
        )
    else:
        cols = [c["name"] for c in inspector.get_columns("nexus_model_registry")]
        if "tenant_id" not in cols:
            op.add_column(
                "nexus_model_registry",
                sa.Column(
                    "tenant_id",
                    sa.String(length=64),
                    nullable=False,
                    server_default=sa.text("'default'"),
                ),
            )
        if "workspace_id" not in cols:
            op.add_column(
                "nexus_model_registry",
                sa.Column(
                    "workspace_id",
                    sa.String(length=64),
                    nullable=False,
                    server_default=sa.text("'default'"),
                ),
            )
        if "promotion_gates" not in cols:
            op.add_column(
                "nexus_model_registry",
                sa.Column("promotion_gates", sa.JSON(), nullable=True),
            )
        if "rollback_reason" not in cols:
            op.add_column(
                "nexus_model_registry",
                sa.Column("rollback_reason", sa.Text(), nullable=True),
            )

    # 2. nexus_forecasts provenance columns
    if "nexus_forecasts" in tables:
        f_cols = [c["name"] for c in inspector.get_columns("nexus_forecasts")]
        if "model_id" not in f_cols:
            op.add_column(
                "nexus_forecasts",
                sa.Column("model_id", sa.String(length=64), nullable=True),
            )
            op.create_index("ix_nexus_forecasts_model_id", "nexus_forecasts", ["model_id"])
        if "confidence" not in f_cols:
            op.add_column(
                "nexus_forecasts",
                sa.Column("confidence", sa.Float(), nullable=True),
            )
        if "feature_hash" not in f_cols:
            op.add_column(
                "nexus_forecasts",
                sa.Column("feature_hash", sa.String(length=64), nullable=True),
            )
            op.create_index("ix_nexus_forecasts_feature_hash", "nexus_forecasts", ["feature_hash"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "nexus_model_registry" in tables:
        op.drop_table("nexus_model_registry")
