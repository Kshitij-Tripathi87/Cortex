"""Propagation engine — deterministic BFS over the supply-chain graph.

Walks from a disrupted supplier downstream through the canonical edge set
(see :class:`EdgeType` in ``app.common.enums``):

    supplier --supplies--> component           (supplies)
    component --stored_in--> warehouse         (stored_in)
    factory --consumes--> component            (consumes)
    factory --makes--> product                 (makes)
    customer --orders--> product               (orders)

BOM expansion is folded in (component -> product via ``inventory.bom``) so the
blast radius reaches finished products even when the explicit ``makes`` edge is
absent. Inventory buffers are consulted to expose which warehouses hold the
affected component and how many days that stock covers.

Determinism guarantees:
  * FIFO BFS by hop with **sorted** neighbor iteration — same inputs always
    produce the same ``PropagationResult`` (no nondeterministic dict order).
  * No wall-clock, no RNG.
  * Attenuation is a fixed per-hop factor (0.85 per ADR-0003 alignment with the
    existing graph propagation rules) applied multiplicatively to exposure.

Returns :class:`PropagationResult`. This module is pure: it never touches the
database or the network.
"""

from __future__ import annotations

from collections import deque
from uuid import UUID

from app.modules.disruption.engines.types import (
    AffectedComponent,
    AffectedOrder,
    AffectedProduct,
    AffectedWarehouse,
    BomData,
    EdgeData,
    OrderData,
    PropagationResult,
    SupplyChainSnapshot,
)

# Edge-type names (kept as plain strings to avoid importing the enum and pulling
# the whole graph module; these mirror app.common.enums.EdgeType values).
_SUPPLIES = "supplies"
_STORED_IN = "stored_in"
_CONSUMES = "consumes"
_MAKES = "makes"
_ORDERS = "orders"

# Fixed attenuation per hop — multiplicative exposure decay (0.85 matches the
# existing graph propagation rules; documented here for traceability).
ATTENUATION_PER_HOP: float = 0.85
MAX_HOP: int = 8


def _build_adjacency(
    edges: tuple[EdgeData, ...],
) -> dict[tuple[str, UUID], list[EdgeData]]:
    """Group edges by ``(from_type, from_id)`` for downstream BFS.

    Neighbors within a group are sorted by a stable key so iteration order is
    deterministic.
    """
    adjacency: dict[tuple[str, UUID], list[EdgeData]] = {}
    for edge in edges:
        adjacency.setdefault((edge.from_type, edge.from_id), []).append(edge)
    for group in adjacency.values():
        group.sort(key=lambda e: (e.edge_type, str(e.to_id), str(e.from_id)))
    return adjacency


def _component_lookup(
    snapshot: SupplyChainSnapshot,
) -> dict[UUID, tuple[str, str]]:
    return {c.id: (c.sku, c.name) for c in snapshot.components}


def _product_lookup(
    snapshot: SupplyChainSnapshot,
) -> dict[UUID, tuple[str, str]]:
    return {p.id: (p.sku, p.name) for p in snapshot.products}


def _bom_by_component(
    bom: tuple[BomData, ...],
) -> dict[UUID, list[BomData]]:
    by: dict[UUID, list[BomData]] = {}
    for b in bom:
        by.setdefault(b.component_id, []).append(b)
    for group in by.values():
        group.sort(key=lambda b: str(b.product_id))
    return by


def _inventory_by_component(
    snapshot: SupplyChainSnapshot,
) -> dict[UUID, list]:
    by: dict[UUID, list] = {}
    for inv in snapshot.inventory:
        by.setdefault(inv.component_id, []).append(inv)
    for group in by.values():
        group.sort(key=lambda i: str(i.warehouse_id))
    return by


