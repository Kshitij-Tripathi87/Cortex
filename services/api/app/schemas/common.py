"""Shared building blocks of the API contract: strict types, paging, PATCH rules."""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, ClassVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.core.decimals import DecimalFormatError, fixed_scale, parse_plain_decimal
from app.models import limits

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


# --- strict input types ---------------------------------------------------------------


def _strict_iso_date(value: Any) -> Any:
    """Accept ``YYYY-MM-DD`` text (or a date object) and nothing else.

    pydantic would also take timestamps and datetime strings; a date field of
    this API has exactly one spelling.
    """
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    if isinstance(value, str) and _ISO_DATE.fullmatch(value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise PydanticCustomError("INVALID_DATE", "Use an unambiguous date in YYYY-MM-DD format.")


def _strict_decimal(value: Any) -> Any:
    """Accept a decimal string or an integer. A JSON float is not exact."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (bool, float)):
        raise PydanticCustomError(
            "INVALID_DECIMAL", 'Send decimal values as JSON strings, for example "1234.56".'
        )
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return parse_plain_decimal(value)
        except DecimalFormatError:
            pass
    raise PydanticCustomError("INVALID_DECIMAL", "Supply a plain decimal number.")


def _currency_code(value: Any) -> Any:
    if isinstance(value, str) and _CURRENCY.fullmatch(value.strip().upper()):
        return value.strip().upper()
    raise PydanticCustomError("INVALID_CURRENCY", "Use a three-letter currency code.")


def _money_json(value: Decimal) -> str:
    return fixed_scale(value, limits.MONEY_SCALE)


def _quantity_json(value: Decimal) -> str:
    return fixed_scale(value, limits.QUANTITY_SCALE)


IsoDate = Annotated[date, BeforeValidator(_strict_iso_date)]

Money = Annotated[
    Decimal,
    BeforeValidator(_strict_decimal),
    Field(ge=0, max_digits=limits.MONEY_PRECISION, decimal_places=limits.MONEY_SCALE),
    PlainSerializer(_money_json, return_type=str, when_used="json"),
]

Quantity = Annotated[
    Decimal,
    BeforeValidator(_strict_decimal),
    Field(gt=0, max_digits=limits.QUANTITY_PRECISION, decimal_places=limits.QUANTITY_SCALE),
    PlainSerializer(_quantity_json, return_type=str, when_used="json"),
]

CurrencyCode = Annotated[str, BeforeValidator(_currency_code)]


def _text(max_length: int) -> Any:
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


CodeText = Annotated[str, _text(limits.CODE_MAX)]
NameText = Annotated[str, _text(limits.NAME_MAX)]
LocationText = Annotated[str, _text(limits.LOCATION_MAX)]
PlaceText = Annotated[str, _text(limits.PLACE_MAX)]
PoNumberText = Annotated[str, _text(limits.PO_NUMBER_MAX)]
ActorText = Annotated[str, _text(limits.ACTOR_MAX)]
SourceReferenceText = Annotated[str, _text(limits.SOURCE_REFERENCE_MAX)]
SpecificationText = Annotated[str, _text(limits.SPECIFICATION_TEXT_MAX)]


# --- base models ----------------------------------------------------------------------


class RequestModel(BaseModel):
    """Base of request bodies: unknown fields are rejected, not ignored."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base of response bodies; can be built from ORM records."""

    model_config = ConfigDict(from_attributes=True)


class PatchModel(RequestModel):
    """Base of partial updates.

    Only the fields present in the request are applied. A field listed in
    ``not_nullable`` may be omitted but may not be sent as ``null``.
    """

    not_nullable: ClassVar[frozenset[str]] = frozenset()

    @field_validator("*", mode="before")
    @classmethod
    def _reject_null_for_required_fields(cls, value: Any, info: ValidationInfo) -> Any:
        # Runs only for fields that are present in the request.
        if value is None and info.field_name in cls.not_nullable:
            raise PydanticCustomError("REQUIRED_FIELD_MISSING", "This field cannot be null.")
        return value

    def changes(self) -> dict[str, Any]:
        """The fields the caller sent, as Python values."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class Page[ItemT](ResponseModel):
    """The one shape of every list response."""

    items: list[ItemT]
    total: int = Field(ge=0, description="Number of items that match, across all pages.")
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


# --- error envelope (documented for every route) --------------------------------------


class ErrorDetailModel(BaseModel):
    code: str
    message: str
    field: str | None = Field(default=None, description="Field of a JSON request.")
    row_number: int | None = Field(default=None, description="Row of an imported file.")
    column: str | None = Field(default=None, description="Column of an imported file.")


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code.")
    message: str
    details: list[ErrorDetailModel]
    request_id: str | None


class ErrorResponse(BaseModel):
    """The one shape of every error response."""

    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "The body is not valid JSON.",
        404: "The record or the workspace is not available.",
        409: "Conflict with existing data or with the state of the record.",
        422: "The request content is invalid.",
        500: "Unexpected failure.",
        503: "The database is not reachable.",
    }.items()
}
