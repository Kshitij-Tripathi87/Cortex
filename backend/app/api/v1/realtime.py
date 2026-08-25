"""Real-Time Streaming API — WebSocket Endpoint for Browser Operational Cockpit.

Provides real-time updates for:
- World state mutations
- Deliberation & Decision Room message streams
- Simulation progress ticks
- Human decision approvals
"""

from __future__ import annotations

import json
from typing import Any

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.common.ids import uuid7
from app.config import get_settings
from app.infrastructure.realtime_gateway import get_realtime_gateway

router = APIRouter(prefix="/realtime", tags=["Real-Time Streaming"])

_gateway = get_realtime_gateway()


def _decode_token_safe(token: str) -> dict[str, Any] | None:
    """Safely decode JWT claims without crashing on invalid tokens."""
    if not token:
        return None
    try:
        s = get_settings()
        secret = s.jwt_secret or "dev-insecure-secret-key-32chars!"
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_signature": False},
        )
    except Exception:
        return None


@router.websocket("/ws")
async def realtime_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
    workspace_id: str = Query(default="default_workspace"),
    tenant_id: str = Query(default="default_tenant"),
) -> None:
    """WebSocket connection authenticated at handshake for tenant-scoped fanout."""
    user_id = "ws_user"
    if token:
        payload = _decode_token_safe(token)
        if payload and "sub" in payload:
            user_id = payload["sub"]
            tenant_id = payload.get("tenant_id", tenant_id)

    session_id = str(uuid7())
    session = await _gateway.connect(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        websocket=websocket,
    )

    try:
        # Default subscribe to all channels within authorized workspace
        await _gateway.subscribe(session_id, workspace_id, "*")
        await websocket.send_text(
            json.dumps({
                "type": "connection_established",
                "session_id": session_id,
                "workspace_id": workspace_id,
                "tenant_id": tenant_id,
            })
        )

        while True:
            # Receive client control messages (e.g. subscribe / unsubscribe)
            data_text = await websocket.receive_text()
            try:
                msg = json.loads(data_text)
                action = msg.get("action")
                target_ws = msg.get("workspace_id", workspace_id)
                channel = msg.get("channel", "*")

                if action == "subscribe":
                    ok = await _gateway.subscribe(session_id, target_ws, channel)
                    await websocket.send_text(
                        json.dumps({"type": "subscription_ack", "channel": channel, "success": ok})
                    )
            except Exception:
                pass

    except WebSocketDisconnect:
        await _gateway.disconnect(session_id)
    except Exception:
        await _gateway.disconnect(session_id)


@router.get("/stats")
async def get_realtime_stats() -> dict[str, Any]:
    """Retrieve real-time gateway connection statistics."""
    return {
        "active_connections": _gateway.get_active_connection_count(),
        "channels": [
            "world-state",
            "scenarios",
            "simulations",
            "agent-messages",
            "decisions",
            "execution",
            "memory",
        ],
    }
