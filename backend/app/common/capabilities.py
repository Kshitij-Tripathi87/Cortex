"""Capability system for agent and user authorization."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.common.errors import PermissionError


class Capability(StrEnum):
    """Execution capabilities within the system."""
    READ = "read"
    ANALYZE = "analyze"
    PROPOSE = "propose"
    SIMULATE = "simulate"
    APPROVE = "approve"
    EXECUTE = "execute"


class CapabilitySet:
    """Immutable set of capabilities with validation."""

    def __init__(self, capabilities: frozenset[Capability]) -> None:
        self._capabilities = capabilities

    @staticmethod
    def for_specialist_agent() -> CapabilitySet:
        """Capabilities for specialist AI agents."""
        return CapabilitySet(
            frozenset({
                Capability.READ,
                Capability.ANALYZE,
                Capability.PROPOSE,
                Capability.SIMULATE,
            })
        )

    @staticmethod
    def for_supervisor() -> CapabilitySet:
        """Capabilities for supervisor/orchestrator AI agents."""
        return CapabilitySet(
            frozenset({
                Capability.READ,
                Capability.ANALYZE,
                Capability.PROPOSE,
                Capability.SIMULATE,
            })
        )

    @staticmethod
    def for_execution_service() -> CapabilitySet:
        """Capabilities for non-AI backend execution services."""
        return CapabilitySet(
            frozenset({
                Capability.READ,
                Capability.EXECUTE,
            })
        )

    @staticmethod
    def for_human_operator() -> CapabilitySet:
        """Capabilities for a human operator accessing the platform."""
        return CapabilitySet(
            frozenset({
                Capability.READ,
                Capability.ANALYZE,
                Capability.PROPOSE,
                Capability.SIMULATE,
                Capability.APPROVE,
                Capability.EXECUTE,
            })
        )

    def has(self, cap: Capability) -> bool:
        """Check if capability exists in the set."""
        return cap in self._capabilities

    def require(self, cap: Capability) -> None:
        """Ensure capability exists in the set or raise PermissionError."""
        if cap not in self._capabilities:
            raise PermissionError(f"Missing required capability: {cap}")

    def __contains__(self, cap: Any) -> bool:
        if isinstance(cap, Capability):
            return cap in self._capabilities
        if isinstance(cap, str):
            try:
                c = Capability(cap)
                return c in self._capabilities
            except ValueError:
                pass
        return False

    def to_list(self) -> list[str]:
        """Convert to a list of strings."""
        return [c.value for c in self._capabilities]
