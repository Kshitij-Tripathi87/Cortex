"""Registry of the version 1 API routers.

One owner: a new endpoint module is registered here and nowhere else. Every
route documents the standard error envelope.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    equipment,
    ingestion,
    milestones,
    projects,
    purchase_orders,
    suppliers,
    workspaces,
    world_state,
)
from app.schemas.common import ERROR_RESPONSES

api_router = APIRouter(responses=ERROR_RESPONSES)
api_router.include_router(workspaces.router)
api_router.include_router(projects.router)
api_router.include_router(suppliers.router)
api_router.include_router(equipment.router)
api_router.include_router(purchase_orders.router)
api_router.include_router(milestones.router)
api_router.include_router(ingestion.router)
api_router.include_router(world_state.router)
