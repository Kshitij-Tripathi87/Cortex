"""Country names and codes, as the Ask box reads them from a question.

Files store "DE"; people ask about "Germany" or "German suppliers". The table
must be right, because a wrong code would silently filter on the wrong
country, and it must not see countries in ordinary words.
"""

from __future__ import annotations

import pytest

from app.modules.nexus_spine.p0_migration import country_names
from app.modules.nexus_spine.p0_migration.country_names import (
    countries_mentioned,
    country_code,
    country_name,
    is_country_field,
)


def _rows() -> list[list[str]]:
    return [line.split("|") for line in country_names._TABLE.strip().splitlines()]


def test_every_row_has_a_unique_code_and_a_name() -> None:
    rows = _rows()
    assert len(rows) > 200
    codes = [row[0] for row in rows]
    threes = [row[1] for row in rows]
    assert len(set(codes)) == len(codes)
    assert len(set(threes)) == len(threes)
    for code, three, names, _adjectives in rows:
        assert len(code) == 2 and code.isalpha() and code.isupper(), code
        assert len(three) == 3 and three.isalpha() and three.isupper(), three
        assert names.split(";")[0].strip(), code
    # No name or adjective may belong to two countries.
    seen: dict[str, str] = {}
    for code, _three, names, adjectives in rows:
        for text in [*names.split(";"), *adjectives.split(";")]:
            key = country_names._normalize(text)
            if not key:
                continue
            assert seen.setdefault(key, code) == code, (
                f"{text!r} is listed for {seen[key]} and {code}"
            )


@pytest.mark.parametrize(
    ("code", "three", "name"),
    [
        ("DE", "DEU", "Germany"),
        ("IN", "IND", "India"),
        ("CN", "CHN", "China"),
        ("JP", "JPN", "Japan"),
        ("SE", "SWE", "Sweden"),
        ("US", "USA", "United States"),
        ("GB", "GBR", "United Kingdom"),
        ("CH", "CHE", "Switzerland"),
        ("NL", "NLD", "Netherlands"),
        ("KR", "KOR", "South Korea"),
        ("ZA", "ZAF", "South Africa"),
        ("AE", "ARE", "United Arab Emirates"),
        ("ES", "ESP", "Spain"),
        ("PT", "PRT", "Portugal"),
        ("PL", "POL", "Poland"),
        ("MX", "MEX", "Mexico"),
        ("BR", "BRA", "Brazil"),
        ("VN", "VNM", "Vietnam"),
        ("TR", "TUR", "Turkey"),
        ("AT", "AUT", "Austria"),
        ("AU", "AUS", "Australia"),
    ],
)
def test_well_known_codes_are_right(code: str, three: str, name: str) -> None:
    assert country_name(code) == name
    assert country_code(code) == code
    assert country_code(code.lower()) == code
    assert country_code(three) == code
    assert country_code(name) == code
    assert country_code(f"  {name.upper()} ") == code


def test_stored_values_are_read_in_their_usual_spellings() -> None:
    assert country_code("U.S.A.") == "US"
    assert country_code("United States of America") == "US"
    assert country_code("U.K.") == "GB"
    assert country_code("Great Britain") == "GB"
    assert country_code("Holland") == "NL"
    assert country_code("Côte d'Ivoire") == "CI"
    assert country_code("Türkiye") == "TR"
    # Not countries.
    assert country_code("Pune") is None
    assert country_code("XX") is None
    assert country_code("") is None
    assert country_code("tier_1") is None


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Which suppliers are in Germany?", {"DE"}),
        ("suppliers in india", {"IN"}),
        ("German suppliers", {"DE"}),
        ("which indian vendors are late", {"IN"}),
        ("Swiss and Swedish suppliers", {"CH", "SE"}),
        ("suppliers in the UK or the USA", {"GB", "US"}),
        ("vendors in the UAE", {"AE"}),
        ("suppliers in DEU and IND", {"DE", "IN"}),
        ("orders from the Netherlands", {"NL"}),
        # The longer name wins and is used once.
        ("vendors from South Korea", {"KR"}),
        ("vendors from North Korea", {"KP"}),
        ("parts from Papua New Guinea", {"PG"}),
        ("Guinea-Bissau vs Guinea", {"GW", "GN"}),
        ("Dominican Republic and Dominica", {"DO", "DM"}),
        ("South Sudan", {"SS"}),
        ("suppliers in Northern Ireland", {"GB"}),
        ("WHICH SUPPLIERS ARE IN GERMANY", {"DE"}),
    ],
)
def test_countries_named_in_a_question(question: str, expected: set[str]) -> None:
    assert set(countries_mentioned(question)) == expected


@pytest.mark.parametrize(
    "question",
    [
        # Ordinary words that are also codes or short names.
        "is it late, tell us",
        "suppliers in us",
        "Which suppliers ARE late and CAN deliver?",
        "price PER unit",
        # A language, not a country.
        "answer in German please",
        "show the French version",
        # A continent is not the country in its name.
        "suppliers in South America",
        "Latin American vendors",
        # Places that contain a country name.
        "the plant in New Mexico",
        "shipments across the Indian Ocean",
        # Nothing geographic at all.
        "Which purchase orders are delayed?",
        "tell me about Bharat Castings",
    ],
)
def test_ordinary_words_are_not_countries(question: str) -> None:
    assert countries_mentioned(question) == {}


def test_the_words_that_named_the_country_are_reported() -> None:
    assert countries_mentioned("Which suppliers are in Germany?") == {"DE": "germany"}
    assert countries_mentioned("German suppliers") == {"DE": "german"}
    assert countries_mentioned("vendors in the UK") == {"GB": "UK"}


@pytest.mark.parametrize(
    "field",
    ["country", "Country", "country_code", "origin_country", "supplier_country", "countryOfOrigin"],
)
def test_country_columns_are_recognised(field: str) -> None:
    assert is_country_field(field)


@pytest.mark.parametrize(
    "field", ["city", "status", "designation", "coordination", "nationality", "name", "tier"]
)
def test_other_columns_are_not_country_columns(field: str) -> None:
    assert not is_country_field(field)
