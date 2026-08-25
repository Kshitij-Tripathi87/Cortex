"""Execution Module — Supervised Execution & Closed-Loop Operations.

Program N:
- N.1: Immutable Action Plan (ActionPlan, PlanStatus)
- N.2: Policy & Safety Engine (PolicyEngine, PolicyViolation)
- N.3: Digital Twin Simulation Gate (SimulationGate, SimulationGateResult)
- N.4: Human Decision Control Plane (ApprovalService, DecisionCard, OperatorDecision)
- N.5: Enterprise Execution Adapters (ERPAdapter, WMSAdapter, TMSAdapter, ProcurementAdapter)
- N.6: Decision Memory & Outcome Capture (DecisionMemoryStore, DecisionMemoryRecord)
"""

from app.modules.execution.adapters.base_adapter import EnterpriseAdapter
from app.modules.execution.adapters.erp_adapter import ERPAdapter
from app.modules.execution.adapters.procurement_adapter import ProcurementAdapter
from app.modules.execution.adapters.tms_adapter import TMSAdapter
from app.modules.execution.adapters.wms_adapter import WMSAdapter
from app.modules.execution.approval_service import ApprovalService
from app.modules.execution.decision_memory import DecisionMemoryStore
from app.modules.execution.execution_models import (
    ActionPlan,
    DecisionCard,
    DecisionCardOption,
    DecisionMemoryRecord,
    ExecutionResult,
    ExecutionSystem,
    OperatorDecision,
    PlanStatus,
    PolicyViolation,
    SimulationGateResult,
)
from app.modules.execution.execution_service import ExecutionService
from app.modules.execution.policy_engine import PolicyEngine
from app.modules.execution.simulation_gate import SimulationGate

__all__ = [
    # Models
    "ActionPlan",
    "DecisionCard",
    "DecisionCardOption",
    "DecisionMemoryRecord",
    "ExecutionResult",
    "ExecutionSystem",
    "OperatorDecision",
    "PlanStatus",
    "PolicyViolation",
    "SimulationGateResult",
    # Components
    "ApprovalService",
    "DecisionMemoryStore",
    "EnterpriseAdapter",
    "ExecutionService",
    "PolicyEngine",
    "SimulationGate",
    # Adapters
    "ERPAdapter",
    "ProcurementAdapter",
    "TMSAdapter",
    "WMSAdapter",
]
