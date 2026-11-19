"""Deterministic mapping of source columns to canonical fields.

Each importable entity has a fixed table of fields and of the headers that
may name them. A header maps to a field because it is listed here, never
because it looks similar. A column that is not listed is kept in the raw row
and reported as a warning; it is never dropped and never guessed at.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.ingestion.contracts import (
    MappedRow,
    ParsedRow,
    ParsedSheet,
    ValidationIssue,
    error,
    warning,
)
from app.ingestion.normalization import (
    NormalizationError,
    is_blank,
    normalize_header,
    normalize_text,
    parse_currency,
    parse_date,
    parse_decimal,
    parse_enum,
    parse_integer,
)
from app.models import limits
from app.models.enums import (
    Criticality,
    EquipmentCategory,
    IngestionEntityType,
    MilestoneStatus,
    MilestoneType,
    ProcurementStatus,
    ProjectStatus,
    PurchaseOrderStatus,
    SupplierStatus,
)


class FieldKind(StrEnum):
    TEXT = "TEXT"
    DATE = "DATE"
    DECIMAL = "DECIMAL"
    INTEGER = "INTEGER"
    ENUM = "ENUM"
    CURRENCY = "CURRENCY"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One canonical field of an importable entity."""

    name: str
    kind: FieldKind
    aliases: tuple[str, ...]
    required: bool = False
    max_length: int | None = None
    enum: type[StrEnum] | None = None
    decimal_places: int = 0
    max_integer_digits: int = 0
    max_integer: int = limits.INTEGER_MAX
    positive: bool = False
    non_negative: bool = False
    # Warning raised when the value is absent and absence is allowed.
    missing_warning: tuple[str, str] | None = None

    def normalize(self, value: object) -> Any:
        """Typed value of a non-blank source cell, or NormalizationError."""
        if self.kind is FieldKind.TEXT:
            assert self.max_length is not None
            return normalize_text(value, max_length=self.max_length)
        if self.kind is FieldKind.DATE:
            return parse_date(value)
        if self.kind is FieldKind.DECIMAL:
            return parse_decimal(
                value, places=self.decimal_places, max_integer_digits=self.max_integer_digits
            )
        if self.kind is FieldKind.INTEGER:
            return parse_integer(value, maximum=self.max_integer)
        if self.kind is FieldKind.ENUM:
            assert self.enum is not None
            return parse_enum(value, self.enum)
        return parse_currency(value)

    def from_json(self, value: Any) -> Any:
        """Typed value of a field stored in the ledger's normalized JSON."""
        if value is None:
            return None
        if self.kind is FieldKind.DATE:
            return date.fromisoformat(value)
        if self.kind is FieldKind.DECIMAL:
            return Decimal(value)
        if self.kind is FieldKind.ENUM:
            assert self.enum is not None
            return self.enum(value)
        if self.kind is FieldKind.INTEGER:
            return int(value)
        return value


@dataclass(frozen=True, slots=True)
class EntitySpec:
    entity_type: IngestionEntityType
    fields: tuple[FieldSpec, ...]
    natural_key: tuple[str, ...]

    def field(self, name: str) -> FieldSpec:
        return next(spec for spec in self.fields if spec.name == name)

    @property
    def field_by_alias(self) -> Mapping[str, FieldSpec]:
        return {normalize_header(alias): spec for spec in self.fields for alias in spec.aliases}


def _text(
    name: str, aliases: tuple[str, ...], max_length: int, *, required: bool = False
) -> FieldSpec:
    return FieldSpec(name, FieldKind.TEXT, aliases, required=required, max_length=max_length)


def _date(
    name: str,
    aliases: tuple[str, ...],
    *,
    required: bool = False,
    missing_warning: tuple[str, str] | None = None,
) -> FieldSpec:
    return FieldSpec(
        name, FieldKind.DATE, aliases, required=required, missing_warning=missing_warning
    )


def _enum(
    name: str, aliases: tuple[str, ...], enum: type[StrEnum], *, required: bool = False
) -> FieldSpec:
    return FieldSpec(name, FieldKind.ENUM, aliases, required=required, enum=enum)


def _money(name: str, aliases: tuple[str, ...]) -> FieldSpec:
    return FieldSpec(
        name,
        FieldKind.DECIMAL,
        aliases,
        decimal_places=limits.MONEY_SCALE,
        max_integer_digits=limits.MONEY_PRECISION - limits.MONEY_SCALE,
        non_negative=True,
    )


_PROJECT_CODE = ("Project Code", "Project ID", "Project Ref")
_SUPPLIER_CODE = ("Supplier Code", "Vendor Code")
_EQUIPMENT_CODE = ("Equipment Code", "Asset Code", "Tag No", "Tag Number", "Equipment Tag")
_PO_NUMBER = ("PO Number", "Purchase Order", "Purchase Order Number", "PO No")
_STATUS = ("Status",)

