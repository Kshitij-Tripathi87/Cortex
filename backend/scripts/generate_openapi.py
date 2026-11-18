import json
import os
from pathlib import Path

# This script only reads the route table, so it names its own environment:
# CORTEX_ENV has no default, and the generated contract must not depend on
# whatever happens to be set in the caller's shell.
os.environ.setdefault("CORTEX_ENV", "test")

from app.main import app  # noqa: E402


def main() -> None:
    """Generate OpenAPI schema and write to frontend types directory."""
    openapi_schema = app.openapi()

    backend_root = Path(__file__).parent.parent
    frontend_types = backend_root.parent / "frontend" / "src" / "types"
    frontend_types.mkdir(parents=True, exist_ok=True)

    output_path = backend_root / "openapi.json"
    output_path.write_text(json.dumps(openapi_schema, indent=2))

    frontend_output = frontend_types / "openapi.json"
    frontend_output.write_text(json.dumps(openapi_schema, indent=2))

    print("OpenAPI schema written to:")
    print(f"  - {output_path}")
    print(f"  - {frontend_output}")


if __name__ == "__main__":
    main()