def propagate(
    snapshot: SupplyChainSnapshot,
    supplier_id: UUID,
) -> PropagationResult:
    """BFS from ``supplier_id`` downstream to components, warehouses and products.

    Open orders (`status` in {pending, confirmed, in_production}) on any
    affected product are surfaced as ``open_orders_at_risk``.

    If the supplier is unknown or supplies nothing, an empty (but well-formed)
    :class:`PropagationResult` is returned — the brief still renders, it simply
    reports "no downstream impact".
    """
    adjacency = _build_adjacency(snapshot.edges)
    comp_lookup = _component_lookup(snapshot)
    prod_lookup = _product_lookup(snapshot)
    bom_by_comp = _bom_by_component(snapshot.bom)
    inv_by_comp = _inventory_by_component(snapshot)

    affected_components: list[AffectedComponent] = []
    affected_products: list[AffectedProduct] = []
    traversed: set[str] = set()

    # Hop 0: supplier. Hop 1+: components, warehouses, factories->products.
    # visited keyed by (node_type, node_id)
    visited: set[tuple[str, UUID]] = {("supplier", supplier_id)}
    queue: deque[tuple[str, UUID, int, float, tuple[str, ...]]] = deque(
        [("supplier", supplier_id, 0, 1.0, ())]
    )
    max_hop = 0
    affected_component_ids: set[UUID] = set()

    while queue:
        node_type, node_id, hop, exposure, path = queue.popleft()
        if hop > MAX_HOP:
            continue
        max_hop = max(max_hop, hop)

        for edge in adjacency.get((node_type, node_id), []):
            traversed.add(edge.edge_type)
            ntype = edge.to_type
            nid = edge.to_id
            edge_path = path + (edge.edge_type,)
            child_hop = hop + 1
            child_exposure = (
                exposure * ATTENUATION_PER_HOP
                if edge.weight is None
                else exposure * float(edge.weight)
            )
            child_exposure = max(0.0, min(1.0, child_exposure))

            key = (ntype, nid)
            if key in visited:
                continue
            visited.add(key)

            if ntype == "component" and edge.edge_type == _SUPPLIES:
                # Component directly supplied by the disrupted supplier (or its
                # downstream chain). Record it and continue walking.
                sku_name = comp_lookup.get(nid, ("", ""))
                affected_components.append(
                    AffectedComponent(
                        component_id=nid,
                        sku=sku_name[0],
                        name=sku_name[1],
                        hop=child_hop,
                        attenuated_exposure=child_exposure,
                        edge_path=edge_path,
                    )
                )
                affected_component_ids.add(nid)
                queue.append((ntype, nid, child_hop, child_exposure, edge_path))

            elif ntype == "warehouse" and edge.edge_type == _STORED_IN:
                # Warehouse storing an affected component — walk forward to it.
                queue.append((ntype, nid, child_hop, child_exposure, edge_path))

            elif ntype == "factory" and edge.edge_type in (_CONSUMES, _MAKES):
                queue.append((ntype, nid, child_hop, child_exposure, edge_path))

            elif ntype == "product" and edge.edge_type == _MAKES:
                sku_name = prod_lookup.get(nid, ("", ""))
                # The component is whichever affected component the factory
                # consumed to make this product (best-effort: pick the first
                # affected component in BOM for traceability).
                bottleneck = _bottleneck_component(nid, affected_component_ids, bom_by_comp)
                qpu = _qty_per_unit(nid, bottleneck, bom_by_comp)
                affected_products.append(
                    AffectedProduct(
                        product_id=nid,
                        sku=sku_name[0],
                        name=sku_name[1],
                        component_id=bottleneck,
                        qty_needed_per_unit=qpu,
                        hop=child_hop,
                    )
                )

    # BOM-driven product expansion: any product consuming an affected component
    # is also at risk, even without an explicit ``makes`` edge.
    already_products = {p.product_id for p in affected_products}
    for comp_id in sorted(affected_component_ids, key=str):
        for bom in bom_by_comp.get(comp_id, []):
            if bom.product_id in already_products:
                continue
            sku_name = prod_lookup.get(bom.product_id, ("", ""))
            affected_products.append(
                AffectedProduct(
                    product_id=bom.product_id,
                    sku=sku_name[0],
                    name=sku_name[1],
                    component_id=comp_id,
                    qty_needed_per_unit=bom.quantity_per_unit,
                    hop=1,
                )
            )
            already_products.add(bom.product_id)

    affected_products.sort(key=lambda p: (p.hop, str(p.product_id)))

    # Warehouses holding affected components.
    affected_warehouses: list[AffectedWarehouse] = []
    for comp_id in sorted(affected_component_ids, key=str):
        for inv in inv_by_comp.get(comp_id, []):
            affected_warehouses.append(
                AffectedWarehouse(
                    warehouse_id=inv.warehouse_id,
                    component_id=comp_id,
                    quantity=inv.quantity,
                    safety_stock=inv.safety_stock,
                    daily_usage=inv.daily_usage,
                    coverage_days=inv.coverage_days,
                )
            )
    affected_warehouses.sort(key=lambda w: (str(w.component_id), str(w.warehouse_id)))

    # Open orders on affected products.
    affected_product_ids = {p.product_id for p in affected_products}
    open_orders = _open_orders_for_products(snapshot.orders, affected_product_ids)

    return PropagationResult(
        source_supplier_id=supplier_id,
        affected_components=tuple(affected_components),
        affected_products=tuple(affected_products),
        affected_warehouses=tuple(affected_warehouses),
        open_orders_at_risk=tuple(open_orders),
        max_hop=max_hop,
        traversed_edge_types=tuple(sorted(traversed)),
    )


def _bottleneck_component(
    product_id: UUID,
    affected_component_ids: set[UUID],
    bom_by_comp: dict[UUID, list[BomData]],
) -> UUID:
    """Return the first affected component in the product's BOM (deterministic)."""
    for comp_id in sorted(affected_component_ids, key=str):
        for bom in bom_by_comp.get(comp_id, []):
            if bom.product_id == product_id:
                return comp_id
    return (
        next(iter(sorted(affected_component_ids, key=str)))
        if affected_component_ids
        else product_id
    )


def _qty_per_unit(
    product_id: UUID,
    component_id: UUID,
    bom_by_comp: dict[UUID, list[BomData]],
) -> float:
    for bom in bom_by_comp.get(component_id, []):
        if bom.product_id == product_id:
            return bom.quantity_per_unit
    return 1.0


def _open_orders_for_products(
    orders: tuple[OrderData, ...],
    product_ids: set[UUID],
) -> list[AffectedOrder]:
    """Open orders = status in {pending, confirmed, in_production} for at-risk products."""
    open_statuses = {"pending", "confirmed", "in_production"}
    matched = [
        AffectedOrder(
            order_id=o.id,
            customer_id=o.customer_id,
            product_id=o.product_id,
            quantity=o.quantity,
            status=o.status,
        )
        for o in orders
        if o.product_id in product_ids and o.status in open_statuses
    ]
    matched.sort(key=lambda o: str(o.order_id))
    return matched


__all__ = ["ATTENUATION_PER_HOP", "MAX_HOP", "propagate"]
