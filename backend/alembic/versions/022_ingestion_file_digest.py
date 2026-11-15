"""022 — retain SHA-256 digest for uploaded ingestion artifacts.

Revision ID: 022_ingestion_file_digest
Revises: 021_material_planning_runs
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "022_ingestion_file_digest"
down_revision = "021_material_planning_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ingestion_log" not in inspector.get_table_names(schema="audit"):
        return
    columns = {column["name"] for column in inspector.get_columns("ingestion_log", schema="audit")}
    if "file_sha256" not in columns:
        op.add_column(
            "ingestion_log",
            sa.Column("file_sha256", sa.String(length=64), nullable=True),
            schema="audit",
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ingestion_log" not in inspector.get_table_names(schema="audit"):
        return
    columns = {column["name"] for column in inspector.get_columns("ingestion_log", schema="audit")}
    if "file_sha256" in columns:
        op.drop_column("ingestion_log", "file_sha256", schema="audit")
