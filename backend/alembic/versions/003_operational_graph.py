"""Migration 003 — Operational Graph tables (Phase 3 Program A).

Tables: graph_nodes, graph_edges, graph_snapshots, graph_write_events,
provenance_links. Also adds tenant_id + RLS to the new tables so they
inherit the same tenant isolation as the evidence platform.
"""

import sqlalchemy as sa

from alembic import op

revision = "003_operational_graph"
down_revision = "002_row_level_security"
branch_labels = None
depends_on = None


_TENANT_TABLES = [
    "graph_nodes",
    "graph_edges",
    "graph_snapshots",
    "graph_write_events",
    "provenance_links",
]


def upgrade() -> None:
    # graph_nodes
    op.create_table(
        "graph_nodes",
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("attributes", sa.JSON, nullable=False),
        sa.Column("first_seen_version", sa.Integer, nullable=False),
        sa.Column("last_modified_version", sa.Integer, nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id"),
        sa.UniqueConstraint("workspace_id", "entity_type", "entity_id",
                            name="uq_graph_nodes_workspace_entity"),
    )
    op.create_index("ix_graph_nodes_workspace_id", "graph_nodes", ["workspace_id"])
    op.create_index("ix_graph_nodes_tenant_id", "graph_nodes", ["tenant_id"])

    # graph_edges
    op.create_table(
        "graph_edges",
        sa.Column("edge_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("source_node_id", sa.String(36), nullable=False),
        sa.Column("target_node_id", sa.String(36), nullable=False),
        sa.Column("relationship_type", sa.String(64), nullable=False),
        sa.Column("attributes", sa.JSON, nullable=False),
        sa.Column("first_seen_version", sa.Integer, nullable=False),
        sa.Column("last_modified_version", sa.Integer, nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("edge_id"),
        sa.UniqueConstraint("workspace_id", "source_node_id", "target_node_id",
                            "relationship_type",
                            name="uq_graph_edges_workspace_source_target_rel"),
    )
    op.create_index("ix_graph_edges_workspace_id", "graph_edges", ["workspace_id"])
    op.create_index("ix_graph_edges_tenant_id", "graph_edges", ["tenant_id"])
    op.create_index("ix_graph_edges_source_node_id", "graph_edges", ["source_node_id"])
    op.create_index("ix_graph_edges_target_node_id", "graph_edges", ["target_node_id"])

    # graph_snapshots
    op.create_table(
        "graph_snapshots",
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("prev_snapshot_id", sa.String(36), nullable=True),
        sa.Column("prev_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("node_count", sa.Integer, nullable=False),
        sa.Column("edge_count", sa.Integer, nullable=False),
        sa.Column("source_batch_id", sa.String(36), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("workspace_id", "version",
                            name="uq_graph_snapshots_workspace_version"),
    )
    op.create_index("ix_graph_snapshots_workspace_id", "graph_snapshots", ["workspace_id"])
    op.create_index("ix_graph_snapshots_tenant_id", "graph_snapshots", ["tenant_id"])

    # graph_write_events
    op.create_table(
        "graph_write_events",
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("element_type", sa.String(16), nullable=False),
        sa.Column("element_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("provenance_claim_ids", sa.JSON, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_graph_write_events_workspace_id", "graph_write_events", ["workspace_id"])
    op.create_index("ix_graph_write_events_tenant_id", "graph_write_events", ["tenant_id"])
    op.create_index("ix_graph_write_events_snapshot_id", "graph_write_events", ["snapshot_id"])

    # provenance_links
    op.create_table(
        "provenance_links",
        sa.Column("link_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("graph_element_type", sa.String(16), nullable=False),
        sa.Column("graph_element_id", sa.String(36), nullable=False),
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("link_id"),
        sa.UniqueConstraint("graph_element_type", "graph_element_id", "claim_id",
                            name="uq_provenance_links_element_claim"),
    )
    op.create_index("ix_provenance_links_workspace_id", "provenance_links", ["workspace_id"])
    op.create_index("ix_provenance_links_tenant_id", "provenance_links", ["tenant_id"])
    op.create_index("ix_provenance_links_graph_element_id", "provenance_links", ["graph_element_id"])
    op.create_index("ix_provenance_links_claim_id", "provenance_links", ["claim_id"])

    # Enable + force RLS on new tables
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('app.tenant_id', true)::text)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("provenance_links")
    op.drop_table("graph_write_events")
    op.drop_table("graph_snapshots")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