ENTITY_SPECS: Mapping[IngestionEntityType, EntitySpec] = {
    IngestionEntityType.PROJECT: EntitySpec(
        IngestionEntityType.PROJECT,
        (
            _text("code", _PROJECT_CODE, limits.CODE_MAX, required=True),
            _text("name", ("Project Name", "Project"), limits.NAME_MAX, required=True),
            _text("location", ("Location", "Site", "Site Location"), limits.LOCATION_MAX),
            _enum("status", (*_STATUS, "Project Status"), ProjectStatus),
            _date("target_completion_date", ("Target Completion Date", "Target Completion")),
        ),
        natural_key=("code",),
    ),
    IngestionEntityType.SUPPLIER: EntitySpec(
        IngestionEntityType.SUPPLIER,
        (
            _text("supplier_code", _SUPPLIER_CODE, limits.CODE_MAX, required=True),
            _text("name", ("Supplier Name", "Vendor Name"), limits.NAME_MAX, required=True),
            _text("country", ("Country",), limits.PLACE_MAX),
            _text("city", ("City",), limits.PLACE_MAX),
            _enum("status", (*_STATUS, "Supplier Status"), SupplierStatus),
        ),
        natural_key=("supplier_code",),
    ),
    IngestionEntityType.EQUIPMENT: EntitySpec(
        IngestionEntityType.EQUIPMENT,
        (
            _text("equipment_code", _EQUIPMENT_CODE, limits.CODE_MAX, required=True),
            _text("project_code", (*_PROJECT_CODE, "Project"), limits.CODE_MAX, required=True),
            _text("name", ("Equipment Name", "Equipment", "Name"), limits.NAME_MAX, required=True),
            _enum("category", ("Category", "Equipment Category"), EquipmentCategory, required=True),
            _date(
                "required_on_site_date",
                ("Required On Site Date", "Site Required Date", "ROS Date"),
                missing_warning=(
                    "REQUIRED_ON_SITE_DATE_NOT_RECORDED",
                    "No required-on-site date is recorded for this equipment.",
                ),
            ),
            _enum("criticality", ("Criticality",), Criticality, required=True),
            _enum("procurement_status", ("Procurement Status", *_STATUS), ProcurementStatus),
            _text("spec_description", ("Specification",), limits.SPECIFICATION_TEXT_MAX),
            _text("spec_manufacturer", ("Manufacturer",), limits.SPECIFICATION_TEXT_MAX),
            _text("spec_model", ("Model",), limits.SPECIFICATION_TEXT_MAX),
            _text("spec_notes", ("Notes",), limits.SPECIFICATION_TEXT_MAX),
        ),
        natural_key=("equipment_code",),
    ),
    IngestionEntityType.PURCHASE_ORDER: EntitySpec(
        IngestionEntityType.PURCHASE_ORDER,
        (
            _text("po_number", _PO_NUMBER, limits.PO_NUMBER_MAX, required=True),
            _text("project_code", (*_PROJECT_CODE, "Project"), limits.CODE_MAX, required=True),
            _text("supplier_code", _SUPPLIER_CODE, limits.CODE_MAX, required=True),
            FieldSpec("currency", FieldKind.CURRENCY, ("Currency",), required=True),
            _enum("status", (*_STATUS, "PO Status"), PurchaseOrderStatus, required=True),
            _date("issue_date", ("Issue Date", "PO Date", "Order Date")),
            _money("total_value", ("Total Value", "PO Value", "Order Value")),
        ),
        natural_key=("po_number",),
    ),
    IngestionEntityType.PURCHASE_ORDER_ITEM: EntitySpec(
        IngestionEntityType.PURCHASE_ORDER_ITEM,
        (
            _text("po_number", _PO_NUMBER, limits.PO_NUMBER_MAX, required=True),
            _text("equipment_code", _EQUIPMENT_CODE, limits.CODE_MAX, required=True),
            FieldSpec(
                "quantity",
                FieldKind.DECIMAL,
                ("Quantity", "Qty"),
                required=True,
                decimal_places=limits.QUANTITY_SCALE,
                max_integer_digits=limits.QUANTITY_PRECISION - limits.QUANTITY_SCALE,
                positive=True,
            ),
            _money("unit_price", ("Unit Price", "Unit Rate")),
        ),
        natural_key=("po_number", "equipment_code"),
    ),
    IngestionEntityType.MILESTONE: EntitySpec(
        IngestionEntityType.MILESTONE,
        (
            _text("po_number", _PO_NUMBER, limits.PO_NUMBER_MAX, required=True),
            _enum("milestone_type", ("Milestone Type", "Milestone"), MilestoneType, required=True),
            FieldSpec(
                "sequence_no",
                FieldKind.INTEGER,
                ("Sequence No", "Sequence", "Seq No"),
                required=True,
                max_integer=limits.SEQUENCE_NO_MAX,
                positive=True,
            ),
            _date("planned_date", ("Planned Date", "Baseline Date"), required=True),
            _date("actual_date", ("Actual Date", "Completion Date")),
            _enum("status", (*_STATUS, "Milestone Status"), MilestoneStatus),
        ),
        natural_key=("po_number", "milestone_type", "sequence_no"),
    ),
    IngestionEntityType.SUPPLIER_COMMITMENT: EntitySpec(
        IngestionEntityType.SUPPLIER_COMMITMENT,
        (
            _text("po_number", _PO_NUMBER, limits.PO_NUMBER_MAX, required=True),
            _date(
                "committed_delivery_date",
                ("Committed Delivery Date", "Supplier Promise Date"),
                required=True,
            ),
            _text("recorded_by", ("Recorded By",), limits.ACTOR_MAX),
            _text("source_reference", ("Source Reference",), limits.SOURCE_REFERENCE_MAX),
        ),
        natural_key=("po_number",),
    ),
}


