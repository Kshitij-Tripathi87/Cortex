"""Base Enterprise Execution Adapter Protocol.

Program N.5 (Enterprise Execution Adapters):
Standard contract for all downstream connectors (ERP, WMS, TMS, Procurement):
- Typed request payloads
- Idempotency guarantees
- Audit logging & latency measurement
- Rollback & compensation hooks
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.execution.execution_models import ActionPlan, ExecutionResult, ExecutionSystem


class EnterpriseAdapter(ABC):
    """Abstract base class for all enterprise system adapters."""

    def __init__(self, system_type: ExecutionSystem):
        self.system_type = system_type

    @abstractmethod
    def execute(
        self,
        plan: ActionPlan,
        idempotency_key: str,
    ) -> ExecutionResult:
        """Execute the ActionPlan against the external enterprise system."""
        pass

    @abstractmethod
    def rollback(
        self,
        execution_id: str,
        external_transaction_id: str,
    ) -> bool:
        """Execute compensating transaction to roll back an execution."""
        pass
