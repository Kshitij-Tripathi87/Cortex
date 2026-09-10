"""016 — Outbox claim/lease + retry columns (v0.8.5-B4)

Revision ID: 016_outbox_claim_lease
Revises: 015_auth_onboarding
Create Date: 2026-09-10

Adds worker claim/lease and retry bookkeeping to ``nexus_events``:

* ``claimed_at`` / ``claimed_by`` — which publisher currently owns the row
* ``lease_expires_at`` — claim expiry; expired claims are reclaimed by peers
* ``next_retry_at`` — exponential-backoff visibility timeout for failures
* ``last_error`` — truncated error from the most recent failed attempt

plus the ``ix_nexus_events_claim`` covering index for the sweep predicate.
Idempotent (add-if-missing) like migration 013.
"""

import sqlalchemy as sa

from alembic import op

revision = "016_outbox_claim_lease"
down_revision = "015_auth_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "nexus_events" not in tables:
        # Fresh database: init_db/create_all owns the schema; nothing to alter.
        return

    cols = {c["name"] for c in inspector.get_columns("nexus_events")}
    if "claimed_at" not in cols:
        op.add_column(
            "nexus_events",
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "claimed_by" not in cols:
        op.add_column(
            "nexus_events",
            sa.Column("claimed_by", sa.String(length=128), nullable=True),
        )
    if "lease_expires_at" not in cols:
        op.add_column(
            "nexus_events",
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "next_retry_at" not in cols:
        op.add_column(
            "nexus_events",
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "last_error" not in cols:
        op.add_column(
            "nexus_events",
            sa.Column("last_error", sa.Text(), nullable=True),
        )

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("nexus_events")}
    if "ix_nexus_events_claim" not in existing_indexes:
        op.create_index(
            "ix_nexus_events_claim",
            "nexus_events",
            ["published_at", "lease_expires_at", "next_retry_at"],
        )
    if "ix_nexus_events_lease_expires_at" not in existing_indexes:
        op.create_index("ix_nexus_events_lease_expires_at", "nexus_events", ["lease_expires_at"])
    if "ix_nexus_events_next_retry_at" not in existing_indexes:
        op.create_index("ix_nexus_events_next_retry_at", "nexus_events", ["next_retry_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nexus_events" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("nexus_events")}
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("nexus_events")}
    for ix in (
        "ix_nexus_events_claim",
        "ix_nexus_events_lease_expires_at",
        "ix_nexus_events_next_retry_at",
    ):
        if ix in existing_indexes:
            op.drop_index(ix, table_name="nexus_events")
    for col in (
        "last_error",
        "next_retry_at",
        "lease_expires_at",
        "claimed_by",
        "claimed_at",
    ):
        if col in cols:
            op.drop_column("nexus_events", col)
