"""Program P — Enterprise Production Validation API v1.

Endpoints:
- POST /validation/ingest-contract — Ingest minimal enterprise contract tables
- POST /validation/backtest — Execute temporal historical backtesting without future leakage
- POST /validation/intelligence-comparison — Benchmark L1 vs L2 vs L3 intelligence tiers
- POST /validation/agent-audit — Audit agent proposal for evidence grounding & hallucination
- GET /validation/observability — Retrieve operational control plane and correctness trajectory
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.multi_agent.agent_models import AgentProposal, AgentRole
from app.modules.production_validation.agent_grounding import AgentGroundingAuditor
from app.modules.production_validation.backtesting import TemporalBacktester
from app.modules.production_validation.data_contract import EnterpriseContractIngestor
from app.modules.production_validation.data_readiness import EnterpriseDataReadinessAuditor
from app.modules.production_validation.intelligence_comparator import IntelligenceProgressionHarness
from app.modules.production_validation.observability import CortexObservabilityEngine
from app.modules.production_validation.pilot_ledger import DesignPartnerPilotLedger
from app.modules.production_validation.validation_models import (
    DisruptionType,
    MinimalEnterpriseContract,
    TemporalBacktestScenario,
)
from app.modules.production_validation.validation_report import PilotValidationReportGenerator
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_repository import StateRepository

router = APIRouter()
logger = logging.getLogger(__name__)

_contract_ingestor = EnterpriseContractIngestor()
_readiness_auditor = EnterpriseDataReadinessAuditor()
_backtester = TemporalBacktester()
_progression_harness = IntelligenceProgressionHarness()
_grounding_auditor = AgentGroundingAuditor()
_observability_engine = CortexObservabilityEngine()
_report_generator = PilotValidationReportGenerator()
_pilot_ledger = DesignPartnerPilotLedger()


# ─────────────────────────────────────────────────────────────────────────────
# Request Schemas
# ─────────────────────────────────────────────────────────────────────────────


class DataReadinessAuditRequest(BaseModel):
    workspace_id: str
    customer_name: str
    suppliers: list[dict[str, Any]]
    components: list[dict[str, Any]] = []
    bill_of_materials: list[dict[str, Any]] = []
    warehouses: list[dict[str, Any]] = []
    inventory_levels: list[dict[str, Any]] = []
    factories: list[dict[str, Any]] = []
    purchase_orders: list[dict[str, Any]] = []


class IngestContractRequest(BaseModel):
    workspace_id: str
    world_id: str
    suppliers: list[dict[str, Any]]
    components: list[dict[str, Any]] = []
    bill_of_materials: list[dict[str, Any]] = []
    warehouses: list[dict[str, Any]] = []
    inventory_levels: list[dict[str, Any]] = []
    factories: list[dict[str, Any]] = []
    purchase_orders: list[dict[str, Any]] = []


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/data-readiness")
async def audit_enterprise_data_readiness(
    req: DataReadinessAuditRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Pre-flight audit of customer data completeness before pilot activation."""
    require_workspace_access(req.workspace_id, auth)

    checksum = _contract_ingestor.compute_sha256_checksum(req.model_dump())

    contract = MinimalEnterpriseContract(
        suppliers=req.suppliers,
        components=req.components,
        bill_of_materials=req.bill_of_materials,
        warehouses=req.warehouses,
        inventory_levels=req.inventory_levels,
        factories=req.factories,
        purchase_orders=req.purchase_orders,
        source_checksum_sha256=checksum,
    )

    report = _readiness_auditor.audit_customer_data(req.customer_name, contract)
    return report.to_dict()


class TemporalBacktestRequest(BaseModel):
    workspace_id: str
    pre_event_world_id: str
    incident_name: str
    disruption_type: DisruptionType
    disrupted_entity_id: str
    ground_truth_actual_revenue_loss_usd: float
    ground_truth_affected_products: list[str]
    ground_truth_stockout_hours: float
    ground_truth_recovery_days: float
    version: int = 1


class AgentGroundingAuditRequest(BaseModel):
    workspace_id: str
    world_id: str
    proposal: dict[str, Any]
    version: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/ingest-contract")
