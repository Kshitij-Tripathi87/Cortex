"""Liveness and readiness.

Liveness says only that the process answers. Readiness says the service can
do its work: PostgreSQL is reachable and the schema is at the expected
migration head. Readiness answers 503 otherwise; it never reports a healthy
state it did not verify.
"""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.db.health import check_database
from app.db.session import Database

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class ReadinessCheck(BaseModel):
    status: Literal["ok", "failed"]
    detail: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, ReadinessCheck]


@router.get("/health/live", response_model=LivenessResponse, summary="Process liveness")
def live() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Database and migration readiness",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def ready(request: Request, response: Response) -> ReadinessResponse:
    database: Database = request.app.state.database
    outcomes = check_database(database, request.app.state.migration_heads)
    is_ready = all(outcome.ok for outcome in outcomes.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        checks={
            name: ReadinessCheck(status="ok" if outcome.ok else "failed", detail=outcome.detail)
            for name, outcome in outcomes.items()
        },
    )
