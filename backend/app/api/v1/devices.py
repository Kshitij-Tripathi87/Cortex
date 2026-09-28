"""Device Mesh API — registration, presence, ownership (Day 25).

The phone is a capability-bearing mesh node, not a UI client. Every device
is scoped to its owner: owner_id must match the authenticated principal.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.devices.service import (
    DeviceMeshService,
    DeviceNotFoundError,
    DeviceOwnershipError,
)

router = APIRouter()


def _svc(session: AsyncSession) -> DeviceMeshService:
    return DeviceMeshService(session)


class DeviceRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str | None = Field(default=None, max_length=64)
    platform: str = Field(min_length=1, max_length=32)
    agent_version: str = Field(default="v1.0", max_length=32)
    capabilities: list[str] = Field(default_factory=list)
    public_key: str | None = Field(default=None, max_length=512)


class DeviceHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(default=None, max_length=32)


@router.post("/devices", status_code=201)
async def register_device(
    body: DeviceRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Register (or re-enroll) this device in the mesh."""
    svc = _svc(session)
    try:
        device = await svc.register_device(
            tenant_id=str(auth.user_id or "anonymous"),
            owner_id=str(auth.user_id or "anonymous"),
            platform=body.platform,
            agent_version=body.agent_version,
            capabilities=body.capabilities,
            public_key=body.public_key,
            device_id=body.device_id,
        )
        await session.commit()
    except DeviceOwnershipError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _envelope(request, {"device": device})


@router.get("/devices")
async def list_devices(
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    devices = await _svc(session).list_devices(owner_id=str(auth.user_id or "anonymous"))
    return _envelope(request, {"devices": devices, "count": len(devices)})


@router.get("/devices/{device_id}")
async def get_device(
    device_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    device = await _svc(session).get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if device["owner_id"] != str(auth.user_id or "anonymous"):
        raise HTTPException(status_code=403, detail="device belongs to another owner")
    return _envelope(request, {"device": device})


@router.post("/devices/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: str,
    body: DeviceHeartbeatRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        device = await _svc(session).heartbeat(
            device_id,
            owner_id=str(auth.user_id or "anonymous"),
            status=body.status,
        )
        await session.commit()
    except DeviceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DeviceOwnershipError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _envelope(request, {"device": device})


def _envelope(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    return {"data": data}
