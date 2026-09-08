"""Migration 009 — MVP wedge schema.

Creates 7 schemas and ~17 tables with native PostgreSQL UUID (ADR-0001),
organised by domain (ADR-0006). Tables are referenced by the ORM models
in app.modules.{access, supply_chain, disruption, decision, ingestion}.

Schema layout (per ADR-0006):
    core.*           — workspaces, users
    operational.*    — suppliers, components, warehouses, factories,
                       products, customers, edges
    inventory.*      — inventory, bom
    orders.*         — orders, disruption_events
    analytics.*      — impact_reports, backtest_results
    decision.*       — decision_log, decision_memory
    audit.*          — ingestion_log

Down revision: 008_world_state (008 provides the World State Engine tables that 010 hardens).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "009_mvp_wedge_schema"
down_revision = "008_world_state"
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_UUID = postgresql.UUID(as_uuid=True)
_NOW = sa.text("now()")
_GEN_RANDOM = sa.text("gen_random_uuid()")

_SCHEMAS = (
    "core",
    "operational",
    "inventory",
    "orders",
    "analytics",
    "decision",
    "audit",
)


def _ws_fk(referred_schema: str, referred_table: str) -> sa.ForeignKeyConstraint:
    """Standard `workspace_id` FK to core.workspaces.id (CASCADE delete)."""
    return sa.ForeignKeyConstraint(
        "workspace_id",
        f"{referred_schema}.{referred_table}.id",
        ondelete="CASCADE",
        # Match the naming convention in app.infrastructure.database
        name="fk_{table_name}_workspace_id_workspaces",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Upgrade
# ─────────────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # 1. Schemas
    for schema in _SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # 2. core.workspaces ----------------------------------------------------
    op.create_table(
        "workspaces",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column(
            "metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
        schema="core",
    )

    # 3. core.users ---------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default=sa.text("'viewer'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.UniqueConstraint("workspace_id", "email", name="uq_users_workspace_email"),
        schema="core",
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"], schema="core")

    # 4. operational.suppliers ----------------------------------------------
    op.create_table(
        "suppliers",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("lead_time_days", sa.Integer, nullable=False, server_default=sa.text("14")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'active'")),
        sa.Column("risk_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("workspace_id", "name", name="uq_suppliers_workspace_name"),
        schema="operational",
    )
    op.create_index(
        "ix_suppliers_workspace_tier", "suppliers", ["workspace_id", "tier"], schema="operational"
    )

    # 5. operational.components ---------------------------------------------
    op.create_table(
        "components",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("unit_of_measure", sa.String(32), nullable=False, server_default=sa.text("'EA'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("workspace_id", "sku", name="uq_components_workspace_sku"),
        schema="operational",
    )

    # 6. operational.warehouses --------------------------------------------
    op.create_table(
        "warehouses",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("capacity_units", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("workspace_id", "code", name="uq_warehouses_workspace_code"),
        schema="operational",
    )

    # 7. operational.factories ---------------------------------------------
    op.create_table(
        "factories",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("throughput_per_day", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("workspace_id", "code", name="uq_factories_workspace_code"),
        schema="operational",
    )

    # 8. operational.products -----------------------------------------------
    op.create_table(
        "products",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column(
            "factory_id",
            _UUID,
            sa.ForeignKey("operational.factories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("lead_time_days", sa.Integer, nullable=False, server_default=sa.text("7")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("workspace_id", "sku", name="uq_products_workspace_sku"),
        schema="operational",
    )

    # 9. operational.customers ----------------------------------------------
    op.create_table(
        "customers",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("tier", sa.String(16), nullable=True),
        sa.Column("contract_value_annual", sa.Numeric(18, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint("workspace_id", "name", name="uq_customers_workspace_name"),
        schema="operational",
    )

    # 10. operational.edges --------------------------------------------------
    op.create_table(
        "edges",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_type", sa.String(32), nullable=False),
        sa.Column("from_id", _UUID, nullable=False),
        sa.Column("to_type", sa.String(32), nullable=False),
        sa.Column("to_id", _UUID, nullable=False),
        sa.Column("edge_type", sa.String(32), nullable=False),
        sa.Column("weight", sa.Numeric(18, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        schema="operational",
    )
    op.create_index(
        "ix_edges_workspace_from",
        "edges",
        ["workspace_id", "from_type", "from_id"],
        schema="operational",
    )
    op.create_index(
        "ix_edges_workspace_to",
        "edges",
        ["workspace_id", "to_type", "to_id"],
        schema="operational",
    )
    op.create_index(
        "ix_edges_workspace_type", "edges", ["workspace_id", "edge_type"], schema="operational"
    )

    # 11. inventory.inventory ------------------------------------------------
    op.create_table(
        "inventory",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "warehouse_id",
            _UUID,
            sa.ForeignKey("operational.warehouses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            _UUID,
            sa.ForeignKey("operational.components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("safety_stock", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "last_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "warehouse_id",
            "component_id",
            name="uq_inventory_workspace_warehouse_component",
        ),
        schema="inventory",
    )

    # 12. inventory.bom ------------------------------------------------------
    op.create_table(
        "bom",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            _UUID,
            sa.ForeignKey("operational.products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            _UUID,
            sa.ForeignKey("operational.components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "quantity_per_unit", sa.Numeric(18, 4), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.UniqueConstraint(
            "workspace_id",
            "product_id",
            "component_id",
            name="uq_bom_workspace_product_component",
        ),
        schema="inventory",
    )

    # 13. orders.orders ------------------------------------------------------
    op.create_table(
        "orders",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            _UUID,
            sa.ForeignKey("operational.customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            _UUID,
            sa.ForeignKey("operational.products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("order_date", sa.Date, nullable=False),
        sa.Column("requested_delivery_date", sa.Date, nullable=False),
        sa.Column("actual_delivery_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        schema="orders",
    )
    op.create_index(
        "ix_orders_workspace_status", "orders", ["workspace_id", "status"], schema="orders"
    )
    op.create_index(
        "ix_orders_workspace_customer", "orders", ["workspace_id", "customer_id"], schema="orders"
    )

    # 14. orders.disruption_events ------------------------------------------
    op.create_table(
        "disruption_events",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("source_node_type", sa.String(32), nullable=False),
        sa.Column("source_node_id", _UUID, nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'open'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema="orders",
    )
    op.create_index(
        "ix_disruption_events_workspace_status",
        "disruption_events",
        ["workspace_id", "status"],
        schema="orders",
    )
    op.create_index(
        "ix_disruption_events_workspace_started_at",
        "disruption_events",
        ["workspace_id", "started_at"],
        schema="orders",
    )

    # 15. analytics.impact_reports ------------------------------------------
    op.create_table(
        "impact_reports",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "disruption_event_id",
            _UUID,
            sa.ForeignKey("orders.disruption_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("computation_run_id", _UUID, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("confidence_overall", sa.Numeric(6, 4), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        schema="analytics",
    )
    op.create_index(
        "ix_impact_reports_workspace_event",
        "impact_reports",
        ["workspace_id", "disruption_event_id"],
        schema="analytics",
    )

    # 16. analytics.backtest_results ----------------------------------------
    op.create_table(
        "backtest_results",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accuracy", sa.Numeric(6, 4), nullable=False),
        sa.Column("precision", sa.Numeric(6, 4), nullable=False),
        sa.Column("recall", sa.Numeric(6, 4), nullable=False),
        sa.Column("f1", sa.Numeric(6, 4), nullable=False),
        sa.Column("total_predictions", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema="analytics",
    )

    # 17. decision.decision_log ---------------------------------------------
    op.create_table(
        "decision_log",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("core.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "disruption_event_id",
            _UUID,
            sa.ForeignKey("orders.disruption_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recommendation_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(48), nullable=False),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column(
            "contract_version", sa.String(16), nullable=False, server_default=sa.text("'1.0'")
        ),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema="decision",
    )
    op.create_index(
        "ix_decision_log_workspace_event",
        "decision_log",
        ["workspace_id", "disruption_event_id"],
        schema="decision",
    )
    op.create_index(
        "ix_decision_log_workspace_user",
        "decision_log",
        ["workspace_id", "user_id"],
        schema="decision",
    )

    # 18. decision.decision_memory -----------------------------------------
    op.create_table(
        "decision_memory",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decision_log_id",
            _UUID,
            sa.ForeignKey("decision.decision_log.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pattern_signature", sa.String(128), nullable=False),
        sa.Column(
            "outcome_metrics",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        schema="decision",
    )
    op.create_index(
        "ix_decision_memory_workspace",
        "decision_memory",
        ["workspace_id"],
        schema="decision",
    )

    # 19. audit.ingestion_log -----------------------------------------------
    op.create_table(
        "ingestion_log",
        sa.Column("id", _UUID, primary_key=True, server_default=_GEN_RANDOM),
        sa.Column(
            "workspace_id",
            _UUID,
            sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("core.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dataset_type", sa.String(32), nullable=False),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("file_key", sa.String(1024), nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'received'")),
        sa.Column("rows_total", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("rows_accepted", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("rows_rejected", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column(
            "error_log", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        schema="audit",
    )
    op.create_index(
        "ix_ingestion_log_workspace_status",
        "ingestion_log",
        ["workspace_id", "status"],
        schema="audit",
    )
    op.create_index(
        "ix_ingestion_log_workspace_started_at",
        "ingestion_log",
        ["workspace_id", "started_at"],
        schema="audit",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Downgrade
# ─────────────────────────────────────────────────────────────────────────────


def downgrade() -> None:
    # Tables first, then schemas (CASCADE drops tables in advance of DROP SCHEMA
    # but explicit drop gives cleaner migration logs).
    for schema, table in (
        ("audit", "ingestion_log"),
        ("decision", "decision_memory"),
        ("decision", "decision_log"),
        ("analytics", "backtest_results"),
        ("analytics", "impact_reports"),
        ("orders", "disruption_events"),
        ("orders", "orders"),
        ("inventory", "bom"),
        ("inventory", "inventory"),
        ("operational", "edges"),
        ("operational", "customers"),
        ("operational", "products"),
        ("operational", "factories"),
        ("operational", "warehouses"),
        ("operational", "components"),
        ("operational", "suppliers"),
        ("core", "users"),
        ("core", "workspaces"),
    ):
        op.drop_table(table, schema=schema)

    for schema in _SCHEMAS:
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
