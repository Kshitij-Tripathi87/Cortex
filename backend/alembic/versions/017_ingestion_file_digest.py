"""017 — retain raw upload SHA-256 on ingestion audit records.

Revision ID: 017_ingestion_file_digest
Revises: 016_outbox_claim_lease
Create Date: 2026-11-04
"""

import sqlalchemy as sa

from alembic import op

revision = "017_ingestion_file_digest"
down_revision = "016_outbox_claim_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names(schema="audit")
    if "ingestion_log" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("ingestion_log", schema="audit")}
    if "file_sha256" not in columns:
        op.add_column(
            "ingestion_log",
            sa.Column("file_sha256", sa.String(length=64), nullable=True),
            schema="audit",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names(schema="audit")
    if "ingestion_log" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("ingestion_log", schema="audit")}
    if "file_sha256" in columns:
        op.drop_column("ingestion_log", "file_sha256", schema="audit")
