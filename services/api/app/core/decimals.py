"""Strict decimal parsing shared by the API schemas and the import normalization.

One rule for both entry points: plain decimal text only. No exponent, no
thousands separator, no NaN or infinity, and never a binary float, which
cannot represent every decimal value exactly.
"""

import re
from decimal import Decimal

_PLAIN_DECIMAL = re.compile(r"^[+-]?\d+(\.\d+)?$")


class DecimalFormatError(ValueError):
    """The text is not a plain decimal number."""


def parse_plain_decimal(text: str) -> Decimal:
    """Parse text such as ``"1234.56"`` or ``"-0.5"``; reject anything else."""
    candidate = text.strip()
    if not _PLAIN_DECIMAL.fullmatch(candidate):
        raise DecimalFormatError("not a plain decimal number")
    return Decimal(candidate)


def decimal_places(value: Decimal) -> int:
    """Number of digits after the decimal point, ignoring trailing zeros."""
    exponent = value.normalize().as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def integer_digits(value: Decimal) -> int:
    """Number of digits before the decimal point."""
    return len(str(abs(int(value))))


def fixed_scale(value: Decimal, scale: int) -> str:
    """Render with exactly ``scale`` decimals: ``Decimal("2")`` -> ``"2.000"``."""
    return format(value.quantize(Decimal(1).scaleb(-scale)), "f")
