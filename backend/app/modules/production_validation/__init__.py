"""Program P & Q — Enterprise Production Validation, Security & Pilot Deployment.

Subsystems:
- P.1 / P.2: Minimal Enterprise Integration Contract & Ingestion Lineage
- P.3: Temporal Historical Backtesting without leakage
- P.4: Intelligence Progression Comparator (L1 vs L2 vs L3)
- P.5: Agent Grounding & Hallucination Auditor
- P.6 / P.7 / P.11.7: Tiered Autonomy Guard & Multi-Tenant Security
- P.11.5: Human Decision Benchmark (Cortex vs Human Operator choice)
- P.11.8: Agent Capability Matrix & Execution Lock
- P.9 / P.11.9: Observability Engine & Longitudinal Telemetry
- P.10 / P.11.10: Unified Decision Lifecycle & Boardroom-Ready Pilot Validation Reports
- P.12 / Q.1: Design Partner Pilot Ledger & Coverage-Adjusted Portfolio ROI
- Q.2: Enterprise Data Readiness & Pre-Flight Quality Auditor
"""

from app.modules.production_validation.agent_grounding import AgentGroundingAuditor
from app.modules.production_validation.autonomy_guard import AutonomyGuard
from app.modules.production_validation.backtesting import TemporalBacktester
from app.modules.production_validation.data_contract import EnterpriseContractIngestor
from app.modules.production_validation.data_readiness import EnterpriseDataReadinessAuditor
from app.modules.production_validation.decision_lifecycle import DecisionLifecycleManager
from app.modules.production_validation.human_benchmark import HumanDecisionComparator
from app.modules.production_validation.intelligence_comparator import (
    IntelligenceProgressionHarness,
)
from app.modules.production_validation.observability import (
    CortexObservabilityEngine,
    ObservabilityDashboardSnapshot,
)
from app.modules.production_validation.pilot_demo_harness import (
    EnterprisePilotDemoHarness,
    EnterprisePilotDemoReport,
    PilotDemoStageResult,
)
from app.modules.production_validation.pilot_ledger import (
    DesignPartnerPilotLedger,
    PilotPortfolioSummary,
)
from app.modules.production_validation.security_boundary import (
    AgentCapability,
    AgentCapabilityGuard,
    TenantIsolationValidator,
)
from app.modules.production_validation.validation_models import (
    AgentGroundingAuditResult,
    AutonomyLevel,
    CortexDecisionLifecycle,
    CortexPilotValidationReport,
    DataReadinessReport,
    DataReadinessWarning,
    DisruptionType,
    HumanDecisionBenchmark,
    IntelligenceLevelMetrics,
    IntelligenceProgressionReport,
    MetricComparisonRow,
    MinimalEnterpriseContract,
    PilotCoverageMetrics,
    PilotExclusionReason,
    TemporalBacktestResult,
    TemporalBacktestScenario,
    ValidationEnvironment,
)
from app.modules.production_validation.validation_report import (
    PilotValidationReportGenerator,
)

__all__ = [
    # Models
    "AgentCapability",
    "AgentGroundingAuditResult",
    "AutonomyLevel",
    "CortexDecisionLifecycle",
    "CortexPilotValidationReport",
    "DataReadinessReport",
    "DataReadinessWarning",
    "DisruptionType",
    "EnterprisePilotDemoReport",
    "HumanDecisionBenchmark",
    "IntelligenceLevelMetrics",
    "IntelligenceProgressionReport",
    "MetricComparisonRow",
    "MinimalEnterpriseContract",
    "ObservabilityDashboardSnapshot",
    "PilotCoverageMetrics",
    "PilotDemoStageResult",
    "PilotExclusionReason",
    "PilotPortfolioSummary",
    "TemporalBacktestResult",
    "TemporalBacktestScenario",
    "ValidationEnvironment",
    # Engines & Services
    "AgentCapabilityGuard",
    "AgentGroundingAuditor",
    "AutonomyGuard",
    "CortexObservabilityEngine",
    "DecisionLifecycleManager",
    "DesignPartnerPilotLedger",
    "EnterpriseContractIngestor",
    "EnterpriseDataReadinessAuditor",
    "EnterprisePilotDemoHarness",
    "HumanDecisionComparator",
    "IntelligenceProgressionHarness",
    "PilotValidationReportGenerator",
    "TemporalBacktester",
    "TenantIsolationValidator",
]
