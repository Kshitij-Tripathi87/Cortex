"""Billing — server-side subscription/entitlement enforcement.

The billing gate for the Nexus durable task runtime: subscription validity,
per-plan concurrent task quotas, and per-plan capability entitlements,
enforced server-side at the API/service boundary before expensive or
consequential operations.
"""

from .entitlements import (
    PLAN_CAPABILITY_ENTITLEMENTS,
    PLAN_CONCURRENT_TASK_LIMITS,
    EntitlementDenied,
    EntitlementService,
    EntitlementSnapshot,
)

__all__ = [
    "EntitlementDenied",
    "EntitlementService",
    "EntitlementSnapshot",
    "PLAN_CAPABILITY_ENTITLEMENTS",
    "PLAN_CONCURRENT_TASK_LIMITS",
]
