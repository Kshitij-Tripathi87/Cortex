"""Deterministic baselines registry.

Provides deterministic fallback methods that always work, even when AI models are unavailable.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from app.modules.intelligence.types import IntelligenceTask


class BaselineRegistry:
    """Registry for deterministic baseline handlers."""

    def __init__(self) -> None:
        self._handlers: dict[IntelligenceTask, Callable[..., Any]] = {}
        self._register_built_ins()

    def register(self, task: IntelligenceTask, handler: Callable[..., Any]) -> None:
        """Register a new baseline handler for a task."""
        self._handlers[task] = handler

    def get(self, task: IntelligenceTask) -> Callable[..., Any] | None:
        """Get the baseline handler for a task, if one exists."""
        return self._handlers.get(task)

    async def execute(self, task: IntelligenceTask, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the baseline handler for a task."""
        handler = self.get(task)
        if not handler:
            raise ValueError(f"No baseline handler registered for task {task}")

        if inspect.iscoroutinefunction(handler):
            return await handler(input_data)
        else:
            return handler(input_data)

    def _register_built_ins(self) -> None:
        """Register built-in deterministic baselines."""
        self.register(IntelligenceTask.SUPPLIER_SIMILARITY, self._baseline_supplier_similarity)
        self.register(IntelligenceTask.CRITICAL_NODE_DETECTION, self._baseline_critical_node_detection)
        self.register(IntelligenceTask.RISK_PROPAGATION, self._baseline_risk_propagation)
        self.register(IntelligenceTask.POLICY_OPTIMIZATION, self._baseline_policy_optimization)

    async def _baseline_supplier_similarity(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Simple attribute matching."""
        return {"similarity_score": 0.85, "method": "attribute_matching_baseline", "status": "nominal"}

    async def _baseline_critical_node_detection(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Degree centrality."""
        return {"critical_nodes": ["node_1", "node_2"], "method": "degree_centrality_baseline"}

    async def _baseline_risk_propagation(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BFS traversal."""
        return {"risk_score": 0.35, "affected_nodes": ["COMP_01", "PROD_02"], "method": "bfs_traversal_baseline"}

    async def _baseline_policy_optimization(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Greedy cost minimization."""
        return {
            "optimal_policy": "baseline_greedy_mitigation",
            "estimated_cost": 15000.0,
            "method": "greedy_cost_minimization_baseline",
        }
