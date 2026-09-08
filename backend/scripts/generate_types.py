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

    # Sync the freshly regenerated backend/openapi.json into the frontend.
    # Without this, the openapi-typescript step below would consume a stale
    # frontend copy, and the CI drift gate would only catch that *both*
    # files diverged — it would not tell us the frontend openapi.json was
    # generated from a stale source. This sync is the single source of
    # truth: backend/openapi.json is canonical, everything else is a copy.
    import shutil

    frontend_root = backend_root.parent / "frontend"
    fe_openapi = frontend_root / "src" / "types" / "openapi.json"
    shutil.copy2(backend_root / "openapi.json", fe_openapi)
    print(f"\nSynced OpenAPI schema to {fe_openapi.relative_to(frontend_root.parent)}")

    print("\nGenerating TypeScript types from OpenAPI...")
    subprocess.run(
        ["npx", "openapi-typescript", "src/types/openapi.json", "--output", "src/types/api.ts"],
        cwd=frontend_root,
        check=True,
    )

    print("\nDone! TypeScript types generated at frontend/src/types/api.ts")


if __name__ == "__main__":
    main()
