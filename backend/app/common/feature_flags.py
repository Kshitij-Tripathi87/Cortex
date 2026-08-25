"""Feature flags — capability toggles read from Settings.

See ADR-0008 for the MVP wedge decision. Capabilities that are excluded from
the MVP but kept in the codebase (live ERP connectors, simulation studio)
are gated behind feature flags and return 501 Not Implemented when disabled.

Read a flag via:

    from app.common.feature_flags import is_feature_enabled
    if not is_feature_enabled("FEATURE_SIMULATION"):
        raise HTTPException(status_code=501, detail="Simulation not enabled")
"""

from __future__ import annotations

from app.config import Settings, get_settings


def is_feature_enabled(name: str, settings: Settings | None = None) -> bool:
    """Return whether the given feature flag is currently enabled.

    Defaults to False when the flag is not declared in Settings.feature_flags.
    Treats unknown flags as off-by-default for safety.
    """
    s = settings if settings is not None else get_settings()
    return bool(s.feature_flags.get(name, False))
