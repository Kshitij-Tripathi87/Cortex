"""Device Mesh service — registration, presence, and ownership (Day 25).

The phone is a capability-bearing Vanessa device: it registers like any
other mesh node and is scoped to its owner. The API layer enforces
ownership (owner_id must match the authenticated principal) — a device is
never shared across owners.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.devices.models import MobileDeviceDB

ALLOWED_CAPABILITIES = {
    "voice",
    "notifications",
    "approval",
    "display",
    "terminal",
    "filesystem",
    "tasks",
}

VALID_STATUSES = {"ONLINE", "OFFLINE", "BUSY", "DEGRADED"}


class DeviceOwnershipError(Exception):
    """The authenticated principal does not own the device."""


class DeviceNotFoundError(Exception):
    """The device does not exist."""


def _now() -> datetime:
    return datetime.now(UTC)


class DeviceMeshService:
    """Registration + presence for the DeviceMesh."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_device(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        platform: str,
        agent_version: str = "v1.0",
        capabilities: list[str] | None = None,
        public_key: str | None = None,
        device_id: str | None = None,
    ) -> dict[str, Any]:
        """Register (or re-enroll) a device. Re-registration with the same
        device_id updates the record instead of duplicating it."""
        clean_caps = [c for c in (capabilities or []) if c in ALLOWED_CAPABILITIES]
        did = device_id or f"dev-{uuid7()}"

        existing = await self.get_device(did) if device_id else None
        if existing is not None:
            if existing["owner_id"] != owner_id:
                raise DeviceOwnershipError(f"device {did} belongs to another owner")
            rec = await self.session.get(MobileDeviceDB, did)
            assert rec is not None
            rec.platform = platform
            rec.agent_version = agent_version
            rec.capabilities = clean_caps
            rec.public_key = public_key
            rec.status = "ONLINE"
            rec.last_seen = _now()
            await self.session.flush()
            return self._to_dict(rec)

        rec = MobileDeviceDB(
            device_id=did,
            tenant_id=tenant_id,
            owner_id=owner_id,
            platform=platform,
            agent_version=agent_version,
            capabilities=clean_caps,
            public_key=public_key,
            status="ONLINE",
            last_seen=_now(),
        )
        self.session.add(rec)
        await self.session.flush()
        return self._to_dict(rec)

    async def list_devices(self, *, owner_id: str) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            select(MobileDeviceDB)
            .where(MobileDeviceDB.owner_id == owner_id)
            .order_by(MobileDeviceDB.created_at.asc())
        )
        return [self._to_dict(r) for r in rows.scalars().all()]

    async def get_device(self, device_id: str) -> dict[str, Any] | None:
        rec = await self.session.get(MobileDeviceDB, device_id)
        return self._to_dict(rec) if rec is not None else None

    async def heartbeat(
        self, device_id: str, *, owner_id: str, status: str | None = None
    ) -> dict[str, Any]:
        rec = await self.session.get(MobileDeviceDB, device_id)
        if rec is None:
            raise DeviceNotFoundError(f"device {device_id} not found")
        if rec.owner_id != owner_id:
            raise DeviceOwnershipError(f"device {device_id} belongs to another owner")
        rec.last_seen = _now()
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid device status: {status}")
            rec.status = status
        await self.session.flush()
        return self._to_dict(rec)

    def _to_dict(self, rec: MobileDeviceDB) -> dict[str, Any]:
        return {
            "device_id": rec.device_id,
            "tenant_id": rec.tenant_id,
            "owner_id": rec.owner_id,
            "public_key": rec.public_key,
            "platform": rec.platform,
            "agent_version": rec.agent_version,
            "capabilities": list(rec.capabilities),
            "status": rec.status,
            "last_seen": rec.last_seen.isoformat(),
            "created_at": rec.created_at.isoformat(),
        }


__all__ = [
    "ALLOWED_CAPABILITIES",
    "DeviceMeshService",
    "DeviceNotFoundError",
    "DeviceOwnershipError",
]
