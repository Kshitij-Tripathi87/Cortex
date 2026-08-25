"""006_ml_pipeline.py

Add ML pipeline tables for decision export, feature store, model registry, and shadow inference.

Revision ID: 006
Revises: 005
Create Date: 2026-07-21

"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Feature store tables
    op.create_table(
        "ml_feature_store",
        sa.Column("feature_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("feature_name", sa.String(128), nullable=False),
        sa.Column("feature_value", sa.Float, nullable=False),
        sa.Column("feature_version", sa.String(16), nullable=False, default="1.0.0"),
        sa.Column("snapshot_version", sa.Integer, nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=text("(CURRENT_TIMESTAMP)")),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("feature_id"),
    )

    op.create_table(
        "ml_feature_groups",
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("group_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("feature_names", sa.JSON, nullable=False, default=list),
        sa.Column("version", sa.String(16), nullable=False, default="1.0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=text("(CURRENT_TIMESTAMP)")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("group_id"),
    )

    # Model registry tables
    op.create_table(
        "ml_model_registry",
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("model_type", sa.String(32), nullable=False),
        sa.Column("version", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False, default="development"),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("training_data_version", sa.String(64), nullable=False),
        sa.Column("training_samples", sa.Integer, nullable=False),
        sa.Column("hyperparameters", sa.JSON, nullable=False, default=dict),
        sa.Column("metrics", sa.JSON, nullable=False, default=dict),
        sa.Column("artifact_path", sa.String(512), nullable=True),
        sa.Column("parent_model_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=text("(CURRENT_TIMESTAMP)")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("model_id"),
    )

    op.create_table(
        "ml_model_evaluations",
        sa.Column("evaluation_id", sa.String(36), nullable=False),
        sa.Column("model_id", sa.String(36), nullable=False, index=True),
        sa.Column("evaluation_name", sa.String(128), nullable=False),
        sa.Column("dataset_name", sa.String(128), nullable=False),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("metrics", sa.JSON, nullable=False, default=dict),
        sa.Column("confusion_matrix", sa.JSON, nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=text("(CURRENT_TIMESTAMP)")),
        sa.Column("evaluated_by", sa.String(36), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("evaluation_id"),
    )

    # Shadow inference table
    op.create_table(
        "ml_shadow_predictions",
        sa.Column("prediction_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("model_id", sa.String(36), nullable=False),
        sa.Column("model_version", sa.String(16), nullable=False),
        sa.Column("input_features", sa.JSON, nullable=False, default=dict),
        sa.Column("prediction", sa.JSON, nullable=False, default=dict),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("actual_outcome", sa.JSON, nullable=True),
        sa.Column("matched", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=text("(CURRENT_TIMESTAMP)")),
        sa.Column("metadata", sa.JSON, nullable=False, default=dict),
        sa.PrimaryKeyConstraint("prediction_id"),
    )

    # Create indexes for performance
    op.create_index("ix_ml_feature_store_entity", "ml_feature_store", ["workspace_id", "entity_type", "entity_id"])
    op.create_index("ix_ml_feature_store_name", "ml_feature_store", ["feature_name"])
    op.create_index("ix_ml_model_registry_name_version", "ml_model_registry", ["model_name", "version"])
    op.create_index("ix_ml_shadow_predictions_model", "ml_shadow_predictions", ["model_id", "model_version"])


def downgrade() -> None:
    op.drop_index("ix_ml_shadow_predictions_model", table_name="ml_shadow_predictions")
    op.drop_index("ix_ml_model_registry_name_version", table_name="ml_model_registry")
    op.drop_index("ix_ml_feature_store_name", table_name="ml_feature_store")
    op.drop_index("ix_ml_feature_store_entity", table_name="ml_feature_store")

    op.drop_table("ml_shadow_predictions")
    op.drop_table("ml_model_evaluations")
    op.drop_table("ml_model_registry")
    op.drop_table("ml_feature_groups")
    op.drop_table("ml_feature_store")
