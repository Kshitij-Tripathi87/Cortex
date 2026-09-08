"""Agent Safety Budget — prevents runaway agent loops and bounds execution costs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.common.errors import CortexError


class BudgetStatus(StrEnum):
    WITHIN_LIMITS = "WITHIN_LIMITS"
    WARNING = "WARNING"
    EXCEEDED = "EXCEEDED"


class BudgetExceededError(CortexError):
    code = "budget_exceeded"
    http_status = 400
    category = "client"


@dataclass
class SafetyBudget:
    """Tracks token, time, and monetary limits during an agent run."""

    max_tokens: int = 100_000
    max_time_seconds: float = 120.0
    max_messages: int = 50
    max_iterations: int = 10
    max_cost_usd: float = 10.0
    max_tool_calls: int = 20

    _tokens: int = field(default=0, init=False)
    _messages: int = field(default=0, init=False)
    _cost: float = field(default=0.0, init=False)
    _tool_calls: int = field(default=0, init=False)
    _iterations: int = field(default=0, init=False)
    _start_time: float = field(default_factory=time.time, init=False)

    def track(
        self,
        tokens: int = 0,
        messages: int = 0,
        cost: float = 0.0,
        tool_calls: int = 0,
        iterations: int = 0,
    ) -> None:
        """Record consumption of resources."""
        self._tokens += tokens
        self._messages += messages
        self._cost += cost
        self._tool_calls += tool_calls
        self._iterations += iterations

    def check(self) -> BudgetStatus:
        """Check current budget status."""
        if (
            self._tokens > self.max_tokens
            or self.elapsed_seconds > self.max_time_seconds
            or self._messages > self.max_messages
            or self._iterations > self.max_iterations
            or self._cost > self.max_cost_usd
            or self._tool_calls > self.max_tool_calls
        ):
            return BudgetStatus.EXCEEDED

        util = self.utilization
        if any(v > 0.8 for v in util.values()):
            return BudgetStatus.WARNING

        return BudgetStatus.WITHIN_LIMITS

    def enforce(self) -> None:
        """Raise an error if budget is exceeded."""
        status = self.check()
        if status == BudgetStatus.EXCEEDED:
            raise BudgetExceededError("Safety budget exceeded.", details=[self.to_dict()])

    @property
    def elapsed_seconds(self) -> float:
        """Seconds elapsed since budget initialization."""
        return time.time() - self._start_time

    @property
    def remaining(self) -> dict[str, float | int]:
        """Amount of resources left before exceeding limits."""
        return {
            "tokens": max(0, self.max_tokens - self._tokens),
            "time_seconds": max(0.0, self.max_time_seconds - self.elapsed_seconds),
            "messages": max(0, self.max_messages - self._messages),
            "iterations": max(0, self.max_iterations - self._iterations),
            "cost_usd": max(0.0, self.max_cost_usd - self._cost),
            "tool_calls": max(0, self.max_tool_calls - self._tool_calls),
        }

    @property
    def utilization(self) -> dict[str, float]:
        """Percentage utilization of allocated resources."""
        return {
            "tokens": self._tokens / self.max_tokens if self.max_tokens else 0,
            "time_seconds": self.elapsed_seconds / self.max_time_seconds
            if self.max_time_seconds
            else 0,
            "messages": self._messages / self.max_messages if self.max_messages else 0,
            "iterations": self._iterations / self.max_iterations if self.max_iterations else 0,
            "cost_usd": self._cost / self.max_cost_usd if self.max_cost_usd else 0,
            "tool_calls": self._tool_calls / self.max_tool_calls if self.max_tool_calls else 0,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize budget state for audit or logging."""
        return {
            "limits": {
                "max_tokens": self.max_tokens,
                "max_time_seconds": self.max_time_seconds,
                "max_messages": self.max_messages,
                "max_iterations": self.max_iterations,
                "max_cost_usd": self.max_cost_usd,
                "max_tool_calls": self.max_tool_calls,
            },
            "current": {
                "tokens": self._tokens,
                "elapsed_seconds": self.elapsed_seconds,
                "messages": self._messages,
                "iterations": self._iterations,
                "cost_usd": self._cost,
                "tool_calls": self._tool_calls,
            },
            "status": self.check().value,
        }
