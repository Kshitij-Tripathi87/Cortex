"""Supply-chain domain — operational+inventory+orders schemas (ADR-0006).

Public re-exports for API/service code:

    from app.modules.supply_chain import (
        Supplier, Component, Warehouse, Factory, Product, Customer, Edge,
        Inventory, BillOfMaterials, Order, DisruptionEvent,
        SupplierRepository, ComponentRepository, ...
    )
"""

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
from app.modules.supply_chain.repositories import (
    BomRepository,
    ComponentRepository,
    CustomerRepository,
    DisruptionEventRepository,
    EdgeRepository,
    FactoryRepository,
    InventoryRepository,
    OrderRepository,
    ProductRepository,
    SupplierRepository,
    WarehouseRepository,
    WorkspaceScopedRepository,
)

__all__ = [
    "BillOfMaterials",
    "BomRepository",
    "Component",
    "ComponentRepository",
    "Customer",
    "CustomerRepository",
    "DisruptionEvent",
    "DisruptionEventRepository",
    "Edge",
    "EdgeRepository",
    "Factory",
    "FactoryRepository",
    "Inventory",
    "InventoryRepository",
    "Order",
    "OrderRepository",
    "Product",
    "ProductRepository",
    "Supplier",
    "SupplierRepository",
    "Warehouse",
    "WarehouseRepository",
    "WorkspaceScopedRepository",
]
