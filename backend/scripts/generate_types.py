#!/usr/bin/env python3
"""Generate OpenAPI schema and TypeScript types."""

import subprocess
from pathlib import Path


def main():
    backend_root = Path(__file__).parent.parent

    print("Generating OpenAPI schema...")
    subprocess.run(
        ["python", "-m", "scripts.generate_openapi"],
        cwd=backend_root,
        check=True,
    )

    print("\nGenerating TypeScript types from OpenAPI...")
    frontend_root = backend_root.parent / "frontend"
    subprocess.run(
        ["npx", "openapi-typescript", "src/types/openapi.json", "--output", "src/types/api.ts"],
        cwd=frontend_root,
        check=True,
    )

    print("\nDone! TypeScript types generated at frontend/src/types/api.ts")


if __name__ == "__main__":
    main()
