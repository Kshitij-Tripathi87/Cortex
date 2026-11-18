"""Public site requests API.

    POST /public/contact-requests   save a demo request or a contact message

The site has no mailbox behind it. This route is the one place a visitor's
request is stored; the reference it returns is the reference of the row that
was saved, so the site only ever says "received" about something that was.

Security notes:
  * Public by design: the sender has no account. It is write-only; nothing
    here (or anywhere in the API) reads the table back. The team reads it
    with ``scripts/contact_requests.py``.
  * Every field is length-limited and unknown fields are rejected, so one
    request cannot store more than a few kilobytes.
  * Limited per client address and for the server as a whole, so one caller
    can neither fill the table nor use up everybody else's budget. Per-client
    limits need the real client address: behind a proxy set uvicorn's
    FORWARDED_ALLOW_IPS (see docs/11-deployment.md).
  * The client address is used for the limit only and is not stored.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AttemptThrottle, client_address
from app.modules.contact.models import STATUS_NEW, ContactRequest

router = APIRouter()
logger = logging.getLogger(__name__)

# Same shape as the sign-up rule in auth.py.
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,63}$")

# Letters and digits that cannot be mistaken for one another when read aloud
# or copied by hand (no 0/O, 1/I/L).
_REFERENCE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_REFERENCE_LENGTH = 8

# 10 requests an hour from one client address; 300 an hour for the whole
# server, which bounds how fast the table can grow whatever the source.
_REQUESTS = AttemptThrottle(
    address=(10, 3600.0),
    everyone=(300, 3600.0),
)

Topic = Literal["demo", "general", "sales", "engineering", "security", "privacy", "legal"]

_Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_Choice = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class DemoDetails(BaseModel):
    """The extra answers of the demo request form. All optional."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    job_title: str | None = Field(default=None, max_length=200)
    primary_role: str | None = Field(default=None, max_length=64)
    country: str | None = Field(default=None, max_length=100)
    company_size: str | None = Field(default=None, max_length=32)
    challenges: list[_Choice] = Field(default_factory=list, max_length=12)
    current_systems: list[_Choice] = Field(default_factory=list, max_length=12)
    desired_outcome: str | None = Field(default=None, max_length=500)
    timeline: str | None = Field(default=None, max_length=64)


class ContactRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: Topic
    full_name: _Line
    email: str = Field(min_length=3, max_length=320)
    company: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    consent: bool
    details: DemoDetails | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("invalid email address")
        return email

    @field_validator("consent")
    @classmethod
    def _require_consent(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("consent is required to store and answer the request")
        return value


class ContactRequestReceipt(BaseModel):
    reference: str
    received_at: datetime


def _new_reference() -> str:
    code = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(_REFERENCE_LENGTH))
    return f"REQ-{code}"


@router.post(
    "/contact-requests",
    response_model=ContactRequestReceipt,
    status_code=201,
    summary="Save a demo request or contact message from the public site.",
)
async def create_contact_request(
    body: ContactRequestBody, request: Request, db: AsyncSession = Depends(get_db)
) -> ContactRequestReceipt:
    """Store the request and return the reference of the stored row."""
    _REQUESTS.acquire({"address": client_address(request), "everyone": "_all"})

    details = body.details.model_dump(exclude_none=True) if body.details is not None else {}
    received_at = datetime.now(UTC)

    # The reference is random; a clash with an existing one is next to
    # impossible, but the unique constraint decides, not luck.
    for _attempt in range(5):
        reference = _new_reference()
        taken = (
            await db.execute(select(ContactRequest.id).where(ContactRequest.reference == reference))
        ).scalar_one_or_none()
        if taken is not None:
            continue
        db.add(
            ContactRequest(
                id=uuid7(),
                reference=reference,
                topic=body.topic,
                full_name=body.full_name,
                email=body.email,
                company=body.company or None,
                message=body.message,
                details=details,
                consent=True,
                status=STATUS_NEW,
                created_at=received_at,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            continue
        # No personal data in the log: the reference is enough to find the row.
        logger.info("contact request saved: reference=%s topic=%s", reference, body.topic)
        return ContactRequestReceipt(reference=reference, received_at=received_at)

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="The request could not be saved. Please try again.",
    )
