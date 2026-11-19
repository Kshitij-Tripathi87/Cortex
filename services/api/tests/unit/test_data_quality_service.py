"""Data-quality semantics: dimensions are counted side by side, never merged."""

from app.models.enums import QualityDimension
from app.services.data_quality_service import DIMENSION_BY_CODE, count_by_dimension, dimension_of


def test_every_dimension_is_reported_even_when_zero() -> None:
    assert count_by_dimension([]) == {
        "COMPLETENESS": 0,
        "VALIDITY": 0,
        "CONSISTENCY": 0,
        "UNIQUENESS": 0,
        "REFERENTIAL_INTEGRITY": 0,
    }


def test_codes_are_counted_under_their_dimension() -> None:
    counts = count_by_dimension(
        [
            "REQUIRED_FIELD_MISSING",
            "INVALID_DATE",
            "INVALID_DATE",
            "MUST_BE_POSITIVE",
            "CROSS_PROJECT_REFERENCE",
            "DUPLICATE_NATURAL_KEY",
            "REFERENCE_NOT_FOUND",
            "REFERENCE_NOT_FOUND",
            "REFERENCE_INACTIVE",
        ]
    )

    assert counts == {
        "COMPLETENESS": 1,
        "VALIDITY": 3,
        "CONSISTENCY": 1,
        "UNIQUENESS": 1,
        "REFERENTIAL_INTEGRITY": 3,
    }
    assert sum(counts.values()) == 9


def test_the_examples_of_the_playbook_fall_into_the_expected_dimension() -> None:
    assert dimension_of("REQUIRED_FIELD_MISSING") is QualityDimension.COMPLETENESS
    assert dimension_of("MUST_BE_POSITIVE") is QualityDimension.VALIDITY  # PO quantity is zero
    assert dimension_of("CROSS_PROJECT_REFERENCE") is QualityDimension.CONSISTENCY
    assert dimension_of("DUPLICATE_NATURAL_KEY") is QualityDimension.UNIQUENESS
    assert dimension_of("REFERENCE_NOT_FOUND") is QualityDimension.REFERENTIAL_INTEGRITY


def test_an_unlisted_code_is_a_validity_problem() -> None:
    assert dimension_of("SOME_FUTURE_FORMAT_RULE") is QualityDimension.VALIDITY


def test_the_result_is_counts_and_nothing_resembling_a_score() -> None:
    counts = count_by_dimension(["INVALID_DATE"])

    assert set(counts) == {dimension.value for dimension in QualityDimension}
    assert all(isinstance(value, int) for value in counts.values())
    assert not any("score" in key.lower() or "percent" in key.lower() for key in counts)


def test_every_mapped_code_has_a_known_dimension() -> None:
    assert set(DIMENSION_BY_CODE.values()) <= set(QualityDimension)
