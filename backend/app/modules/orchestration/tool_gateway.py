"""Nexus-owned tool gateway contract.

The gateway is the enforcement boundary between framework agents and business
capabilities. Implementations must authorize every invocation and capture
provenance before returning a result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .contracts import AgentContext, CapabilityDescriptor


class ToolGateway(ABC):
    """Safe capability invocation surface exposed to agents."""

    @abstractmethod
    async def invoke(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        """Validate, authorize, execute, and trace one tool invocation."""
        raise NotImplementedError