@dataclass(frozen=True, slots=True)
class HeaderMapping:
    """How the headers of one file map to the fields of one entity."""

    # canonical field -> the source headers that name it (usually one)
    columns_by_field: Mapping[str, tuple[str, ...]]
    unknown_columns: tuple[str, ...]
    warnings: tuple[ValidationIssue, ...]


def map_headers(spec: EntitySpec, sheet: ParsedSheet) -> HeaderMapping:
    """Resolve each source header to a canonical field through the alias table."""
    aliases = spec.field_by_alias
    by_field: dict[str, list[str]] = {}
    unknown: list[str] = []
    for original, normalized in zip(sheet.headers_original, sheet.headers_normalized, strict=True):
        field_spec = aliases.get(normalized)
        if field_spec is None:
            unknown.append(original)
        else:
            by_field.setdefault(field_spec.name, []).append(original)
    warnings = tuple(
        warning(
            "MULTIPLE_COLUMNS_FOR_FIELD",
            f"{len(columns)} columns map to this field; a row is accepted only when they agree.",
            column=name,
        )
        for name, columns in by_field.items()
        if len(columns) > 1
    )
    return HeaderMapping(
        columns_by_field={name: tuple(columns) for name, columns in by_field.items()},
        unknown_columns=tuple(unknown),
        warnings=warnings,
    )


def map_row(spec: EntitySpec, mapping: HeaderMapping, row: ParsedRow) -> MappedRow:
    """Map and normalize one source row. The raw row is carried along untouched."""
    normalized: dict[str, Any] = {}
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    for field_spec in spec.fields:
        columns = mapping.columns_by_field.get(field_spec.name, ())
        if any(column in row.formula_cells for column in columns):
            errors.append(
                error(
                    "FORMULA_WITHOUT_CACHED_VALUE",
                    "The cell holds a formula without a stored result. Formulas are not "
                    "evaluated; save the workbook with calculated values or enter the value.",
                    column=field_spec.name,
                )
            )
            continue

        candidates: list[Any] = []
        failure: NormalizationError | None = None
        for column in columns:
            value = row.raw_data.get(column)
            if is_blank(value):
                continue
            try:
                candidates.append(field_spec.normalize(value))
            except NormalizationError as exc:
                failure = exc
        if failure is not None:
            errors.append(error(failure.code, failure.message, column=field_spec.name))
            continue
        distinct = _distinct(candidates)
        if len(distinct) > 1:
            # Two source columns say different things about one field. Neither wins.
            errors.append(
                error(
                    "AMBIGUOUS_COLUMN_MAPPING",
                    "Several source columns map to this field and their values differ.",
                    column=field_spec.name,
                )
            )
        elif distinct:
            normalized[field_spec.name] = distinct[0]
        elif field_spec.missing_warning is not None and not field_spec.required:
            code, message = field_spec.missing_warning
            warnings.append(warning(code, message, column=field_spec.name))

    for column in mapping.unknown_columns:
        if not is_blank(row.raw_data.get(column)):
            warnings.append(
                warning(
                    "UNKNOWN_SOURCE_COLUMN",
                    "Column retained in raw source data but not mapped to a canonical field.",
                    column=column,
                )
            )
    if row.extra_cells:
        errors.append(
            error(
                "ROW_SHAPE_MISMATCH",
                "The row has more cells than the header has columns.",
            )
        )
    return MappedRow(
        row_number=row.row_number,
        raw_data=row.raw_data,
        normalized_data=normalized,
        unknown_columns=mapping.unknown_columns,
        mapping_errors=tuple(errors),
        mapping_warnings=tuple(warnings),
    )


def _distinct(values: list[Any]) -> list[Any]:
    unique: list[Any] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def decode_normalized(spec: EntitySpec, stored: Mapping[str, Any]) -> dict[str, Any]:
    """Typed values from the normalized JSON kept in the ingestion ledger."""
    return {
        field_spec.name: field_spec.from_json(stored[field_spec.name])
        for field_spec in spec.fields
        if stored.get(field_spec.name) is not None
    }
