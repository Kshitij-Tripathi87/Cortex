"""Voice API — provider-agnostic voice sessions + token issuance (Day 25).

    Tap -> Connect -> Microphone active -> "Vanessa" -> "Yes?"

The voice token endpoint validates identity and issues a SHORT-LIVED,
scoped token via a pluggable VoiceProvider. No permanent backend
credentials ever ship inside the app — the provider contract is the same
pattern as the S3/notifications swaps: real providers (LiveKit Cloud)
wire in later via config without touching this module's contract.

The voice state machine is user-visible and durable:

    IDLE → CONNECTING → LISTENING → THINKING → SPEAKING → EXECUTING → LISTENING
    Failure: DISCONNECTED → RECONNECTING → RESYNCING → CONNECTED
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.devices.models import VoiceSessionDB

router = APIRouter()

# The voice state machine.
VOICE_TRANSITIONS: dict[str, set[str]] = {
    "IDLE": {"CONNECTING"},
    "CONNECTING": {"LISTENING", "DISCONNECTED"},
    "LISTENING": {"THINKING", "DISCONNECTED"},
    "THINKING": {"SPEAKING", "LISTENING", "DISCONNECTED"},
    "SPEAKING": {"LISTENING", "EXECUTING", "DISCONNECTED"},
    "EXECUTING": {"LISTENING", "DISCONNECTED"},
    "DISCONNECTED": {"RECONNECTING"},
    "RECONNECTING": {"RESYNCING", "DISCONNECTED"},
    "RESYNCING": {"CONNECTED", "RECONNECTING"},
    "CONNECTED": {"LISTENING", "DISCONNECTED"},
}

VOICE_TOKEN_TTL_S = 300  # short-lived: 5 minutes


class VoiceTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = Field(default=None, max_length=64)
    device_id: str = Field(min_length=1, max_length=64)


class VoiceSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = Field(default=None, max_length=64)
    device_id: str = Field(min_length=1, max_length=64)


class VoiceStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=1, max_length=32)


def _voice_provider() -> Any:
    """The configured VoiceProvider (stub locally; LiveKit wires in via config).

    The provider issues the short-lived scoped voice-session token. The stub
    signs an HMAC token with the voice-session claims — same identity
    validation, no external service. No permanent backend credentials ship
    inside the app: the token is scoped to ``voice`` and expires in 5 minutes.
    """
    import jwt as pyjwt

    from app.config import get_settings

    class StubVoiceProvider:
        name = "stub"

        async def issue_token(self, claims: dict[str, Any]) -> dict[str, Any]:
            s = get_settings()
            if not s.jwt_secret:
                raise RuntimeError("CORTEX_JWT_SECRET must be configured to issue voice tokens")
            now = datetime.now(UTC)
            payload = {
                "sub": str(claims["user_id"]),
                "scope": "voice",
                "device_id": claims["device_id"],
                "aud": s.jwt_audience,
                "iat": now,
                "exp": now + timedelta(seconds=VOICE_TOKEN_TTL_S),
            }
            token: str = pyjwt.encode(payload, s.jwt_secret, algorithm="HS256")
            return {
                "token": token,
                "expires_in": VOICE_TOKEN_TTL_S,
                "provider": self.name,
            }

    return StubVoiceProvider()


@router.post("/voice/token")
async def voice_token(
    body: VoiceTokenRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Short-lived, scoped voice token — identity validated server-side."""
    user_id = str(auth.user_id or "anonymous")
    provider = _voice_provider()
    claims = {
        "user_id": user_id,
        "device_id": body.device_id,
    }
    result = await provider.issue_token(claims)
    return {
        "data": {
            **result,
            "scope": "voice",
            "user_id": user_id,
            "device_id": body.device_id,
        }
    }


@router.post("/voice/sessions", status_code=201)
async def create_voice_session(
    body: VoiceSessionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = str(auth.user_id or "anonymous")
    rec = VoiceSessionDB(
        voice_session_id=f"voice-{uuid.uuid4().hex[:20]}",
        tenant_id=user_id,
        workspace_id=body.workspace_id,
        user_id=user_id,
        device_id=body.device_id,
        state="IDLE",
        provider="stub",
    )
    session.add(rec)
    await session.commit()
    return {
        "data": {
            "voice_session_id": rec.voice_session_id,
            "state": rec.state,
            "device_id": rec.device_id,
            "workspace_id": rec.workspace_id,
        }
    }


@router.get("/voice/sessions/{voice_session_id}")
async def get_voice_session(
    voice_session_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    rec = await session.get(VoiceSessionDB, voice_session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="voice session not found")
    if rec.user_id != str(auth.user_id or "anonymous"):
        raise HTTPException(status_code=403, detail="voice session belongs to another user")
    return {
        "data": {
            "voice_session_id": rec.voice_session_id,
            "state": rec.state,
            "device_id": rec.device_id,
            "workspace_id": rec.workspace_id,
            "provider": rec.provider,
            "created_at": rec.created_at.isoformat(),
            "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
        }
    }


@router.post("/voice/sessions/{voice_session_id}/state")
async def transition_voice_session(
    voice_session_id: str,
    body: VoiceStateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    rec = await session.get(VoiceSessionDB, voice_session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="voice session not found")
    if rec.user_id != str(auth.user_id or "anonymous"):
        raise HTTPException(status_code=403, detail="voice session belongs to another user")
    allowed = VOICE_TRANSITIONS.get(rec.state, set())
    if body.state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"invalid voice transition: {rec.state} -> {body.state}. Allowed: {sorted(allowed)}",
        )
    rec.state = body.state
    if body.state == "DISCONNECTED":
        rec.ended_at = datetime.now(UTC)
    await session.commit()
    return {
        "data": {
            "voice_session_id": rec.voice_session_id,
            "state": rec.state,
            "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
        }
    }
