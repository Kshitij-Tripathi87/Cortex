"""020 — P1/P2 manufacturing planning data model.

Adds explicit inventory quantity semantics, revisioned multi-level BOM records,
manufacturing production orders, dated purchase-order lines, and workspace UOM
conversions. Existing customer-order and flat-BOM tables remain unchanged.

Revision ID: 020_p1_p2_operational_planning
Revises: 019_audit_subject_id_width
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "020_p1_p2_operational_planning"
down_revision = "019_audit_subject_id_width"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def _table_exists(schema: str, table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names(schema=schema)


def _columns(schema: str, table: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table, schema=schema)
    }


def upgrade() -> None:
    # Existing inventory.quantity and safety_stock were integer-valued. Numeric
    # preserves existing values while allowing fractional units of measure.
    if _table_exists("inventory", "inventory"):
        columns = _columns("inventory", "inventory")
        for column_name in ("quantity", "safety_stock"):
            if column_name in columns:
                op.alter_column(
                    "inventory",
                    column_name,
                    schema="inventory",
                    existing_type=sa.Integer(),
                    type_=sa.Numeric(18, 4),
                    postgresql_using=f"{column_name}::numeric(18,4)",
                )
        if "reserved_quantity" not in columns:
            op.add_column(
                "inventory",
                sa.Column(
                    "reserved_quantity", sa.Numeric(18, 4),
                    nullable=False, server_default=sa.text("0"),
                ),
                schema="inventory",
            )
        if "blocked_quantity" not in columns:
            op.add_column(
                "inventory",
                sa.Column(
                    "blocked_quantity", sa.Numeric(18, 4),
                    nullable=False, server_default=sa.text("0"),
                ),
                schema="inventory",
            )
        if "quantity_basis" not in columns:
            op.add_column(
                "inventory",
                sa.Column(
                    "quantity_basis", sa.String(32),
                    nullable=False, server_default=sa.text("'physical_on_hand'"),
                ),
                schema="inventory",
            )
        if "basis_excludes_reserved" not in columns:
            op.add_column(
                "inventory",
                sa.Column("basis_excludes_reserved", sa.Boolean(), nullable=True),
                schema="inventory",
            )
        if "basis_excludes_blocked" not in columns:
            op.add_column(
                "inventory",
                sa.Column("basis_excludes_blocked", sa.Boolean(), nullable=True),
                schema="inventory",
            )

    if not _table_exists("inventory", "bom_revisions"):
        op.create_table(
            "bom_revisions",
            sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", _UUID, sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_item_type", sa.String(32), nullable=False),
            sa.Column("parent_item_id", _UUID, nullable=False),
            sa.Column("revision_code", sa.String(64), nullable=False),
            sa.Column("facility_id", _UUID, sa.ForeignKey("operational.factories.id", ondelete="SET NULL"), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("source_ref", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            schema="inventory",
        )
        op.create_index(
            "ix_bom_revisions_workspace_parent",
            "bom_revisions",
            ["workspace_id", "parent_item_type", "parent_item_id"],
            schema="inventory",
        )

    if not _table_exists("inventory", "bom_lines"):
        op.create_table(
            "bom_lines",
            sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", _UUID, sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("revision_id", _UUID, sa.ForeignKey("inventory.bom_revisions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("line_code", sa.String(64), nullable=False),
            sa.Column("child_item_type", sa.String(32), nullable=False),
            sa.Column("child_item_id", _UUID, nullable=False),
            sa.Column("usage_quantity", sa.Numeric(18, 6), nullable=False),
            sa.Column("usage_uom", sa.String(32), nullable=False),
            sa.Column("child_base_uom", sa.String(32), nullable=False),
            sa.Column("child_is_assembly", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("scrap_factor", sa.Numeric(12, 6), nullable=True),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("source_ref", sa.String(512), nullable=True),
            sa.UniqueConstraint("workspace_id", "revision_id", "line_code", name="uq_bom_lines_workspace_revision_line"),
            schema="inventory",
        )
        op.create_index(
            "ix_bom_lines_workspace_revision",
            "bom_lines",
            ["workspace_id", "revision_id"],
            schema="inventory",
        )

    if not _table_exists("inventory", "uom_conversions"):
        op.create_table(
            "uom_conversions",
            sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", _UUID, sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("from_uom", sa.String(32), nullable=False),
            sa.Column("to_uom", sa.String(32), nullable=False),
            sa.Column("factor", sa.Numeric(24, 12), nullable=False),
            sa.Column("source_ref", sa.String(512), nullable=True),
            sa.UniqueConstraint("workspace_id", "from_uom", "to_uom", name="uq_uom_conversions_workspace_pair"),
            schema="inventory",
        )

    if not _table_exists("orders", "production_orders"):
        op.create_table(
            "production_orders",
            sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", _UUID, sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("order_number", sa.String(128), nullable=False),
            sa.Column("factory_id", _UUID, sa.ForeignKey("operational.factories.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("warehouse_id", _UUID, sa.ForeignKey("operational.warehouses.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("item_type", sa.String(32), nullable=False),
            sa.Column("item_id", _UUID, nullable=False),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
            sa.Column("order_uom", sa.String(32), nullable=False),
            sa.Column("item_base_uom", sa.String(32), nullable=False),
            sa.Column("material_need_at", sa.Date(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("bom_revision_id", _UUID, sa.ForeignKey("inventory.bom_revisions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_ref", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("workspace_id", "order_number", name="uq_production_orders_workspace_number"),
            schema="orders",
        )
        op.create_index(
            "ix_production_orders_workspace_need",
            "production_orders",
            ["workspace_id", "material_need_at"],
            schema="orders",
        )

    if not _table_exists("orders", "purchase_order_lines"):
        op.create_table(
            "purchase_order_lines",
            sa.Column("id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("workspace_id", _UUID, sa.ForeignKey("core.workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("po_number", sa.String(128), nullable=False),
            sa.Column("line_number", sa.String(32), nullable=False),
            sa.Column("supplier_id", _UUID, sa.ForeignKey("operational.suppliers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("warehouse_id", _UUID, sa.ForeignKey("operational.warehouses.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("component_id", _UUID, sa.ForeignKey("operational.components.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("ordered_quantity", sa.Numeric(18, 4), nullable=False),
            sa.Column("received_quantity", sa.Numeric(18, 4), nullable=False, server_default=sa.text("0")),
            sa.Column("open_quantity", sa.Numeric(18, 4), nullable=True),
            sa.Column("expected_date", sa.Date(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("uom", sa.String(32), nullable=False),
            sa.Column("source_ref", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("workspace_id", "po_number", "line_number", name="uq_purchase_order_lines_workspace_line"),
            schema="orders",
        )
        op.create_index(
            "ix_purchase_order_lines_workspace_receipt",
            "purchase_order_lines",
            ["workspace_id", "expected_date"],
            schema="orders",
        )


def downgrade() -> None:
    # Additive tables can be removed. Existing inventory values are not narrowed
    # back to integers because doing so could truncate fractional values.
    for table_name in ("purchase_order_lines", "production_orders"):
        if _table_exists("orders", table_name):
            op.drop_table(table_name, schema="orders")
    for table_name in ("uom_conversions", "bom_lines", "bom_revisions"):
        if _table_exists("inventory", table_name):
            op.drop_table(table_name, schema="inventory")
    if _table_exists("inventory", "inventory"):
        columns = _columns("inventory", "inventory")
        for column_name in (
            "basis_excludes_blocked",
            "basis_excludes_reserved",
            "quantity_basis",
            "blocked_quantity",
            "reserved_quantity",
        ):
            if column_name in columns:
                op.drop_column("inventory", column_name, schema="inventory")
