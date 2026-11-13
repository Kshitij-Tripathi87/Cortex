import json
import sys
from pathlib import Path

# Keep the backend package root importable even when invoked by file path.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app  # noqa: E402  (must follow the backend path bootstrap)


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
