"""Launch authentication & onboarding API (v0.8.5-B, blockers B1 + B7).

Endpoints:
  POST /auth/signup           open signup — creates organization + workspace +
                              admin user atomically, returns a bearer token.
  POST /auth/login            workspace-scoped login (pre-existing, hardened).
  GET  /auth/me               current principal + workspace + org + trial state.
  POST /auth/logout           client-symmetric logout (audit-recorded).
  POST /auth/change-password  authenticated password change.
  POST /auth/reset/request    request a single-use reset token.
  POST /auth/reset/confirm    redeem a reset token.

Security notes (honest limitations, see Day-11 pass):
  * Access tokens are stateless HS256 JWTs (default 60 min). There is NO
    server-side revocation list: ``logout`` discards the client token and
    records an audit event; a stolen token stays valid until ``exp``.
    True revocation (Redis denylist / token version) is a Day-11 decision.
  * Rate limits below are per-process in-memory buckets. They blunt online
    brute force on a single instance; a Redis-backed limiter is required
    before multi-instance prod if abuse is observed (Day 11).
  * ``reset/request`` never discloses whether an email exists (uniform 200)
    and returns the raw token ONLY in dev/test. In pilot/prod the token is
    delivered out-of-band (admin CLI until Day-15 email exists).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.common.ids import uuid7_uuid
from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, rate_limit
from app.modules.access.models import Organization, PasswordResetToken, User, Workspace
from app.modules.audit.service import emit as emit_audit
from app.modules.identity.jwt_auth import hash_password, issue_token, verify_password

router = APIRouter()

TRIAL_DAYS = 7
RESET_TOKEN_TTL_MINUTES = 30
# Password policy (launch): >= 10 chars with at least one letter and one digit.
_PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{10,128}$")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,63}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ─────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=256)
    workspace_name: str | None = Field(default=None, min_length=2, max_length=256)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    full_name: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("invalid email address")
        return email

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if not _PASSWORD_RE.match(value):
            raise ValueError("password must be >= 10 chars with a letter and a digit")
        return value


class LoginRequest(BaseModel):
    workspace_id: UUID
    email: str = Field(min_length=3, max_length=320)
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_at: datetime
    user_id: UUID
    workspace_id: UUID
    role: str
    organization_id: UUID | None = None


class MeUser(BaseModel):
    id: UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeWorkspace(BaseModel):
    id: UUID
    name: str
    slug: str


class MeOrganization(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: str
    trial_ends_at: datetime | None


class MeResponse(BaseModel):
    user: MeUser
    workspace: MeWorkspace
    organization: MeOrganization | None


class MessageResponse(BaseModel):
    success: bool
    message: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if not _PASSWORD_RE.match(value):
            raise ValueError("password must be >= 10 chars with a letter and a digit")
        return value


class ResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ResetRequestResponse(BaseModel):
    requested: bool
    # Populated ONLY in dev/test. In pilot/prod the token is delivered
    # out-of-band (admin CLI until Day-15 email) and this is always None.
    reset_token: str | None = None


class ResetConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if not _PASSWORD_RE.match(value):
            raise ValueError("password must be >= 10 chars with a letter and a digit")
        return value


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _email_key(*args: object, **kwargs: object) -> str:
    """Rate-limit key: the request body's email, else a global bucket."""
    body = kwargs.get("body", args[0] if args else None)
    email = getattr(body, "email", None)
    return f"email:{email}" if isinstance(email, str) and email else "_global"


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")[:48] or "org"
    return slug


async def _unique_slug(
    db: AsyncSession, model: type[Organization] | type[Workspace], base: str
) -> str:
    """Return ``base`` (or ``base-2`` …) that is not taken for ``model``."""
    candidate = base
    for attempt in range(1, 25):
        exists = (
            await db.execute(select(model.id).where(model.slug == candidate))
        ).scalar_one_or_none()
        if exists is None:
            return candidate
        candidate = f"{base}-{attempt + 1}"
    # Practically unreachable; fall back to a random suffix, never fail signup.
    return f"{base}-{secrets.token_hex(4)}"


