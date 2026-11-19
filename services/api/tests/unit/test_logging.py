"""Log lines are structured and never carry credentials."""

import json
import logging

import pytest

from app.core.logging import JsonLogFormatter, redact


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("connecting to postgresql+psycopg://nexus:hunter2@127.0.0.1:5432/db", "hunter2"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ('{"authorization": "Basic dXNlcjpwYXNz"}', "dXNlcjpwYXNz"),
        ("cookie=session=abcdef; path=/", "abcdef"),
        ("login failed password=hunter2 user=x", "hunter2"),
        ("api_key: sk-123456", "sk-123456"),
        ("token=eyJhbGciOi", "eyJhbGciOi"),
    ],
)
def test_redact_masks_credentials(text: str, secret: str) -> None:
    cleaned = redact(text)

    assert secret not in cleaned
    assert "***" in cleaned


def test_redact_leaves_ordinary_text_alone() -> None:
    text = "Imported 20 rows for batch 4d1b into project DC-IN-001"

    assert redact(text) == text


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_one_json_object_with_the_required_keys() -> None:
    line = JsonLogFormatter().format(_record("hello", batch_id="b-1", rows=3))
    payload = json.loads(line)

    assert set(payload) >= {"timestamp", "level", "logger", "message", "request_id"}
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "hello"
    assert payload["timestamp"].endswith("Z")
    assert payload["batch_id"] == "b-1"
    assert payload["rows"] == 3
    assert "\n" not in line


def test_formatter_redacts_message_extras_and_tracebacks() -> None:
    try:
        raise RuntimeError("cannot reach postgresql+psycopg://nexus:hunter2@db/x")
    except RuntimeError:
        import sys

        record = _record(
            "failed with password=hunter2",
            dsn="postgresql+psycopg://nexus:hunter2@db/x",
        )
        record.exc_info = sys.exc_info()
        line = JsonLogFormatter().format(record)

    assert "hunter2" not in line
    assert "RuntimeError" in json.loads(line)["exception"]
