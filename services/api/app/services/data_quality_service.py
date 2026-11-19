"""Data quality: what is missing or invalid, counted and named.

Two kinds of observation, kept apart:

* about source rows (this module, pure): every validation code belongs to
  one quality dimension, and a batch reports how many blocking findings fall
  into each;
* about stored records (functions further down, database-backed): facts that
  are not recorded, such as a purchase order without an acknowledgement
  milestone.

Nothing here produces a score, a percentage or a judgement. "Not recorded"
is a statement about the data, not about a supplier.
"""

from collections.abc import Iterable, Mapping

from app.models.enums import QualityDimension

# Which dimension a validation code speaks about. A code that is not listed
# is a validity problem: the value itself breaks a type, range or format rule.
DIMENSION_BY_CODE: Mapping[str, QualityDimension] = {
    "REQUIRED_FIELD_MISSING": QualityDimension.COMPLETENESS,
    "FORMULA_WITHOUT_CACHED_VALUE": QualityDimension.COMPLETENESS,
    "REQUIRED_ON_SITE_DATE_NOT_RECORDED": QualityDimension.COMPLETENESS,
    "INVALID_DATE": QualityDimension.VALIDITY,
    "INVALID_ENUM": QualityDimension.VALIDITY,
    "INVALID_DECIMAL": QualityDimension.VALIDITY,
    "INVALID_INTEGER": QualityDimension.VALIDITY,
    "INVALID_CURRENCY": QualityDimension.VALIDITY,
    "INVALID_VALUE": QualityDimension.VALIDITY,
    "VALUE_TOO_LONG": QualityDimension.VALIDITY,
    "MUST_BE_POSITIVE": QualityDimension.VALIDITY,
    "MUST_BE_NON_NEGATIVE": QualityDimension.VALIDITY,
    "ROW_SHAPE_MISMATCH": QualityDimension.VALIDITY,
    "AMBIGUOUS_COLUMN_MAPPING": QualityDimension.CONSISTENCY,
    "CROSS_PROJECT_REFERENCE": QualityDimension.CONSISTENCY,
    "IMMUTABLE_FIELD_CONFLICT": QualityDimension.CONSISTENCY,
    "INCONSISTENT_MILESTONE_STATE": QualityDimension.CONSISTENCY,
    "DUPLICATE_NATURAL_KEY": QualityDimension.UNIQUENESS,
    "DUPLICATE_ROW": QualityDimension.UNIQUENESS,
    "REFERENCE_NOT_FOUND": QualityDimension.REFERENTIAL_INTEGRITY,
    "REFERENCE_INACTIVE": QualityDimension.REFERENTIAL_INTEGRITY,
}


def dimension_of(code: str) -> QualityDimension:
    return DIMENSION_BY_CODE.get(code, QualityDimension.VALIDITY)


def count_by_dimension(codes: Iterable[str]) -> dict[str, int]:
    """Number of findings per dimension. Every dimension is present, zero included.

    The five numbers are reported side by side and are never combined.
    """
    counts = {dimension.value: 0 for dimension in QualityDimension}
    for code in codes:
        counts[dimension_of(code).value] += 1
    return counts
