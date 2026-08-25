"""World State Engine tables

Revision ID: 008_world_state
Revises: 007
Create Date: 2026-08-08 21:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = '008_world_state'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'world_states',
        sa.Column('state_id', sa.String(length=36), nullable=False),
        sa.Column('world_id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('graph_version', sa.Integer(), nullable=False),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('state_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint('state_id'),
        sa.UniqueConstraint('world_id', 'version', name='uq_world_states_world_version'),
    )
    op.create_index('ix_world_states_world_id', 'world_states', ['world_id'], unique=False)
    op.create_index('ix_world_states_workspace_id', 'world_states', ['workspace_id'], unique=False)
    op.create_index('ix_world_states_version', 'world_states', ['version'], unique=False)
    op.create_index('ix_world_states_state_hash', 'world_states', ['state_hash'], unique=False)

    op.create_table(
        'world_state_events',
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('world_id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('entity_type', sa.String(length=64), nullable=False),
        sa.Column('entity_id', sa.String(length=64), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('caused_by_event_id', sa.String(length=36), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index('ix_world_state_events_workspace_id', 'world_state_events', ['workspace_id'], unique=False)
    op.create_index('ix_world_state_events_entity', 'world_state_events', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_world_state_events_event_type', 'world_state_events', ['event_type'], unique=False)
    op.create_index('ix_world_state_events_occurred_at', 'world_state_events', ['occurred_at'], unique=False)
    op.create_index('ix_world_state_events_world_id', 'world_state_events', ['world_id'], unique=False)

    op.create_table(
        'world_snapshots',
        sa.Column('snapshot_id', sa.String(length=36), nullable=False),
        sa.Column('world_id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('graph_version', sa.Integer(), nullable=False),
        sa.Column('state_hash', sa.String(length=64), nullable=False),
        sa.Column('variable_count', sa.Integer(), nullable=False),
        sa.Column('is_archive', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint('snapshot_id'),
    )
    op.create_index('ix_world_snapshots_workspace_id', 'world_snapshots', ['workspace_id'], unique=False)
    op.create_index('ix_world_snapshots_world_id', 'world_snapshots', ['world_id'], unique=False)
    op.create_index('ix_world_snapshots_version', 'world_snapshots', ['version'], unique=False)
    op.create_index('ix_world_snapshots_state_hash', 'world_snapshots', ['state_hash'], unique=False)

    op.create_table(
        'world_versions',
        sa.Column('version_id', sa.String(length=36), nullable=False),
        sa.Column('world_id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('graph_version', sa.Integer(), nullable=False),
        sa.Column('state_hash', sa.String(length=64), nullable=False),
        sa.Column('event_id', sa.String(length=36), nullable=True),
        sa.Column('parent_version_id', sa.String(length=36), nullable=True),
        sa.Column('source', sa.String(length=64), nullable=False, server_default='projection'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint('version_id'),
        sa.UniqueConstraint('world_id', 'version', name='uq_world_versions_world_version'),
    )
    op.create_index('ix_world_versions_workspace_id', 'world_versions', ['workspace_id'], unique=False)
    op.create_index('ix_world_versions_world_id', 'world_versions', ['world_id'], unique=False)
    op.create_index('ix_world_versions_version', 'world_versions', ['version'], unique=False)
    op.create_index('ix_world_versions_event_id', 'world_versions', ['event_id'], unique=False)
    op.create_index('ix_world_versions_created_at', 'world_versions', ['created_at'], unique=False)

    op.create_table(
        'world_metadata',
        sa.Column('metadata_id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('world_id', sa.String(length=36), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('graph_version', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('parent_world_id', sa.String(length=36), nullable=True),
        sa.Column('parent_version', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("ARRAY[]::varchar[]")),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint('metadata_id'),
    )
    op.create_index('ix_world_metadata_workspace_id', 'world_metadata', ['workspace_id'], unique=False)
    op.create_index('ix_world_metadata_world_id', 'world_metadata', ['world_id'], unique=False)
    op.create_index('ix_world_metadata_version', 'world_metadata', ['version'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_world_metadata_version', table_name='world_metadata')
    op.drop_index('ix_world_metadata_world_id', table_name='world_metadata')
    op.drop_index('ix_world_metadata_workspace_id', table_name='world_metadata')
    op.drop_table('world_metadata')

    op.drop_index('ix_world_versions_created_at', table_name='world_versions')
    op.drop_index('ix_world_versions_event_id', table_name='world_versions')
    op.drop_index('ix_world_versions_version', table_name='world_versions')
    op.drop_index('ix_world_versions_world_id', table_name='world_versions')
    op.drop_index('ix_world_versions_workspace_id', table_name='world_versions')
    op.drop_table('world_versions')

    op.drop_index('ix_world_snapshots_state_hash', table_name='world_snapshots')
    op.drop_index('ix_world_snapshots_version', table_name='world_snapshots')
    op.drop_index('ix_world_snapshots_world_id', table_name='world_snapshots')
    op.drop_index('ix_world_snapshots_workspace_id', table_name='world_snapshots')
    op.drop_table('world_snapshots')

    op.drop_index('ix_world_state_events_world_id', table_name='world_state_events')
    op.drop_index('ix_world_state_events_occurred_at', table_name='world_state_events')
    op.drop_index('ix_world_state_events_event_type', table_name='world_state_events')
    op.drop_index('ix_world_state_events_entity', table_name='world_state_events')
    op.drop_index('ix_world_state_events_workspace_id', table_name='world_state_events')
    op.drop_table('world_state_events')

    op.drop_index('ix_world_states_state_hash', table_name='world_states')
    op.drop_index('ix_world_states_version', table_name='world_states')
    op.drop_index('ix_world_states_workspace_id', table_name='world_states')
    op.drop_table('world_states')