def _invalid_credentials() -> HTTPException:
    # Uniform message for unknown user / bad password / inactive account:
    # no user-enumeration oracle.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _request_id(request: Request | None) -> str | None:
    if request is None:
        return None
    return getattr(request.state, "request_id", None)


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────


@router.post("/signup", response_model=LoginResponse, status_code=201)
@rate_limit(capacity=30, refill_per_s=30 / 3600)  # 30 signups/hour/instance
async def signup(
    body: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    """Open signup: organization + workspace + admin user, atomically.

    Launch rule (scope freeze): exactly one workspace per organization.
    Email is globally unique across workspaces so login can stay
    unambiguous for future multi-workspace users.
    """
    existing = (
        await db.execute(select(User.id).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    now = datetime.now(UTC)
    org = Organization(
        id=uuid7_uuid(),
        name=body.organization_name.strip(),
        slug=await _unique_slug(db, Organization, _slugify(body.organization_name)),
        plan="trial",
        trial_ends_at=now + timedelta(days=TRIAL_DAYS),
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    await db.flush()

    workspace_name = (body.workspace_name or body.organization_name).strip()
    workspace = Workspace(
        id=uuid7_uuid(),
        organization_id=org.id,
        name=workspace_name,
        slug=await _unique_slug(db, Workspace, _slugify(workspace_name)),
        created_at=now,
        updated_at=now,
    )
    db.add(workspace)
    await db.flush()

    user = User(
        id=uuid7_uuid(),
        workspace_id=workspace.id,
        email=body.email,
        full_name=(body.full_name.strip() if body.full_name else None),
        password_hash=hash_password(body.password),
        role=UserRole.ADMIN,
        is_active=True,
        created_at=now,
        password_changed_at=now,
    )
    db.add(user)
    await db.flush()

    await emit_audit(
        db,
        event_type="auth.signup",
        workspace_id=str(workspace.id),
        actor_id=str(user.id),
        actor_type="user",
        subject_type="user",
        subject_id=str(user.id),
        request_id=_request_id(request),
        message=f"Signup: {user.email} created org {org.slug}",
        payload={"organization_id": str(org.id), "plan": org.plan},
    )

    token, expires_at = issue_token(
        user_id=user.id, workspace_id=workspace.id, role=str(user.role), email=user.email
    )
    await db.commit()
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user_id=user.id,
        workspace_id=workspace.id,
        role=str(user.role),
        organization_id=org.id,
    )


@router.post("/login", response_model=LoginResponse)
@rate_limit(capacity=20, refill_per_s=20 / 900, key=_email_key)  # 20/15min/email
async def login(
    body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> LoginResponse:
    stmt = select(User).where(User.workspace_id == body.workspace_id, User.email == body.email)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise _invalid_credentials()
    token, expires_at = issue_token(
        user_id=user.id, workspace_id=user.workspace_id, role=str(user.role), email=user.email
    )
    user.last_login_at = datetime.now(UTC)
    await emit_audit(
        db,
        event_type="auth.login",
        workspace_id=str(user.workspace_id),
        actor_id=str(user.id),
        actor_type="user",
        subject_type="user",
        subject_id=str(user.id),
        request_id=_request_id(request),
        message=f"Login: {user.email}",
    )
    await db.commit()
    org_id = (
        await db.execute(select(Workspace.organization_id).where(Workspace.id == user.workspace_id))
    ).scalar_one_or_none()
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        user_id=user.id,
        workspace_id=user.workspace_id,
        role=str(user.role),
        organization_id=org_id,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    if not auth.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = UUID(auth.user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == user.workspace_id))
    ).scalar_one_or_none()
    if workspace is None:  # pragma: no cover — FK guarantees this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    org = None
    if workspace.organization_id is not None:
        org = (
            await db.execute(
                select(Organization).where(Organization.id == workspace.organization_id)
            )
        ).scalar_one_or_none()
    return MeResponse(
        user=MeUser(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=str(user.role),
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        ),
        workspace=MeWorkspace(id=workspace.id, name=workspace.name, slug=workspace.slug),
        organization=MeOrganization(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            trial_ends_at=org.trial_ends_at,
        )
        if org is not None
        else None,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Logout (client-symmetric).

    The client MUST discard its token. Tokens are stateless JWTs: the server
    records the logout for audit but cannot revoke the bearer token before
    ``exp`` (documented launch limitation, Day-11 review).
    """
    await emit_audit(
        db,
        event_type="auth.logout",
        workspace_id=auth.workspace_ids[0] if auth.workspace_ids else None,
        actor_id=auth.user_id,
        actor_type="user",
        subject_type="user",
        subject_id=auth.user_id,
        request_id=_request_id(request),
        message="Logout",
    )
    await db.commit()
    return MessageResponse(success=True, message="Logged out")


@router.post("/change-password", response_model=MessageResponse)
@rate_limit(capacity=10, refill_per_s=10 / 3600)  # 10/hour/instance
async def change_password(
    body: ChangePasswordRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    if not auth.user_id:
        raise _invalid_credentials()
    try:
        user_id = UUID(auth.user_id)
    except ValueError:
        raise _invalid_credentials() from None
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _invalid_credentials()
    if not verify_password(body.current_password, user.password_hash):
        raise _invalid_credentials()
    now = datetime.now(UTC)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = now
    await emit_audit(
        db,
        event_type="auth.password_changed",
        workspace_id=str(user.workspace_id),
        actor_id=str(user.id),
        actor_type="user",
        subject_type="user",
        subject_id=str(user.id),
        message="Password changed",
    )
    await db.commit()
    return MessageResponse(success=True, message="Password changed")


@router.post("/reset/request", response_model=ResetRequestResponse)
@rate_limit(capacity=5, refill_per_s=5 / 3600, key=_email_key)  # 5/hour/email
async def request_password_reset(
    body: ResetRequest, db: AsyncSession = Depends(get_db)
) -> ResetRequestResponse:
    """Request a single-use reset token. Uniform response — never reveals
    whether the email exists."""
    settings = get_settings()
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    raw_token: str | None = None
    if user is not None and user.is_active:
        # One live token per user: drop superseded unused tokens.
        await db.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
        raw_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        db.add(
            PasswordResetToken(
                id=uuid7_uuid(),
                user_id=user.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
                created_at=now,
            )
        )
        await emit_audit(
            db,
            event_type="auth.reset_requested",
            workspace_id=str(user.workspace_id),
            actor_type="anonymous",
            subject_type="user",
            subject_id=str(user.id),
            message="Password reset requested",
        )
        await db.commit()
    if settings.env in {"dev", "test"}:
        return ResetRequestResponse(requested=True, reset_token=raw_token)
    return ResetRequestResponse(requested=True)


@router.post("/reset/confirm", response_model=MessageResponse)
@rate_limit(capacity=10, refill_per_s=10 / 3600)  # 10/hour/instance
async def confirm_password_reset(
    body: ResetConfirmRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    record = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if record is None or record.used_at is not None or record.expires_at <= now:
        # Uniform message: no oracle for token validity / expiry / reuse.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    user = (await db.execute(select(User).where(User.id == record.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    record.used_at = now
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = now
    await emit_audit(
        db,
        event_type="auth.reset_confirmed",
        workspace_id=str(user.workspace_id),
        actor_type="anonymous",
        subject_type="user",
        subject_id=str(user.id),
        message="Password reset completed",
    )
    await db.commit()
    return MessageResponse(success=True, message="Password has been reset")
