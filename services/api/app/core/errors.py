"""Domain errors and their translation to the standard API error envelope.

Services raise the typed errors below. The handlers registered by
:func:`register_exception_handlers` turn them, request-validation errors and
database errors into one response shape::

    {"error": {"code": ..., "message": ..., "details": [...], "request_id": ...}}

No handler ever puts SQL, a stack trace, a path or a submitted value into a
response. Codes are stable; messages may be reworded.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id, error_body

_log = logging.getLogger("app.error")


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """One specific problem inside an error response."""

    code: str
    message: str
    field: str | None = None
    row_number: int | None = None
    column: str | None = None

    def as_dict(self) -> dict[str, object]:
        body: dict[str, object] = {"code": self.code, "message": self.message}
        if self.field is not None:
            body["field"] = self.field
        if self.row_number is not None:
            body["row_number"] = self.row_number
        if self.column is not None:
            body["column"] = self.column
        return body


class DomainError(Exception):
    """Base class of every error a service raises on purpose."""

    status_code: ClassVar[int] = 400
    default_code: ClassVar[str] = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Sequence[ErrorDetail] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = tuple(details)


class NotFoundError(DomainError):
    """The record does not exist, or is not visible in the verified workspace."""

    status_code = 404
    default_code = "NOT_FOUND"


class WorkspaceNotAvailableError(DomainError):
    """The workspace is not the one this process serves, is missing or is disabled.

    Answered with 404 in every case, so the response does not say whether a
    workspace with that id exists.
    """

    status_code = 404
    default_code = "WORKSPACE_NOT_AVAILABLE"

    def __init__(self) -> None:
        super().__init__("The workspace is not available.")


class ConflictError(DomainError):
    """The request collides with existing data, for example a natural key."""

    status_code = 409
    default_code = "CONFLICT"


class InvalidStateError(DomainError):
    """The record is not in a state that allows the operation."""

    status_code = 409
    default_code = "INVALID_STATE"


class ValidationFailedError(DomainError):
    """The request is well formed but its content breaks a rule."""

    status_code = 422
    default_code = "VALIDATION_ERROR"


class UnsupportedFileError(DomainError):
    """The upload is not a CSV or XLSX file."""

    status_code = 415
    default_code = "UNSUPPORTED_FILE"


class FileTooLargeError(DomainError):
    """The upload exceeds the configured size limit."""

    status_code = 413
    default_code = "FILE_TOO_LARGE"


# --- translation to HTTP -------------------------------------------------------------

_HTTP_STATUS_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    406: "NOT_ACCEPTABLE",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
}

_HTTP_STATUS_MESSAGES = {
    404: "The requested resource was not found.",
    405: "The method is not allowed for this resource.",
}

# pydantic error type -> stable API code
_PYDANTIC_CODES = {
    "missing": "REQUIRED_FIELD_MISSING",
    "enum": "INVALID_ENUM",
    "literal_error": "INVALID_ENUM",
    "extra_forbidden": "UNKNOWN_FIELD",
    "string_too_long": "VALUE_TOO_LONG",
    "string_too_short": "VALUE_TOO_SHORT",
    "too_long": "TOO_MANY_ITEMS",
    "uuid_parsing": "INVALID_UUID",
    "uuid_type": "INVALID_UUID",
    "int_parsing": "INVALID_INTEGER",
    "int_type": "INVALID_INTEGER",
    "int_from_float": "INVALID_INTEGER",
    "bool_parsing": "INVALID_BOOLEAN",
    "bool_type": "INVALID_BOOLEAN",
}
_PYDANTIC_CODE_PREFIXES = (
    ("date_", "INVALID_DATE"),
    ("datetime_", "INVALID_DATE"),
    ("decimal_", "INVALID_DECIMAL"),
)


def _code_for_pydantic_error(error: dict[str, Any]) -> str:
    error_type = str(error.get("type", ""))
    # Validators of this service raise PydanticCustomError with the API code as type.
    if error_type.isupper():
        return error_type
    if error_type in _PYDANTIC_CODES:
        return _PYDANTIC_CODES[error_type]
    for prefix, code in _PYDANTIC_CODE_PREFIXES:
        if error_type.startswith(prefix):
            return code
    context = error.get("ctx") or {}
    if error_type == "greater_than" and context.get("gt") == 0:
        return "MUST_BE_POSITIVE"
    if error_type == "greater_than_equal" and context.get("ge") == 0:
        return "MUST_BE_NON_NEGATIVE"
    if error_type in {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}:
        return "OUT_OF_RANGE"
    return "INVALID_VALUE"


def _field_path(location: Sequence[Any]) -> str | None:
    """`("body", "items", 0, "quantity")` -> `"items.0.quantity"`."""
    parts = [str(part) for part in location]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    return ".".join(parts) or None


def _respond(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Sequence[ErrorDetail] = (),
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or current_request_id()
    return JSONResponse(
        status_code=status_code,
        content=error_body(code, message, request_id, [detail.as_dict() for detail in details]),
    )


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _respond(request, exc.status_code, exc.code, exc.message, exc.details)


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    if any(error.get("type") == "json_invalid" for error in errors):
        return _respond(request, 400, "MALFORMED_REQUEST", "The request body is not valid JSON.")
    details = [
        ErrorDetail(
            code=_code_for_pydantic_error(error),
            # pydantic's message names the rule, never the submitted value.
            message=str(error.get("msg", "Invalid value.")),
            field=_field_path(error.get("loc", ())),
        )
        for error in errors
    ]
    return _respond(request, 422, "VALIDATION_ERROR", "The supplied record is invalid.", details)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = _HTTP_STATUS_MESSAGES.get(exc.status_code, "The request could not be processed.")
    response = _respond(request, exc.status_code, code, message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _handle_integrity_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, IntegrityError)
    # Services check natural keys before writing; this is the answer when two
    # writers race. Only the constraint name is logged, never the statement.
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    _log.warning("Integrity constraint rejected a write", extra={"constraint": constraint})
    return _respond(request, 409, "CONFLICT", "The request conflicts with existing data.")


async def _handle_database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DBAPIError)
    _log.error("Database is not reachable", extra={"error_type": type(exc.orig).__name__})
    return _respond(
        request, 503, "DATABASE_UNAVAILABLE", "The database is not reachable. Try again shortly."
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the handlers that produce the standard error envelope."""
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(IntegrityError, _handle_integrity_error)
    app.add_exception_handler(OperationalError, _handle_database_unavailable)
    app.add_exception_handler(InterfaceError, _handle_database_unavailable)