async def ingest_minimal_contract(
    req: IngestContractRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Ingest minimal enterprise customer data tables into an immutable WorldState."""
    require_workspace_access(req.workspace_id, auth)

    checksum = _contract_ingestor.compute_sha256_checksum(req.model_dump())

    contract = MinimalEnterpriseContract(
        suppliers=req.suppliers,
        components=req.components,
        bill_of_materials=req.bill_of_materials,
        warehouses=req.warehouses,
        inventory_levels=req.inventory_levels,
        factories=req.factories,
        purchase_orders=req.purchase_orders,
        source_checksum_sha256=checksum,
    )

    world_state = _contract_ingestor.ingest_and_reconstruct_world_state(
        workspace_id=req.workspace_id,
        world_id=req.world_id,
        contract=contract,
    )

    repo = StateRepository(db)
    await repo.create(world_state)

    return {
        "world_id": world_state.world_id,
        "workspace_id": world_state.workspace_id,
        "variables_count": len(world_state.variables),
        "contract_summary": contract.to_dict(),
    }


@router.post("/backtest")
async def run_temporal_backtest(
    req: TemporalBacktestRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Run temporal backtest starting at T_0 without knowledge of the future."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    pre_state = await repo.get(req.pre_event_world_id, req.workspace_id, req.version)
    if not pre_state or pre_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="Pre-event world state not found")

    scenario = TemporalBacktestScenario(
        scenario_id=f"scen_{req.disrupted_entity_id}",
        incident_name=req.incident_name,
        disruption_type=req.disruption_type,
        pre_event_world_id=req.pre_event_world_id,
        disrupted_entity_id=req.disrupted_entity_id,
        ground_truth_actual_revenue_loss_usd=req.ground_truth_actual_revenue_loss_usd,
        ground_truth_affected_products=req.ground_truth_affected_products,
        ground_truth_stockout_hours=req.ground_truth_stockout_hours,
        ground_truth_recovery_days=req.ground_truth_recovery_days,
    )

    result = _backtester.run_backtest(scenario, pre_state)
    return result.to_dict()


@router.post("/intelligence-comparison")
async def compare_intelligence_tiers(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Benchmark L1 (Deterministic) vs L2 (+GNN) vs L3 (+RL+Agents) intelligence tiers."""
    require_workspace_access(workspace_id, auth)

    report = _progression_harness.compare_tiers([])
    return report.to_dict()


@router.post("/agent-audit")
async def audit_agent_grounding(
    req: AgentGroundingAuditRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Audit agent proposal for hallucinated facts and evidence citations."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    p_dict = req.proposal
    act_dict = p_dict["proposed_action"]
    action = MitigationAction(
        action_type=ActionType(act_dict["action_type"]),
        entity_id=act_dict["entity_id"],
        quantity=act_dict.get("quantity", 0.0),
        target_entity_id=act_dict.get("target_entity_id"),
        cost_usd=act_dict.get("cost_usd", 0.0),
    )

    role_val = p_dict["agent_role"]
    try:
        agent_role = AgentRole(role_val)
    except ValueError:
        agent_role = AgentRole.SOURCING_SPECIALIST

    proposal = AgentProposal(
        proposal_id=p_dict["proposal_id"],
        agent_role=agent_role,
        agent_name=p_dict.get("agent_name", "Specialist Agent"),
        proposed_action=action,
        estimated_cost_usd=p_dict["estimated_cost_usd"],
        estimated_revenue_protected_usd=p_dict["estimated_revenue_protected_usd"],
        confidence_score=p_dict["confidence_score"],
        domain_rationale=p_dict.get("domain_rationale", p_dict.get("rationale", "")),
        supporting_evidence=p_dict.get("supporting_evidence", []),
    )

    audit_res = _grounding_auditor.audit_proposal(proposal, world_state)
    return audit_res.to_dict()


class GeneratePilotReportRequest(BaseModel):
    workspace_id: str
    customer_name: str
    incident_title: str
    data_source_summary: str
    predicted_revenue_risk_usd: float
    actual_revenue_loss_usd: float
    predicted_stockout_hours: float
    actual_stockout_hours: float
    predicted_orders_impacted: int
    actual_orders_impacted: int
    predicted_recovery_days: float
    actual_recovery_days: float
    cortex_action_name: str
    cortex_cost_usd: float
    cortex_protected_revenue_usd: float
    human_action_name: str
    human_cost_usd: float
    human_protected_revenue_usd: float


@router.post("/pilot-report")
async def generate_pilot_validation_report(
    req: GeneratePilotReportRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Generate the canonical CFO/COO Pilot Validation Report."""
    require_workspace_access(req.workspace_id, auth)

    report = _report_generator.generate_pilot_validation_report(
        customer_name=req.customer_name,
        incident_title=req.incident_title,
        data_source_summary=req.data_source_summary,
        predicted_revenue_risk_usd=req.predicted_revenue_risk_usd,
        actual_revenue_loss_usd=req.actual_revenue_loss_usd,
        predicted_stockout_hours=req.predicted_stockout_hours,
        actual_stockout_hours=req.actual_stockout_hours,
        predicted_orders_impacted=req.predicted_orders_impacted,
        actual_orders_impacted=req.actual_orders_impacted,
        predicted_recovery_days=req.predicted_recovery_days,
        actual_recovery_days=req.actual_recovery_days,
        cortex_action_name=req.cortex_action_name,
        cortex_cost_usd=req.cortex_cost_usd,
        cortex_protected_revenue_usd=req.cortex_protected_revenue_usd,
        human_action_name=req.human_action_name,
        human_cost_usd=req.human_cost_usd,
        human_protected_revenue_usd=req.human_protected_revenue_usd,
    )
    _pilot_ledger.record_incident_report(report)
    return report.to_dict()


@router.get("/portfolio-summary")
async def get_portfolio_summary(
    customer_name: str = Query(...),
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve cumulative ROI and win rate across all evaluated partner incidents."""
    require_workspace_access(workspace_id, auth)

    summary = _pilot_ledger.generate_portfolio_summary(customer_name)
    return summary.to_dict()


@router.get("/observability")
async def get_observability_dashboard(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve operational dashboard: Is Cortex Becoming More Correct?"""
    require_workspace_access(workspace_id, auth)

    dash = _observability_engine.generate_dashboard(workspace_id)
    return dash.to_dict()
