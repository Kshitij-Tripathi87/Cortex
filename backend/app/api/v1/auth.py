"""MVP login endpoint issuing short-lived HS256 bearer tokens."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.modules.access.models import User
from app.modules.identity.jwt_auth import issue_token, verify_password

router = APIRouter()

class LoginRequest(BaseModel):
    workspace_id: UUID
    email: str = Field(min_length=3, max_length=320)
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_at: datetime
    user_id: UUID
    workspace_id: UUID
    role: str

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    stmt = select(User).where(User.workspace_id == body.workspace_id, User.email == body.email)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password", headers={"WWW-Authenticate": "Bearer"})
    token, expires_at = issue_token(user_id=user.id, workspace_id=user.workspace_id, role=str(user.role), email=user.email)
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return LoginResponse(access_token=token, expires_at=expires_at, user_id=user.id, workspace_id=user.workspace_id, role=str(user.role))
