"""Value normalization: strict parsing, explicit aliases, nothing guessed."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.ingestion.normalization import (
    ENUM_ALIASES,
    NormalizationError,
    is_blank,
    normalize_header,
    normalize_text,
    parse_currency,
    parse_date,
    parse_decimal,
    parse_enum,
    parse_integer,
    to_json,
)
from app.models.enums import (
    EquipmentCategory,
    MilestoneStatus,
    MilestoneType,
    ProcurementStatus,
    PurchaseOrderStatus,
)


def fails(code: str) -> pytest.RaisesExc[NormalizationError]:
    return pytest.raises(NormalizationError, check=lambda exc: exc.code == code)


# --- headers --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("PO Number", "po number"),
        ("  po   number ", "po number"),
        ("PO_NUMBER", "po number"),
        ("PO-Number", "po number"),
        ("Required On-Site Date", "required on site date"),
        ("\N{ZERO WIDTH NO-BREAK SPACE}Project Code", "project code"),
        ("Ｐｒｏｊｅｃｔ Code", "project code"),  # full-width letters fold to ASCII
        ("Unit Price (INR)", "unit price inr"),
        (42, "42"),
    ],
)
def test_header_case_spacing_and_punctuation_are_folded(header: object, expected: str) -> None:
    assert normalize_header(header) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_blank_values(value: object) -> None:
    assert is_blank(value)


@pytest.mark.parametrize("value", [0, False, "0", " x "])
def test_values_that_are_not_blank(value: object) -> None:
    assert not is_blank(value)


# --- text -----------------------------------------------------------------------------


def test_text_is_trimmed_and_bounded() -> None:
    assert normalize_text("  TR-001  ", max_length=10) == "TR-001"
    with fails("VALUE_TOO_LONG"):
        normalize_text("x" * 11, max_length=10)


def test_spreadsheet_numbers_become_clean_text() -> None:
    """A code typed as a number in a spreadsheet must not gain a float tail."""
    assert normalize_text(4501, max_length=10) == "4501"
    assert normalize_text(4501.0, max_length=10) == "4501"
    assert normalize_text(45.5, max_length=10) == "45.5"
    with fails("INVALID_VALUE"):
        normalize_text(True, max_length=10)


# --- dates ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-19",
        " 2026-11-19 ",
        date(2026, 11, 19),
        datetime(2026, 11, 19),
        "2026-11-19T00:00:00",
    ],
)
def test_iso_dates_and_spreadsheet_date_cells_are_accepted(value: object) -> None:
    assert parse_date(value) == date(2026, 11, 19)


@pytest.mark.parametrize(
    "value",
    [
        "03/04/26",  # 3 April or 4 March: not guessed
        "19/11/2026",
        "11/19/2026",
        "19-11-2026",
        "2026/11/19",
        "19 Nov 2026",
        "2026-11-19T14:30:00",  # a time of day is not a date
        datetime(2026, 11, 19, 14, 30),
        "2026-02-30",
        "2026-13-01",
        "20261119",
        46345,  # a spreadsheet serial number without a date format
        46345.0,
        "tomorrow",
        True,
    ],
)
def test_ambiguous_or_malformed_dates_are_rejected(value: object) -> None:
    with fails("INVALID_DATE"):
        parse_date(value)


# --- decimals -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234.56", Decimal("1234.56")),
        (" 0.10 ", Decimal("0.10")),
        ("-5", Decimal("-5")),
        (2, Decimal("2")),
        (1234.56, Decimal("1234.56")),  # a spreadsheet number keeps its exact text form
        (0.1, Decimal("0.1")),
        (Decimal("7.5"), Decimal("7.5")),
        ("1234567890123456.78", Decimal("1234567890123456.78")),
    ],
)
def test_decimals_are_exact(value: object, expected: Decimal) -> None:
    parsed = parse_decimal(value, places=2, max_integer_digits=16)

    assert parsed == expected
    assert isinstance(parsed, Decimal)


def test_a_float_never_leaks_binary_noise() -> None:
    assert str(parse_decimal(0.1 + 0.2, places=17, max_integer_digits=16)) == "0.30000000000000004"
    assert str(parse_decimal(1234.56, places=2, max_integer_digits=16)) == "1234.56"


@pytest.mark.parametrize(
    "value",
    [
        "1,234.56",  # thousands separator: ambiguous across locales
        "1.234,56",
        "1e3",
        "12.5%",
        "INR 100",
        "",
        "abc",
        "NaN",
        "Infinity",
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        True,
        None,
        [1],
    ],
)
def test_malformed_and_non_finite_decimals_are_rejected(value: object) -> None:
    with fails("INVALID_DECIMAL"):
        parse_decimal(value, places=2, max_integer_digits=16)


def test_too_many_decimal_places_are_rejected_not_rounded() -> None:
    with pytest.raises(NormalizationError, match="not rounded"):
        parse_decimal("1.005", places=2, max_integer_digits=16)
    assert parse_decimal("1.500", places=2, max_integer_digits=16) == Decimal("1.5")


def test_numbers_that_do_not_fit_the_column_are_rejected() -> None:
    with fails("INVALID_DECIMAL"):
        parse_decimal("12345678901234567", places=2, max_integer_digits=16)


# --- integers and currency ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), [(3, 3), ("3", 3), (" 12 ", 12), (3.0, 3), ("-1", -1)]
)
def test_whole_numbers(value: object, expected: int) -> None:
    assert parse_integer(value) == expected


@pytest.mark.parametrize("value", [3.5, "3.5", "three", "", True, None, float("nan")])
def test_values_that_are_not_whole_numbers(value: object) -> None:
    with fails("INVALID_INTEGER"):
        parse_integer(value)


@pytest.mark.parametrize(("value", "expected"), [("INR", "INR"), (" usd ", "USD"), ("Eur", "EUR")])
def test_currency_is_upper_cased(value: str, expected: str) -> None:
    assert parse_currency(value) == expected


@pytest.mark.parametrize("value", ["RS", "RUPEE", "₹", "US$", "12A", "", None, 356])
def test_invalid_currency(value: object) -> None:
    with fails("INVALID_CURRENCY"):
        parse_currency(value)


# --- enumerations ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "enum_class", "expected"),
    [
        ("IN_PRODUCTION", PurchaseOrderStatus, PurchaseOrderStatus.IN_PRODUCTION),
        ("in production", PurchaseOrderStatus, PurchaseOrderStatus.IN_PRODUCTION),
        (" In-Production ", ProcurementStatus, ProcurementStatus.IN_PRODUCTION),
        ("FAT", MilestoneType, MilestoneType.FACTORY_ACCEPTANCE_TEST),
        ("PO Ack", MilestoneType, MilestoneType.PO_ACKNOWLEDGEMENT),
        ("Transformers", EquipmentCategory, EquipmentCategory.TRANSFORMER),
        ("DG set", EquipmentCategory, EquipmentCategory.GENERATOR),
        ("Chiller", EquipmentCategory, EquipmentCategory.COOLING),
        ("done", MilestoneStatus, MilestoneStatus.COMPLETED),
        ("Canceled", MilestoneStatus, MilestoneStatus.CANCELLED),
    ],
)
def test_enum_values_and_documented_aliases(value: str, enum_class: type, expected: object) -> None:
    assert parse_enum(value, enum_class) is expected


@pytest.mark.parametrize(
    ("value", "enum_class"),
    [
        ("Reactor", EquipmentCategory),
        ("LATE", MilestoneStatus),  # a judgement, not a status
        ("AT_RISK", ProcurementStatus),
        ("", PurchaseOrderStatus),
        ("COMPLETED?", MilestoneType),
    ],
)
def test_unknown_enum_values_are_rejected_not_defaulted(value: str, enum_class: type) -> None:
    with pytest.raises(NormalizationError) as failure:
        parse_enum(value, enum_class)

    assert failure.value.code == "INVALID_ENUM"
    # The message lists what is allowed and does not repeat what was sent.
    assert value.strip() == "" or value not in failure.value.message


def test_every_alias_points_at_a_real_member() -> None:
    for enum_class, aliases in ENUM_ALIASES.items():
        values = {member.value for member in enum_class}
        for alias, target in aliases.items():
            assert target in values, (enum_class.__name__, alias)
            assert alias not in values, f"{alias} is already a value of {enum_class.__name__}"


# --- JSON form ------------------------------------------------------------------------


def test_normalized_values_serialise_without_losing_precision() -> None:
    assert to_json(Decimal("1234.50")) == "1234.50"
    assert to_json(Decimal("1E+3")) == "1000"
    assert to_json(date(2026, 11, 19)) == "2026-11-19"
    assert to_json(MilestoneStatus.COMPLETED) == "COMPLETED"
    assert to_json({"description": "2.5 MVA", "count": 3}) == {"description": "2.5 MVA", "count": 3}
    assert to_json("text") == "text"
