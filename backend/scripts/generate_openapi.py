import json
import sys
from pathlib import Path

# Make the repo root importable (product.workflo_api lives outside backend/).
# Without this, `python -m scripts.generate_openapi` from backend/ fails on
# `from product.workflo_api import ...` in app.api.v1.router — the same
# command the CI openapi-types job runs.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.main import app  # noqa: E402  (must follow the sys.path bootstrap)


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
