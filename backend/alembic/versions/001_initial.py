"""Initial migration — Phase 2 tables: audit, sources, compiler."""

import sqlalchemy as sa

from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Audit events
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_category", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=True),
        sa.Column("subject_id", sa.String(36), nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_subject_id", "audit_events", ["subject_id"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])

    # Source batches
    op.create_table(
        "source_batches",
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("uploader_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("source_system_hint", sa.String(32), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("file_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index("ix_source_batches_workspace_id", "source_batches", ["workspace_id"])

    # Source files
    op.create_table(
        "source_files",
        sa.Column("file_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("profiled", sa.Boolean, nullable=False),
        sa.Column("encoding", sa.String(32), nullable=True),
        sa.Column("row_count", sa.Integer, nullable=True),
        sa.Column("column_count", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("file_id"),
    )
    op.create_index("ix_source_files_batch_id", "source_files", ["batch_id"])
    op.create_index("ix_source_files_workspace_id", "source_files", ["workspace_id"])
    op.create_index("ix_source_files_checksum", "source_files", ["checksum"])

    # Source column profiles
    op.create_table(
        "source_column_profiles",
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("file_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("column_name", sa.String(256), nullable=False),
        sa.Column("column_index", sa.Integer, nullable=False),
        sa.Column("inferred_type", sa.String(32), nullable=False),
        sa.Column("null_ratio", sa.Float, nullable=False),
        sa.Column("distinct_count", sa.Integer, nullable=False),
        sa.Column("sample_values", sa.JSON, nullable=False),
        sa.Column("recommended_mapping", sa.String(128), nullable=True),
        sa.Column("mapping_confidence", sa.Float, nullable=True),
        sa.Column("requires_review", sa.Boolean, nullable=False),
        sa.PrimaryKeyConstraint("profile_id"),
    )
    op.create_index("ix_source_column_profiles_file_id", "source_column_profiles", ["file_id"])
    op.create_index("ix_source_column_profiles_workspace_id", "source_column_profiles", ["workspace_id"])

    # Evidence claims
    op.create_table(
        "evidence_claims",
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("source_file_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("source_column", sa.String(256), nullable=False),
        sa.Column("canonical_entity", sa.String(64), nullable=True),
        sa.Column("canonical_field", sa.String(128), nullable=True),
        sa.Column("raw_value", sa.Text, nullable=False),
        sa.Column("normalized_value", sa.Text, nullable=True),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("claim_state", sa.String(32), nullable=False),
        sa.Column("provenance", sa.JSON, nullable=False),
        sa.Column("requires_review", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("claim_id"),
    )
    op.create_index("ix_evidence_claims_workspace_id", "evidence_claims", ["workspace_id"])
    op.create_index("ix_evidence_claims_source_file_id", "evidence_claims", ["source_file_id"])
    op.create_index("ix_evidence_claims_batch_id", "evidence_claims", ["batch_id"])

    # Evidence conflicts
    op.create_table(
        "evidence_conflicts",
        sa.Column("conflict_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("claim_ids", sa.JSON, nullable=False),
        sa.Column("canonical_entity", sa.String(64), nullable=True),
        sa.Column("canonical_field", sa.String(128), nullable=True),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("blocking", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("review_required", sa.Boolean, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    op.create_index("ix_evidence_conflicts_workspace_id", "evidence_conflicts", ["workspace_id"])
    op.create_index("ix_evidence_conflicts_batch_id", "evidence_conflicts", ["batch_id"])

    # Conflict resolutions
    op.create_table(
        "conflict_resolutions",
        sa.Column("resolution_id", sa.String(36), nullable=False),
        sa.Column("conflict_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("selected_claim_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("resolution_id"),
    )
    op.create_index("ix_conflict_resolutions_conflict_id", "conflict_resolutions", ["conflict_id"])

    # Readiness assessments
    op.create_table(
        "readiness_assessments",
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("blocking_conflict_count", sa.Integer, nullable=False),
        sa.Column("open_conflict_count", sa.Integer, nullable=False),
        sa.Column("accepted_claim_count", sa.Integer, nullable=False),
        sa.Column("pending_claim_count", sa.Integer, nullable=False),
        sa.Column("assumptions", sa.JSON, nullable=False),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("assessment_id"),
    )
    op.create_index("ix_readiness_assessments_workspace_id", "readiness_assessments", ["workspace_id"])
    op.create_index("ix_readiness_assessments_batch_id", "readiness_assessments", ["batch_id"])


def downgrade() -> None:
    op.drop_table("readiness_assessments")
    op.drop_table("conflict_resolutions")
    op.drop_table("evidence_conflicts")
    op.drop_table("evidence_claims")
    op.drop_table("source_column_profiles")
    op.drop_table("source_files")
    op.drop_table("source_batches")
    op.drop_table("audit_events")
