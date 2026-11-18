"""Plan rules that need no database: which plans exist and when one is active.

Kept free of imports from the rest of the application, so that the billing
gate, ``GET /auth/me`` and the operator script (``scripts/admin_orgs.py``)
all answer "is this organization's plan active?" with the same rule.
"""

from __future__ import annotations

from datetime import UTC, datetime

TRIAL_PLAN = "trial"

# Plans that never expire. "trial" is time-boxed by ``trial_ends_at``.
NON_EXPIRING_PLANS: frozenset[str] = frozenset({"free", "pro", "enterprise"})

# Every plan an organization may be given. A plan outside this list is never
# active (see ``subscription_is_active``), so nothing may write one.
KNOWN_PLANS: tuple[str, ...] = (TRIAL_PLAN, "free", "pro", "enterprise")

# What an expired plan pauses. One sentence, used wherever the pause is
# explained, so the API and the operator tool cannot drift apart.
PAUSED_ACTIONS = "Creating, running and approving tasks is paused; existing data stays available."


def as_utc(value: datetime) -> datetime:
    """SQLite reads back naive datetimes even for timezone=True columns."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def subscription_is_active(
    plan: str, trial_ends_at: datetime | None, *, now: datetime | None = None
) -> bool:
    """Non-expiring plans are active; a trial is active until ``trial_ends_at``.

    A trial without an end date does not expire. A plan that is not in
    ``KNOWN_PLANS`` is not active.
    """
    if plan in NON_EXPIRING_PLANS:
        return True
    if plan == TRIAL_PLAN:
        if trial_ends_at is None:
            return True
        return as_utc(trial_ends_at) >= (now or datetime.now(UTC))
    return False


def describe_inactive(organization_name: str, plan: str, trial_ends_at: datetime | None) -> str:
    """The sentence a caller reads when the billing gate refuses (HTTP 402)."""
    if plan == TRIAL_PLAN and trial_ends_at is not None:
        ended = as_utc(trial_ends_at)
        reason = f"The trial of '{organization_name}' ended on {ended.day} {ended:%b %Y}."
    else:
        reason = f"The plan '{plan}' of '{organization_name}' is not active."
    return f"{reason} {PAUSED_ACTIONS} Contact the Cortex team to continue."


__all__ = [
    "KNOWN_PLANS",
    "NON_EXPIRING_PLANS",
    "PAUSED_ACTIONS",
    "TRIAL_PLAN",
    "as_utc",
    "describe_inactive",
    "subscription_is_active",
]
