"""Deferred-import guard test for the disruption engines package.

Locks the architectural boundary: no MVP engine may import anything from
``app.deferred.*``. If this test ever fails, it means the engine layer was
re-wired to depend on Phase 2+ code, which the LOCKED DIRECTIVE explicitly
prohibits.
"""

from __future__ import annotations

import importlib
import sys

DEFERRED_PACKAGES = (
    "app.deferred",
    "app.deferred.workflow_engine",
    "app.deferred.workflow_engine.workflow_engine",
    "app.deferred.workflow_engine.workflow_models",
)


def test_no_deferred_imports_in_engines() -> None:
    """Every engine module must be importable without any deferred module."""
    engine_modules = [
        "app.modules.disruption.engines.types",
        "app.modules.disruption.engines.propagation",
        "app.modules.disruption.engines.impact",
        "app.modules.disruption.engines.confidence",
        "app.modules.disruption.engines.recommendations",
        "app.modules.disruption.engines.timeline",
        "app.modules.disruption.engines.brief",
    ]

    # Drop any previously-imported app.deferred modules from sys.modules to
    # avoid stale-cache false positives.
    for mod_name in list(sys.modules):
        if any(mod_name == p or mod_name.startswith(p + ".") for p in DEFERRED_PACKAGES):
            sys.modules.pop(mod_name, None)

    for name in engine_modules:
        # Clear cached engine modules first so each import re-resolves deps.
        sys.modules.pop(name, None)
        importlib.import_module(name)

    # Now assert none of the deferred packages were pulled in.
    leaked: list[str] = []
    for mod_name in sys.modules:
        if any(mod_name == p or mod_name.startswith(p + ".") for p in DEFERRED_PACKAGES):
            leaked.append(mod_name)

    assert leaked == [], f"Engines leaked deferred imports: {leaked}"
