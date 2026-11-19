"""Strict, deterministic normalization of source values.

Every function either returns a typed value or raises NormalizationError with
a stable code. Nothing is guessed and nothing is defaulted: an ambiguous date
is an error, not a best effort. Error messages never repeat the source value.
"""

import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.core.decimals import (
    DecimalFormatError,
    decimal_places,
    integer_digits,
    parse_plain_decimal,
)
from app.models.enums import (
    EquipmentCategory,
    MilestoneStatus,
    MilestoneType,
    ProcurementStatus,
    ProjectStatus,
    PurchaseOrderStatus,
)

BYTE_ORDER_MARK = "\N{ZERO WIDTH NO-BREAK SPACE}"

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
# Dates are matched with the digits 0-9 only (re.ASCII). A date written in the
# digits of another script is often a date of another calendar (Thai ๒๕๖๙ is
# 2026), and the calendar is never guessed. Numbers have no such doubt: there a
# digit of any script is the digit it is.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)
_ISO_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00(:00(\.0+)?)?$", re.ASCII)
_WHOLE_NUMBER = re.compile(r"^[+-]?\d+$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

# Spellings a source may use for an enumerated value. Explicit and short on
# purpose: an alias is added when its meaning is not in doubt, never inferred.
# Keys are compared after upper-casing and replacing separators by "_".
ENUM_ALIASES: Mapping[type[StrEnum], Mapping[str, str]] = {
    ProjectStatus: {"ONHOLD": "ON_HOLD", "CANCELED": "CANCELLED", "COMPLETE": "COMPLETED"},
    EquipmentCategory: {
        "TRANSFORMERS": "TRANSFORMER",
        "SWITCHGEARS": "SWITCHGEAR",
        "GENERATORS": "GENERATOR",
        "DIESEL_GENERATOR": "GENERATOR",
        "DG": "GENERATOR",
        "DG_SET": "GENERATOR",
        "GENSET": "GENERATOR",
        "UPS_SYSTEM": "UPS",
        "CHILLER": "COOLING",
        "CHILLERS": "COOLING",
        "HVAC": "COOLING",
    },
    ProcurementStatus: {"CANCELED": "CANCELLED", "INPRODUCTION": "IN_PRODUCTION"},
    PurchaseOrderStatus: {"CANCELED": "CANCELLED", "INPRODUCTION": "IN_PRODUCTION"},
    MilestoneType: {
        "ACKNOWLEDGEMENT": "PO_ACKNOWLEDGEMENT",
        "ORDER_ACKNOWLEDGEMENT": "PO_ACKNOWLEDGEMENT",
        "PO_ACK": "PO_ACKNOWLEDGEMENT",
        "FAT": "FACTORY_ACCEPTANCE_TEST",
    },
    MilestoneStatus: {"COMPLETE": "COMPLETED", "DONE": "COMPLETED", "CANCELED": "CANCELLED"},
}


class NormalizationError(Exception):
    """A source value cannot be turned into the expected type."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_header(header: object) -> str:
    """Canonical form of a column header: case, spacing and punctuation folded.

    ``" PO  Number "``, ``"po_number"`` and ``"PO-Number"`` all become
    ``"po number"``.
    """
    text = unicodedata.normalize("NFKC", str(header)).replace(BYTE_ORDER_MARK, "").casefold()
    return _NON_ALPHANUMERIC.sub(" ", text).strip()


def is_blank(value: object) -> bool:
    """True for a missing cell: None or text that is empty after trimming."""
    return value is None or (isinstance(value, str) and not value.strip())


def normalize_text(value: object, *, max_length: int) -> str:
    """Trimmed text. Numbers from a spreadsheet are rendered without a float tail."""
    if isinstance(value, bool):
        raise NormalizationError("INVALID_VALUE", "Supply text, not a boolean.")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NormalizationError("INVALID_VALUE", "Supply text.")
        text = str(int(value)) if value.is_integer() else repr(value)
    else:
        text = str(value).strip()
    if len(text) > max_length:
        raise NormalizationError(
            "VALUE_TOO_LONG", f"The value is longer than {max_length} characters."
        )
    return text


def parse_date(value: object) -> date:
    """ISO ``YYYY-MM-DD`` text, or a spreadsheet date cell. Nothing else.

    ``03/04/26`` is rejected rather than guessed: without a declared locale it
    is either 3 April or 4 March.
    """
    if isinstance(value, datetime):
        if (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0):
            return value.date()
    elif isinstance(value, date):
        return value
    elif isinstance(value, str):
        text = value.strip()
        midnight = _ISO_MIDNIGHT.fullmatch(text)
        candidate = midnight.group(1) if midnight else text
        if _ISO_DATE.fullmatch(candidate):
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                pass
    raise NormalizationError("INVALID_DATE", "Use an unambiguous date in YYYY-MM-DD format.")


def parse_decimal(value: object, *, places: int, max_integer_digits: int) -> Decimal:
    """An exact decimal with at most ``places`` decimals. Never rounds, never guesses.

    Text must be plain decimal text. A spreadsheet number is converted through
    its shortest exact text form, so ``1234.56`` stays ``1234.56``.
    """
    invalid = NormalizationError("INVALID_DECIMAL", "Supply a plain decimal number.")
    if isinstance(value, bool):
        raise invalid
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise invalid
        number = Decimal(repr(value))
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise invalid
        number = value
    elif isinstance(value, str):
        try:
            number = parse_plain_decimal(value)
        except DecimalFormatError:
            raise invalid from None
    else:
        raise invalid
    if decimal_places(number) > places:
        raise NormalizationError(
            "INVALID_DECIMAL", f"Supply at most {places} decimal places; values are not rounded."
        )
    if integer_digits(number) > max_integer_digits:
        raise NormalizationError("INVALID_DECIMAL", "The number is too large.")
    return number


def parse_integer(value: object, *, maximum: int) -> int:
    """A whole number. ``3.0`` from a spreadsheet is accepted, ``3.5`` is not.

    A number beyond ``maximum`` (in either direction) is refused here, so that
    a row which passes validation can always be stored.
    """
    invalid = NormalizationError("INVALID_INTEGER", "Supply a whole number.")
    if isinstance(value, bool):
        raise invalid
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not (math.isfinite(value) and value.is_integer()):
            raise invalid
        number = int(value)
    elif isinstance(value, str) and _WHOLE_NUMBER.fullmatch(value.strip()):
        digits = value.strip().lstrip("+-").lstrip("0")
        # Judged by length first: converting thousands of digits is refused by Python itself.
        number = maximum + 1 if len(digits) > len(str(maximum)) else int(value.strip())
    else:
        raise invalid
    if abs(number) > maximum:
        raise NormalizationError("INVALID_INTEGER", f"The number is larger than {maximum}.")
    return number


def enum_token(value: object) -> str:
    """``"in production"`` and ``"In-Production"`` -> ``"IN_PRODUCTION"``."""
    return normalize_header(value).replace(" ", "_").upper()


def parse_enum[EnumT: StrEnum](value: object, enum_class: type[EnumT]) -> EnumT:
    """A member of ``enum_class`` by value or by a documented alias."""
    token = enum_token(value)
    token = ENUM_ALIASES.get(enum_class, {}).get(token, token)
    try:
        return enum_class(token)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_class)
        raise NormalizationError("INVALID_ENUM", f"Use one of: {allowed}.") from None


def parse_currency(value: object) -> str:
    """A three-letter currency code, upper-cased."""
    if isinstance(value, str) and _CURRENCY.fullmatch(value.strip().upper()):
        return value.strip().upper()
    raise NormalizationError("INVALID_CURRENCY", "Use a three-letter currency code.")


def to_json(value: Any) -> Any:
    """JSON form of a normalized value: dates as ISO text, decimals as plain text."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {key: to_json(item) for key, item in value.items()}
    return value
