"""Export the OpenAPI document of the API as a stable JSON file.

Usage (from services/api):
    uv run python ../../scripts/export_openapi.py            # write docs/engineering/openapi.json
    uv run python ../../scripts/export_openapi.py --check    # fail if the committed file is stale
    uv run python ../../scripts/export_openapi.py --output path/to/file.json

The document is built from the code alone, with fixed settings and no
database, so the same commit always produces the same bytes.
"""

import argparse
import difflib
import json
import sys
from pathlib import Path
from uuid import UUID

from app.core.config import REPO_ROOT, Settings
from app.main import create_app

DEFAULT_OUTPUT = REPO_ROOT / "docs" / "engineering" / "openapi.json"


def render() -> str:
    settings = Settings(
        _env_file=None,
        app_env="development",
        app_name="cortex-nexus-api",
        api_v1_prefix="/api/v1",
        # Never connected to: building the document opens no connection.
        database_url="postgresql+psycopg://export:export@127.0.0.1:5432/export",
        log_level="WARNING",
        nexus_dev_workspace_id=UUID("00000000-0000-4000-8000-000000000001"),
    )
    document = create_app(settings).openapi()
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if the file differs from the code",
    )
    arguments = parser.parse_args()

    rendered = render()
    output: Path = arguments.output

    if arguments.check:
        current = output.read_text(encoding="utf-8") if output.exists() else None
        if current == rendered:
            print(f"{output} is up to date.")
            return 0
        reason = "does not exist" if current is None else "differs from the code"
        print(
            f"{output} {reason}. Run `make openapi` and commit the result.",
            file=sys.stderr,
        )
        if current is not None:
            diff = difflib.unified_diff(
                current.splitlines(),
                rendered.splitlines(),
                fromfile=str(output),
                tofile="generated OpenAPI",
                lineterm="",
            )
            print("\\n".join(diff), file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    paths = len(json.loads(rendered)["paths"])
    print(f"Wrote {output} ({paths} paths, {len(rendered.encode('utf-8'))} bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
