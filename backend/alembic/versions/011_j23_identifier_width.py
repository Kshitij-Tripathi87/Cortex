"""J.2.3 — Widen world-state identifier columns to VARCHAR(64).

Revision ID: 011_j23_identifier_width
Revises: 010_j23_repository_hardening
Create Date: 2026-08-18 00:00:00.000000

The application generates prefixed identifiers (e.g. `ws_<uuid7>` = 39 chars,
`world_<workspace_id>` = up to 44 chars) that exceed VARCHAR(36). SQLite does
not enforce string lengths, so this only surfaced against real PostgreSQL.

Columns widened in all five world-state tables:
- world_states.world_id, workspace_id
- world_state_events.world_id, workspace_id
- world_snapshots.world_id, workspace_id
- world_versions.world_id, workspace_id
- world_metadata.workspace_id, world_id, parent_world_id
"""
import sqlalchemy as sa

from alembic import op

revision = '011_j23_identifier_width'
down_revision = '010_j23_repository_hardening'
branch_labels = None
depends_on = None

_TABLES = (
    ('world_states', ('world_id', 'workspace_id')),
    ('world_state_events', ('world_id', 'workspace_id')),
    ('world_snapshots', ('world_id', 'workspace_id')),
    ('world_versions', ('world_id', 'workspace_id')),
    ('world_metadata', ('workspace_id', 'world_id', 'parent_world_id')),
)


def upgrade() -> None:
    for table, columns in _TABLES:
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.String(length=36),
                type_=sa.String(length=64),
                existing_nullable=False if column != 'parent_world_id' else True,
            )


def downgrade() -> None:
    for table, columns in reversed(_TABLES):
        for column in reversed(columns):
            op.alter_column(
                table,
                column,
                existing_type=sa.String(length=64),
                type_=sa.String(length=36),
                existing_nullable=False if column != 'parent_world_id' else True,
            )
