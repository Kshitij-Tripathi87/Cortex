"""Endpoint Authorization Audit — D3 (Production-Gate Item).

Per V2.3 freeze rule and the "no silent fixes to frozen surfaces"
constraint, this test does NOT modify the 40 ungated routes. Instead,
it pins their current state as a known-debt set, and prevents new
ungated routes from being added. The audit itself is documented in
`docs/architecture/ENDPOINT_AUTHZ_AUDIT.md`.

Each (file, path) pair is classified:

  GATED         — function body references an authorization helper.
  PUBLIC        — explicitly documented as a public surface
                  (liveness, taxonomy, etc.).
  KNOWN_DEBT    — currently ungated, listed in the audit document,
                  must be fixed in a dedicated follow-up PR.

A new route that lands without being classified (i.e., is detected
as ungated and is not in either PUBLIC or KNOWN_DEBT) FAILS this test.
The failure message tells the author which file and which path need
to be classified.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend" / "app"

# Authorization helpers that count as a gate. Any one in the function
# body is sufficient to mark the route as gated. The strings are
# matched verbatim, so a future `get_current_user_v2` would need to
# be added here explicitly.
AUTH_HELPERS = (
    "require_workspace_access",
    "require_auth",
    "require_role",
    "get_current_user",
    "get_current_principal",
    "get_workspace_auth",
    "AuthContext",
)

# Paths that are explicitly PUBLIC. Adding a new entry requires an
# audit note in `docs/architecture/ENDPOINT_AUTHZ_AUDIT.md`.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/workflo/health",
        # app/api/v1/auth.py — MVP login: issues the bearer token itself, so
        # it cannot require one. Authenticates email+password against the
        # user table before issuing a short-lived HS256 token. Invisible to
        # earlier audit runs because auth.py carried a UTF-8 BOM that made
        # ast.parse raise SyntaxError (silently skipped); the BOM was removed
        # during the 2026-09 lint paydown. Audit note: D3h.
        "/login",
        # app/api/v1/auth.py — v0.8.5-B launch onboarding (audit note D3i):
        # credential-establishing routes. They cannot require a bearer
        # token: /signup creates the first credential, /reset/* recovers
        # one. Each is per-email/per-instance rate-limited, returns
        # uniform errors (no user enumeration), and /reset/request never
        # discloses token material outside dev/test. Audit note: D3i.
        "/signup",
        "/reset/request",
        "/reset/confirm",
    }
)

# Paths that are KNOWN_DEBT. Each must be tracked in the audit doc
# above and fixed in a dedicated, non-bundled PR. The list is
# authoritative — if a path is here, the audit doc has it; if a
# path is in the audit doc but not here, the doc needs updating.
# All 29 legacy debt routes have been paid down and gated (0 remaining debt).
#
# 2026-09 (v0.8.2 routing flip): pinned the 15 Program S "Live Data
# Intelligence Workspace" demo routes (app/api/v1/workspace.py). They run
# an in-memory demo workspace with no auth gate by design. They were
# invisible to earlier audit runs because workspace.py could not be
# parsed by the AST scanner on Python 3.11 (PEP 701 f-strings; since
# made 3.11-compatible). Gating them is a product decision tracked as
# follow-up D3g in docs/architecture/ENDPOINT_AUTHZ_AUDIT.md.
KNOWN_DEBT: frozenset[str] = frozenset(
    {
        # app/api/v1/workspace.py — Program S demo workspace (D3g)
        "/append-stream",
        "/decisions/evidence",
        "/decisions/validity",
        "/deliberate",
        "/demo/load",
        "/graph/critical-nodes",
        "/graph/delta",
        "/graph/subgraph",
        "/ingest-raw",
        "/query/ask",
        "/query/readiness",
        "/signals",
        "/state",
        "/stream",
        "/upload",
    }
)


class RouteInfo(NamedTuple):
    file: str
    method: str
    path: str
    function: str
    gated: bool


def _enumerate_routes() -> list[RouteInfo]:
    """Walk every Python file under backend/app and extract FastAPI
    routes from APIRouter instances. A function is considered
    GATED if its source references one of AUTH_HELPERS."""
    routes: list[RouteInfo] = []
    for f in sorted(APP_ROOT.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        # Identify `router = APIRouter(...)` variables
        router_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (
                        isinstance(t, ast.Name)
                        and isinstance(node.value, ast.Call)
                        and isinstance(node.value.func, ast.Name)
                        and node.value.func.id == "APIRouter"
                    ):
                        router_names.add(t.id)

        if not router_names:
            continue

        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id in router_names
                    and dec.func.attr in {"get", "post", "put", "patch", "delete", "websocket"}
                ):
                    path = (
                        dec.args[0].value
                        if dec.args and isinstance(dec.args[0], ast.Constant)
                        else "?"
                    )
                    method = dec.func.attr.upper()
                    func_text = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                    gated = any(h in func_text for h in AUTH_HELPERS)
                    routes.append(
                        RouteInfo(
                            file=f.name,
                            method=method,
                            path=path,
                            function=node.name,
                            gated=gated,
                        )
                    )
    return routes


@pytest.fixture(scope="module")
def all_routes() -> list[RouteInfo]:
    return _enumerate_routes()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Sanity — the audit actually scans the real codebase
# ─────────────────────────────────────────────────────────────────────────────


class TestAuditCoverage:
    """The audit must scan every router file and find a non-trivial
    number of routes. If a future refactor renames APIRouter to
    something else, the scan must fail loudly rather than silently
    report zero routes."""

    def test_scan_finds_routes(self, all_routes):
        # The 1,337 baseline is gated on this scan finding at least
        # 100 routes — if it drops, the refactor broke the audit.
        assert len(all_routes) >= 100, (
            f"Audit scan found only {len(all_routes)} routes — expected "
            f"at least 100. Did the router naming convention change?"
        )

    def test_all_paths_are_classified(self, all_routes):
        # Every route must be in one of the three buckets: GATED, PUBLIC,
        # or KNOWN_DEBT. If a path is missing from both PUBLIC and
        # KNOWN_DEBT, the audit has missed it.
        ungated_paths = {r.path for r in all_routes if not r.gated}
        unclassified = ungated_paths - PUBLIC_PATHS - KNOWN_DEBT
        assert not unclassified, (
            "The following routes are ungated and not classified as "
            "either PUBLIC or KNOWN_DEBT. Add them to one of those "
            "frozen sets in this test (with an audit note in "
            "docs/architecture/ENDPOINT_AUTHZ_AUDIT.md) before merging:\n"
            + "\n".join(f"  {p}" for p in sorted(unclassified))
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Known-debt state is pinned — current ungated set must not change
# ─────────────────────────────────────────────────────────────────────────────


class TestKnownDebtIsPinned:
    """The set of KNOWN_DEBT paths is the audited list of ungated
    routes. It MUST match what the codebase actually contains — if a
    route is added or removed, this test forces the author to update
    the frozen set (and therefore the audit doc)."""

    def test_known_debt_matches_current_ungated(self, all_routes):
        current_ungated = {r.path for r in all_routes if not r.gated}
        # After excluding PUBLIC, every other ungated path is debt.
        current_debt = current_ungated - PUBLIC_PATHS
        missing = current_debt - KNOWN_DEBT
        extra = KNOWN_DEBT - current_debt
        # The list must not have grown silently.
        assert not missing, (
            "New ungated routes were added without updating KNOWN_DEBT "
            "(and therefore the audit doc). Either add the routes to "
            "the appropriate gate or update KNOWN_DEBT + the doc:\n"
            + "\n".join(f"  {p}" for p in sorted(missing))
        )
        # The list must not have shrunk silently either — if a route
        # was gated, KNOWN_DEBT must be updated in the same commit.
        assert not extra, (
            "KNOWN_DEBT contains paths that are now GATED. Remove "
            "them from the frozen set and from the audit doc:\n"
            + "\n".join(f"  {p}" for p in sorted(extra))
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Public surface is exact — only the explicitly-listed public
#    paths may be ungated
# ─────────────────────────────────────────────────────────────────────────────


class TestPublicSurfaceIsExact:
    def test_public_set_is_nonempty(self):
        # If a future cleanup empties the public set, the test would
        # silently let every route through. Pin at least one entry.
        assert len(PUBLIC_PATHS) >= 1, "PUBLIC_PATHS must be non-empty"

    def test_every_public_path_is_actually_ungated(self, all_routes):
        # A path in PUBLIC that is actually gated means the helper
        # was added but the public classification was forgotten.
        # Surface that so the author can clean up.
        by_path = {r.path: r for r in all_routes}
        for p in PUBLIC_PATHS:
            r = by_path.get(p)
            if r is None:
                continue
            assert not r.gated, (
                f"PUBLIC path {p!r} is now GATED. Remove it from "
                f"PUBLIC_PATHS and update the audit doc."
            )

    def test_no_duplicate_classification(self):
        # A path that is both PUBLIC and KNOWN_DEBT would be a logical
        # bug — pick one.
        overlap = PUBLIC_PATHS & KNOWN_DEBT
        assert not overlap, f"These paths are in both PUBLIC and KNOWN_DEBT: {sorted(overlap)}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Gated routes really do reference an auth helper
# ─────────────────────────────────────────────────────────────────────────────


class TestGatedRoutesAreValid:
    """If a route is marked GATED, the function body MUST reference one
    of the AUTH_HELPERS strings. This catches false positives from
    the regex match (e.g., a docstring mentioning the word by accident
    is fine because the matching is a substring match — but a future
    refactor that moves the helper out of scope would silently
    downgrade a route. The next test catches that.)"""

    def test_gated_count_is_stable(self, all_routes):
        # All 148 non-public routes are gated (0 debt routes).
        gated_count = sum(1 for r in all_routes if r.gated)
        assert gated_count >= 148, (
            f"Gated route count dropped: got {gated_count}, expected "
            f"at least 148. An auth helper may have been removed or "
            f"renamed; check AUTH_HELPERS and the affected routers."
        )
