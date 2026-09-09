"""v0.8.5-B — Launch onboarding: organizations, workspace org link, user profile fields.

Revision ID: 015_auth_onboarding
Revises: 014_model_registry_governance
Create Date: 2026-09-09

1. core.organizations — commercial tenant root (one workspace per org at
   launch). `plan`/`trial_ends_at` seed the Day-15 billing entitlement model.
2. core.workspaces.organization_id — nullable FK so pre-v0.8.5 rows survive;
   signup always sets it.
3. core.users — full_name, is_active, password_changed_at; password_hash
   widened 128 -> 255 for future hash agility.
4. core.password_resets — single-use reset tokens (SHA-256 hash only).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "015_auth_onboarding"
down_revision = "014_model_registry_governance"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_GEN_RANDOM = sa.text("gen_random_uuid()")


def upgrade() -> None:
    # 1. core.organizations -------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False, server_default="trial"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        schema="core",
    )

    # 2. core.workspaces.organization_id ------------------------------------
    op.add_column(
        "workspaces",
        sa.Column("organization_id", _UUID, nullable=True),
        schema="core",
    )
    op.create_foreign_key(
        "fk_workspaces_organization_id_organizations",
        "workspaces",
        "organizations",
        ["organization_id"],
        ["id"],
        source_schema="core",
        referent_schema="core",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_workspaces_organization_id",
        "workspaces",
        ["organization_id"],
        schema="core",
    )

    # 3. core.users profile fields ------------------------------------------
    op.add_column(
        "users", sa.Column("full_name", sa.String(length=256), nullable=True), schema="core"
    )
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        schema="core",
    )
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=128),
        type_=sa.String(length=255),
        existing_nullable=False,
        schema="core",
    )

    # 4. core.password_resets ------------------------------------------------
    op.create_table(
        "password_resets",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name="fk_password_resets_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_password_resets_token_hash"),
        schema="core",
    )
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"], schema="core")


def downgrade() -> None:
    op.drop_index("ix_password_resets_user_id", table_name="password_resets", schema="core")
    op.drop_table("password_resets", schema="core")
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(length=255),
        type_=sa.String(length=128),
        existing_nullable=False,
        schema="core",
    )
    op.drop_column("users", "password_changed_at", schema="core")
    op.drop_column("users", "is_active", schema="core")
    op.drop_column("users", "full_name", schema="core")
    op.drop_index("ix_workspaces_organization_id", table_name="workspaces", schema="core")
    op.drop_constraint(
        "fk_workspaces_organization_id_organizations",
        "workspaces",
        schema="core",
        type_="foreignkey",
    )
    op.drop_column("workspaces", "organization_id", schema="core")
    op.drop_table("organizations", schema="core")
