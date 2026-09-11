"""Real-Time Streaming API — WebSocket Endpoint for Browser Operational Cockpit.

Provides real-time updates for:
- World state mutations
- Deliberation & Decision Room message streams
- Simulation progress ticks
- Human decision approvals

B4 wire contract: sequenced outbox events ride this socket in the SAME
canonical envelope as SSE/HTTP-replay
``{event_id, seq, type, entity_type, entity_id, payload,
world_state_version, correlation_id, timestamp}`` (plus the legacy
``channel``/``tenant_id``/``workspace_id`` routing keys). New query params
``after_seq``/``replay`` give WS the same catch-up + gap/resync semantics
as SSE: ``connection_established`` → optional catch-up frames →
``catchup_complete`` → live frames; a ``resync_needed``/``resync_required``
frame means the client must replay-or-resnapshot and reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
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


def _ws_event_frame(event: Any, tenant_id: str, workspace_id: str) -> dict[str, Any]:
    """Render a bus Event / outbox row in the canonical WS envelope.

    A superset of the legacy gateway frame: routing keys (``channel``,
    ``tenant_id``, ``workspace_id``) plus the B4 sequencing keys
    (``event_id``, ``seq``, ``world_state_version``, ``correlation_id``).
    """
    to_dict = getattr(event, "to_dict", None)
    if callable(to_dict):
        base = dict(to_dict())
    else:
        created = getattr(event, "created_at", None)
        base = {
            "event_id": event.event_id,
            "seq": event.seq,
            "type": getattr(event, "event_type", "outbox_event"),
            "entity_type": getattr(event, "entity_type", None),
            "entity_id": getattr(event, "entity_id", None),
            "payload": getattr(event, "payload", {}) or {},
            "world_state_version": getattr(event, "world_state_version", None),
            "correlation_id": getattr(event, "correlation_id", None),
            "timestamp": created.isoformat() if created is not None else None,
        }
    base["channel"] = "outbox"
    base["tenant_id"] = tenant_id
    base["workspace_id"] = workspace_id
    base.setdefault("event_type", base.get("type"))
    return base


@router.websocket("/ws")
async def realtime_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
    workspace_id: str = Query(default="default_workspace"),
    tenant_id: str = Query(default="default_tenant"),
    after_seq: int = Query(default=0, ge=0),
    replay: bool = Query(default=True),
) -> None:
    """WebSocket connection authenticated at handshake for tenant-scoped fanout."""
    from app.infrastructure import metrics as _metrics

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
    _metrics.realtime_connections.labels(transport="ws").inc()

    # All socket writes (control acks + bus forwarder) serialize here:
    # concurrent send_text calls from two coroutines can interleave frames.
    send_lock = asyncio.Lock()

    async def _send(obj: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(obj))

    # Outbox rows are attributed to the principal tenant (MVP: user_id),
    # mirroring the persistent API's tenant+workspace read scoping.
    replay_tenant = user_id
    last_seq = after_seq
    bus_queue: Any = None
    forwarder: asyncio.Task[None] | None = None
    try:
        # Default subscribe to all channels within authorized workspace
        await _gateway.subscribe(session_id, workspace_id, "*")
        await _send(
            {
                "type": "connection_established",
                "session_id": session_id,
                "workspace_id": workspace_id,
                "tenant_id": tenant_id,
                "after_seq": after_seq,
            }
        )
        if after_seq > 0:
            _metrics.realtime_reconnect_total.labels(transport="ws").inc()

        # ── Catch-up (B4): missed events before the live tail ──
        settings = get_settings()
        factory = None
        if replay:
            try:
                from app.infrastructure.database import get_session_factory

                factory = get_session_factory()
            except RuntimeError:
                factory = None  # DB not initialized (unit tests): live-only
        if replay and factory is not None:
            from app.modules.nexus_spine.persistence.repositories import (
                get_event_repository,
            )

            repo = get_event_repository()
            async with factory() as catchup_session:
                latest_seq, _ = await repo.get_head(
                    catchup_session,
                    tenant_id=replay_tenant,
                    workspace_id=workspace_id,
                )
                if latest_seq - after_seq > settings.realtime_resync_threshold:
                    _metrics.realtime_resync_total.labels(transport="ws").inc()
                    await _send(
                        {
                            "type": "resync_required",
                            "from_seq": after_seq,
                            "latest_seq": latest_seq,
                        }
                    )
                    last_seq = after_seq
                else:
                    rows = await repo.get_since_seq(
                        catchup_session,
                        workspace_id=workspace_id,
                        since_seq=after_seq,
                        tenant_id=replay_tenant,
                        limit=settings.realtime_replay_limit,
                    )
                    if rows:
                        _metrics.realtime_replay_total.labels(transport="ws").inc()
                    for row in rows:
                        await _send(_ws_event_frame(row, tenant_id, workspace_id))
                        _metrics.realtime_events_delivered_total.labels(transport="ws").inc()
                        last_seq = row.seq
                    await _send(
                        {
                            "type": "catchup_complete",
                            "from_seq": after_seq,
                            "to_seq": last_seq,
                            "latest_seq": latest_seq,
                            "has_more": last_seq < latest_seq,
                        }
                    )

        # ── Live bridge (B4): RealtimeBus → socket with a sequence gate ──
        from app.infrastructure.realtime_bus import get_realtime_bus

        bus = get_realtime_bus()
        bus_queue = bus.subscribe(workspace_id)

        async def _forward() -> None:
            nonlocal last_seq
            try:
                while True:
                    event = await bus_queue.get()
                    if event.seq <= last_seq:
                        _metrics.realtime_duplicate_events_total.inc()
                        continue
                    if last_seq > 0 and event.seq > last_seq + 1:
                        _metrics.realtime_gap_detected_total.labels(transport="ws").inc()
                        with contextlib.suppress(Exception):
                            await _send(
                                {
                                    "type": "resync_needed",
                                    "from_seq": last_seq,
                                    "to_seq": event.seq,
                                }
                            )
                        return  # client reconnects with its cursor
                    await _send(_ws_event_frame(event, tenant_id, workspace_id))
                    _metrics.realtime_events_delivered_total.labels(transport="ws").inc()
                    last_seq = event.seq
            except asyncio.CancelledError:
                pass

        forwarder = asyncio.create_task(_forward())

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
                    await _send({"type": "subscription_ack", "channel": channel, "success": ok})
            except Exception:  # noqa: S110 - malformed control message is ignored
                pass

    except WebSocketDisconnect:  # noqa: S110 — cleanup lives in finally
        pass
    except Exception:  # noqa: S110, BLE001 — cleanup lives in finally
        pass
    finally:
        if forwarder is not None and not forwarder.done():
            forwarder.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await forwarder
        if bus_queue is not None:
            from app.infrastructure.realtime_bus import get_realtime_bus

            with contextlib.suppress(Exception):
                get_realtime_bus().unsubscribe(workspace_id, bus_queue)
        await _gateway.disconnect(session_id)
        _metrics.realtime_connections.labels(transport="ws").dec()


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
