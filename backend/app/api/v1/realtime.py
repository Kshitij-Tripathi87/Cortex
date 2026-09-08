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

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.common.ids import uuid7
from app.config import get_settings
from app.infrastructure.realtime_gateway import get_realtime_gateway
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_role,
    require_workspace_access,
)
from app.modules.identity.jwt_auth import verify_token

router = APIRouter(prefix="/realtime", tags=["Real-Time Streaming"])

_gateway = get_realtime_gateway()


def _resolve_ws_identity(
    websocket: WebSocket,
    token: str,
    workspace_id: str,
    tenant_id: str,
) -> tuple[str, str, str] | None:
    """Resolve the authenticated (user_id, tenant_id, workspace_id) for a
    WebSocket handshake, or ``None`` to reject the connection.

    Fail-closed, per D3d and the production-hardening rule "the server
    decides authorization":

    * A *provided* bearer token must verify — its signature is checked,
      ``exp`` is enforced, and the authorized workspace is taken from
      the verified claims. The old code decoded the token with
      ``verify_signature=False`` (any token, or a forged one, was
      accepted and its claims trusted); that is the bug this closes.
    * With ``jwt_secret`` configured (pilot/staging/prod), a missing or
      invalid token rejects the handshake (no session).
    * In dev (no ``jwt_secret``), the REST app uses header identity;
      the WS handshake mirrors it by reading ``X-User-Id`` /
      ``X-Tenant-Id`` / ``X-Workspace-Id`` headers, falling back to the
      explicit query params. This keeps the dev console usable while
      never trusting *token* claims that cannot be verified.
    """
    settings = get_settings()

    if token:
        # A token was presented: it MUST verify. Never fall back to
        # trusting an unverifiable token's claims.
        if not settings.jwt_secret:
            # Dev mode has no signing secret, so a token cannot be
            # cryptographically verified. Reject rather than accept an
            # unsigned/forged token as if authentic.
            return None
        try:
            payload = verify_token(token, settings)
        except PermissionError:
            return None
        user_id = payload.get("sub")
        verified_ws = payload.get("workspace_id")
        if not isinstance(user_id, str) or not isinstance(verified_ws, str):
            return None
        # The server decides the workspace from the verified claim; the
        # client-supplied query ``workspace_id`` is never trusted.
        return user_id, payload.get("tenant_id", tenant_id), verified_ws

    # No token supplied.
    if settings.jwt_secret:
        # Production-like environment: a token is mandatory.
        return None
    # Dev header-identity fallback (mirrors HeaderIdentityProvider for REST).
    user_id = websocket.headers.get("x-user-id")
    if not user_id:
        return None
    return (
        user_id,
        websocket.headers.get("x-tenant-id", tenant_id),
        websocket.headers.get("x-workspace-id", workspace_id),
    )


@router.websocket("/ws")
async def realtime_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
    workspace_id: str = Query(default="default_workspace"),
    tenant_id: str = Query(default="default_tenant"),
) -> None:
    """WebSocket connection authenticated at handshake for tenant-scoped fanout."""
    identity = _resolve_ws_identity(websocket, token, workspace_id, tenant_id)
    if identity is None:
        # Fail closed: reject the handshake before accept. WebSocket has
        # no standard 401; 4401 is the conventional app-level
        # "unauthorized" close code.
        await websocket.close(code=4401, reason="Unauthorized")
        return
    user_id, tenant_id, workspace_id = identity
    auth = AuthContext(
        user_id=user_id,
        workspace_ids=[workspace_id] if workspace_id else [],
    )
    require_workspace_access(workspace_id, auth)

    session_id = str(uuid7())
    await _gateway.connect(
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
            json.dumps(
                {
                    "type": "connection_established",
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "tenant_id": tenant_id,
                }
            )
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
            except Exception:  # noqa: S110 - malformed control message is ignored
                pass

    except WebSocketDisconnect:
        await _gateway.disconnect(session_id)
    except Exception:
        await _gateway.disconnect(session_id)


@router.get("/stats")
async def get_realtime_stats(
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve real-time gateway connection statistics (operator role required)."""
    require_role("operator", auth)
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
