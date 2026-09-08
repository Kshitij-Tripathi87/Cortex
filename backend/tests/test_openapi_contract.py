"""OpenAPI contract drift guard — D2 (G9 in the production-gate tracker).

Pins the single-source-of-truth invariant: the OpenAPI schema committed
to the frontend tree MUST be byte-identical to the one the backend
generates. The CI gate (.github/workflows/typecheck.yml, "openapi-types"
job) regenerates from the backend, then runs `git diff --exit-code` on
the two openapi.json files. This test is the local equivalent that runs
in `pytest`, so a developer who skips the regen-and-commit step is
caught by `pytest` before the diff even reaches CI.

The frontend `api.ts` is a deterministic function of openapi.json, so
checking the schema files is sufficient — checking the generated TS too
would be a tautology (it would only ever fail if openapi-typescript
itself changed).
"""

from __future__ import annotations

import filecmp
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_OPENAPI = REPO_ROOT / "backend" / "openapi.json"
FRONTEND_OPENAPI = REPO_ROOT / "frontend" / "src" / "types" / "openapi.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


@pytest.mark.regression
class TestOpenAPIDrift:
    """The OpenAPI schema is the contract. Drift between the backend's
    live-generated schema and the frontend's committed copy means a
    type, endpoint, or error envelope has changed and was not propagated
    across the boundary."""

    def test_both_openapi_files_exist(self):
        # If either side is missing, the typechain is broken — the frontend
        # would have a hand-written or stale schema. Fail fast.
        assert BACKEND_OPENAPI.is_file(), (
            "backend/openapi.json is missing — run `python -m scripts.generate_openapi`"
        )
        assert FRONTEND_OPENAPI.is_file(), (
            "frontend/src/types/openapi.json is missing — run "
            "`python -m scripts.generate_types` to refresh"
        )

    def test_openapi_schemas_are_byte_identical(self):
        # Byte-identity is the strongest contract: any change to the wire
        # shape (new endpoint, new error envelope, renamed field) MUST be
        # committed on both sides in the same changeset. This is what the
        # CI `git diff --exit-code` enforces; this test pins the same
        # invariant at the unit level.
        assert filecmp.cmp(BACKEND_OPENAPI, FRONTEND_OPENAPI, shallow=False), (
            f"OpenAPI drift: {BACKEND_OPENAPI} and {FRONTEND_OPENAPI} differ.\n"
            f"  backend sha256: {_sha256(BACKEND_OPENAPI)}\n"
            f"  frontend sha256: {_sha256(FRONTEND_OPENAPI)}\n"
            f"Run `python -m scripts.generate_types` to refresh and commit."
        )

    def test_openapi_version_is_3_1(self):
        # The schema's `openapi` field is a non-empty string the frontend
        # type generator reads. Pinning it to "3.1.0" prevents silent
        # downgrades that would strip nullable / oneOf / etc.
        import json

        backend_doc = json.loads(BACKEND_OPENAPI.read_text(encoding="utf-8"))
        assert backend_doc.get("openapi", "").startswith("3.1"), (
            f"OpenAPI version regressed: got {backend_doc.get('openapi')!r}"
        )
        fe_doc = json.loads(FRONTEND_OPENAPI.read_text(encoding="utf-8"))
        assert fe_doc.get("openapi", "").startswith("3.1"), (
            f"Frontend OpenAPI version regressed: got {fe_doc.get('openapi')!r}"
        )

    def test_openapi_has_paths_and_components(self):
        # Both `paths` and `components.schemas` are required for the
        # type generator to produce useful TS — a schema with no
        # `paths` is a generation failure, not a real spec.
        import json

        for label, path in (("backend", BACKEND_OPENAPI), ("frontend", FRONTEND_OPENAPI)):
            doc = json.loads(path.read_text(encoding="utf-8"))
            assert doc.get("paths"), f"{label} OpenAPI has no `paths`"
            assert doc.get("components", {}).get("schemas"), (
                f"{label} OpenAPI has no `components.schemas`"
            )

    def test_generate_types_script_will_sync_schema(self):
        # Belt-and-suspenders: the generator script must include the
        # copy step, otherwise a future refactor that drops it would
        # silently break the drift gate. Read the file and assert the
        # copy line is present.
        script = REPO_ROOT / "backend" / "scripts" / "generate_types.py"
        assert script.is_file(), "generate_types.py missing"
        text = script.read_text(encoding="utf-8")
        # The sync step is the line that copies backend/openapi.json
        # into frontend/src/types/openapi.json. Look for the copy
        # (shutil.copy2 / copyfile / copy) AND the target path string.
        assert "shutil" in text and "frontend" in text and "openapi.json" in text, (
            "generate_types.py no longer syncs backend/openapi.json → "
            "frontend/src/types/openapi.json. Without this, the CI drift "
            "gate cannot detect a frontend copy that was never refreshed "
            "from a backend change. Re-add the shutil.copy2 line."
        )
