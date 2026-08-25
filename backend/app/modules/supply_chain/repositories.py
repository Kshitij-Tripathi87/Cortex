"""Workspace-scoped repositories for supply-chain entities.

Design (per ADR-0006 and the MVP execution plan §2):

- All queries filter by `workspace_id` automatically through the base class.
- `add()` forces `entity.workspace_id = self._workspace_id` so callers
  cannot accidentally cross-write to another tenant.
- Cross-workspace reads or writes are impossible by construction — there is
  no method on this base class that accepts a workspace_id parameter.

The base repository is generic over the ORM model type. Concrete classes
per entity type live below; they add small entity-specific helpers
(e.g., SupplierRepository.get_by_name) but inherit the workspace-scoped
list/get/delete surface.
"""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.supply_chain.models import (
    BillOfMaterials,
    Component,
    Customer,
    DisruptionEvent,
    Edge,
    Factory,
    Inventory,
    Order,
    Product,
    Supplier,
    Warehouse,
)

ModelT = TypeVar("ModelT")


class WorkspaceScopedRepository[ModelT]:
    """Base class — every query automatically filters by current workspace_id."""

    _model: type[ModelT]

    def __init__(self, session: AsyncSession, workspace_id: UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def _scoped(self) -> select:
        return select(self._model).where(self._model.workspace_id == self._workspace_id)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[ModelT]:
        stmt = self._scoped().limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def get(self, entity_id: UUID) -> ModelT | None:
        stmt = self._scoped().where(self._model.id == entity_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, entity: ModelT) -> ModelT:
        # workspace_id is forced; callers cannot override.
        entity.workspace_id = self._workspace_id
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete(self, entity_id: UUID) -> bool:
        stmt = self._scoped().where(self._model.id == entity_id)
        result = await self._session.execute(stmt)
        obj = result.scalar_one_or_none()
        if obj is None:
            return False
        await self._session.delete(obj)
        return True

    async def count(self) -> int:
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(self._model)
            .where(self._model.workspace_id == self._workspace_id)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())


# ─────────────────────────────────────────────────────────────────────────────
# Concrete entity repositories — small entity-specific helpers go below.
# ─────────────────────────────────────────────────────────────────────────────


class SupplierRepository(WorkspaceScopedRepository[Supplier]):
    _model = Supplier

    async def get_by_name(self, name: str) -> Supplier | None:
        stmt = self._scoped().where(Supplier.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class ComponentRepository(WorkspaceScopedRepository[Component]):
    _model = Component

    async def get_by_sku(self, sku: str) -> Component | None:
        stmt = self._scoped().where(Component.sku == sku)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_sku(self, skus: list[str]) -> list[Component]:
        if not skus:
            return []
        stmt = self._scoped().where(Component.sku.in_(skus))
        result = await self._session.execute(stmt)
        return list(result.scalars())


class WarehouseRepository(WorkspaceScopedRepository[Warehouse]):
    _model = Warehouse

    async def get_by_code(self, code: str) -> Warehouse | None:
        stmt = self._scoped().where(Warehouse.code == code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_code(self, codes: list[str]) -> list[Warehouse]:
        if not codes:
            return []
        stmt = self._scoped().where(Warehouse.code.in_(codes))
        result = await self._session.execute(stmt)
        return list(result.scalars())


class FactoryRepository(WorkspaceScopedRepository[Factory]):
    _model = Factory

    async def get_by_code(self, code: str) -> Factory | None:
        stmt = self._scoped().where(Factory.code == code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_code(self, codes: list[str]) -> list[Factory]:
        if not codes:
            return []
        stmt = self._scoped().where(Factory.code.in_(codes))
        result = await self._session.execute(stmt)
        return list(result.scalars())


class ProductRepository(WorkspaceScopedRepository[Product]):
    _model = Product

    async def get_by_sku(self, sku: str) -> Product | None:
        stmt = self._scoped().where(Product.sku == sku)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_sku(self, skus: list[str]) -> list[Product]:
        if not skus:
            return []
        stmt = self._scoped().where(Product.sku.in_(skus))
        result = await self._session.execute(stmt)
        return list(result.scalars())


class CustomerRepository(WorkspaceScopedRepository[Customer]):
    _model = Customer

    async def get_by_name(self, name: str) -> Customer | None:
        stmt = self._scoped().where(Customer.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_by_name(self, names: list[str]) -> list[Customer]:
        if not names:
            return []
        stmt = self._scoped().where(Customer.name.in_(names))
        result = await self._session.execute(stmt)
        return list(result.scalars())


class EdgeRepository(WorkspaceScopedRepository[Edge]):
    _model = Edge

    async def out_edges(self, node_type: str, node_id: UUID) -> list[Edge]:
        """Edges where (from_type, from_id) == (node_type, node_id)."""
        stmt = self._scoped().where(
            Edge.from_type == node_type,
            Edge.from_id == node_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def in_edges(self, node_type: str, node_id: UUID) -> list[Edge]:
        """Edges where (to_type, to_id) == (node_type, node_id)."""
        stmt = self._scoped().where(
            Edge.to_type == node_type,
            Edge.to_id == node_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())


class InventoryRepository(WorkspaceScopedRepository[Inventory]):
    _model = Inventory

    async def get_for(
        self,
        warehouse_id: UUID,
        component_id: UUID,
    ) -> Inventory | None:
        stmt = self._scoped().where(
            Inventory.warehouse_id == warehouse_id,
            Inventory.component_id == component_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class BomRepository(WorkspaceScopedRepository[BillOfMaterials]):
    _model = BillOfMaterials

    async def get_for(
        self,
        product_id: UUID,
        component_id: UUID,
    ) -> BillOfMaterials | None:
        stmt = self._scoped().where(
            BillOfMaterials.product_id == product_id,
            BillOfMaterials.component_id == component_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class OrderRepository(WorkspaceScopedRepository[Order]):
    _model = Order


class DisruptionEventRepository(WorkspaceScopedRepository[DisruptionEvent]):
    _model = DisruptionEvent

    async def list_open(self, *, limit: int = 50) -> list[DisruptionEvent]:
        stmt = (
            self._scoped()
            .where(DisruptionEvent.status == "open")
            .order_by(DisruptionEvent.started_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())


__all__ = [
    "BomRepository",
    "ComponentRepository",
    "CustomerRepository",
    "DisruptionEventRepository",
    "EdgeRepository",
    "FactoryRepository",
    "InventoryRepository",
    "OrderRepository",
    "ProductRepository",
    "SupplierRepository",
    "WarehouseRepository",
    "WorkspaceScopedRepository",
]
