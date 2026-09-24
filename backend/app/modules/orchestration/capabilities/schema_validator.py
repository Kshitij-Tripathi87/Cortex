"""Golden-path invocation schema validator for capability input contracts.

Application-owned implementation of the gateway's
``InvocationSchemaValidator`` protocol. Enforces the declared input schema
(required arguments and argument types) without pulling in a JSON-Schema
dependency; the World State capability contracts only use the subset of
JSON-Schema keywords validated here.
"""

from __future__ import annotations

from typing import Any


class JsonSchemaLiteValidator:
    """Minimal JSON-schema enforcement for capability input contracts."""

    _TYPES: dict[str, Any] = {
        "object": dict,
        "string": str,
        "integer": int,
        "boolean": bool,
        "array": list,
        "number": (int, float),
    }

    def validate(self, *, schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        """Raise ValueError when ``arguments`` violate the declared schema."""

        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")
        for name in schema.get("required", []):
            if name not in arguments:
                raise ValueError(f"missing required argument: {name}")
        properties = schema.get("properties", {})
        for key, value in arguments.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue
            prop_type = prop.get("type")
            if not isinstance(prop_type, str):
                continue
            expected = self._TYPES.get(prop_type)
            if expected is None:
                continue
            if prop_type == "integer" and isinstance(value, bool):
                raise ValueError(f"argument '{key}' must be an integer")
            if not isinstance(value, expected):
                raise ValueError(f"argument '{key}' has the wrong type")
