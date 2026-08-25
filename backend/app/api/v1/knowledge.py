"""Knowledge API v1 — Rules, constraints, playbooks, SLAs, and policies.

Endpoints:
- GET /knowledge/rules — List business rules
- POST /knowledge/rules — Create a business rule
- GET /knowledge/constraints — List constraints
- POST /knowledge/evaluate — Evaluate rules against world state
- GET /knowledge/playbooks — List playbooks
- GET /knowledge/slas — List SLAs
- GET /knowledge/policies — List policies

Security:
- Every endpoint resolves a principal via get_current_user
- Workspace access enforced via require_workspace_access
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.knowledge.knowledge_models import (
    SLA,
    KnowledgeConstraint,
    KnowledgePolicy,
    KnowledgeRule,
    Playbook,
    RuleAction,
    RuleCondition,
    RuleSeverity,
    RuleTrigger,
)
from app.modules.knowledge.rule_engine import RuleEngine

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class RuleConditionRequest(BaseModel):
    variable_id: str
    operator: str  # eq, ne, lt, le, gt, ge, in, between, contains
    value: Any


class RuleTriggerRequest(BaseModel):
    conditions: list[RuleConditionRequest]
    combinator: str = "and"


class CreateRuleRequest(BaseModel):
    workspace_id: str
    name: str
    description: str
    trigger: RuleTriggerRequest
    action: RuleAction
    severity: RuleSeverity = RuleSeverity.MEDIUM
    action_params: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class RuleResponse(BaseModel):
    rule_id: str
    workspace_id: str
    name: str
    description: str
    action: str
    severity: str
    enabled: bool
    tags: list[str]


class EvaluateRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int | None = None
    rule_ids: list[str] = Field(default_factory=list)
    constraint_ids: list[str] = Field(default_factory=list)
    sla_ids: list[str] = Field(default_factory=list)


class EvaluateResponse(BaseModel):
    state_hash: str
    total_rules_evaluated: int
    total_constraints_evaluated: int
    total_slas_evaluated: int
    fired_rules: list[dict[str, Any]]
    constraint_violations: list[dict[str, Any]]
    sla_breaches: list[dict[str, Any]]
    has_blocking_violations: bool


class PlaybookResponse(BaseModel):
    playbook_id: str
    name: str
    description: str
    step_count: int
    severity: str
    estimated_total_duration_minutes: int


class SLAResponse(BaseModel):
    sla_id: str
    name: str
    description: str
    metric_name: str
    target_value: float
    comparison: str
    customer_facing: bool


class PolicyResponse(BaseModel):
    policy_id: str
    name: str
    description: str
    domain: str
    rule_count: int
    constraint_count: int
    sla_count: int
    playbook_count: int


# ─────────────────────────────────────────────────────────────────────────────
# In-memory storage (for demo; production would use DB)
# ─────────────────────────────────────────────────────────────────────────────


_rules: dict[str, KnowledgeRule] = {}
_constraints: dict[str, KnowledgeConstraint] = {}
_slas: dict[str, SLA] = {}
_playbooks: dict[str, Playbook] = {}
_policies: dict[str, KnowledgePolicy] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Rules Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/knowledge/rules", response_model=RuleResponse, status_code=201)
async def create_rule(
    body: CreateRuleRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Create a business rule."""
    require_workspace_access(body.workspace_id, auth)

    rule_id = str(uuid7())
    conditions = [
        RuleCondition(
            variable_id=c.variable_id,
            operator=c.operator,
            value=c.value,
        )
        for c in body.trigger.conditions
    ]
    trigger = RuleTrigger(conditions=conditions, combinator=body.trigger.combinator)

    rule = KnowledgeRule(
        rule_id=rule_id,
        workspace_id=body.workspace_id,
        name=body.name,
        description=body.description,
        trigger=trigger,
        action=body.action,
        severity=body.severity,
        action_params=body.action_params,
        tags=body.tags,
        created_by=auth.user_id if hasattr(auth, "user_id") else None,
    )
    _rules[rule_id] = rule

    return RuleResponse(
        rule_id=rule.rule_id,
        workspace_id=rule.workspace_id,
        name=rule.name,
        description=rule.description,
        action=rule.action.value,
        severity=rule.severity.value,
        enabled=rule.enabled,
        tags=list(rule.tags),
    )


@router.get("/knowledge/rules")
async def list_rules(
    workspace_id: str = Query(...),
    action: str | None = Query(None),
    tag: str | None = Query(None),
    auth: AuthContext = Depends(get_current_user),
):
    """List business rules for a workspace."""
    require_workspace_access(workspace_id, auth)

    rules = [r for r in _rules.values() if r.workspace_id == workspace_id]
    if action:
        rules = [r for r in rules if r.action.value == action]
    if tag:
        rules = [r for r in rules if tag in r.tags]

    return {
        "workspace_id": workspace_id,
        "rule_count": len(rules),
        "rules": [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "description": r.description,
                "action": r.action.value,
                "severity": r.severity.value,
                "enabled": r.enabled,
                "tags": list(r.tags),
            }
            for r in rules
        ],
    }


@router.get("/knowledge/rules/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
):
    """Get a specific rule by ID."""
    require_workspace_access(workspace_id, auth)
    rule = _rules.get(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RuleResponse(
        rule_id=rule.rule_id,
        workspace_id=rule.workspace_id,
        name=rule.name,
        description=rule.description,
        action=rule.action.value,
        severity=rule.severity.value,
        enabled=rule.enabled,
        tags=list(rule.tags),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Constraints Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/knowledge/constraints")
async def list_constraints(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
):
    """List constraints for a workspace."""
    require_workspace_access(workspace_id, auth)
    constraints = [c for c in _constraints.values() if c.workspace_id == workspace_id]
    return {
        "workspace_id": workspace_id,
        "constraint_count": len(constraints),
        "constraints": [c.to_dict() for c in constraints],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Playbooks Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/knowledge/playbooks", response_model=list[PlaybookResponse])
async def list_playbooks(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
):
    """List playbooks for a workspace."""
    require_workspace_access(workspace_id, auth)
    playbooks = [p for p in _playbooks.values() if p.workspace_id == workspace_id]
    return [
        PlaybookResponse(
            playbook_id=p.playbook_id,
            name=p.name,
            description=p.description,
            step_count=len(p.steps),
            severity=p.severity.value,
            estimated_total_duration_minutes=p.estimated_total_duration_minutes,
        )
        for p in playbooks
    ]


# ─────────────────────────────────────────────────────────────────────────────
# SLAs Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/knowledge/slas", response_model=list[SLAResponse])
async def list_slas(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
):
    """List SLAs for a workspace."""
    require_workspace_access(workspace_id, auth)
    slas = [s for s in _slas.values() if s.workspace_id == workspace_id]
    return [
        SLAResponse(
            sla_id=s.sla_id,
            name=s.name,
            description=s.description,
            metric_name=s.metric_name,
            target_value=s.target_value,
            comparison=s.comparison,
            customer_facing=s.customer_facing,
        )
        for s in slas
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Policies Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/knowledge/policies", response_model=list[PolicyResponse])
async def list_policies(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
):
    """List policies for a workspace."""
    require_workspace_access(workspace_id, auth)
    policies = [p for p in _policies.values() if p.workspace_id == workspace_id]
    return [
        PolicyResponse(
            policy_id=p.policy_id,
            name=p.name,
            description=p.description,
            domain=p.domain,
            rule_count=len(p.rule_ids),
            constraint_count=len(p.constraint_ids),
            sla_count=len(p.sla_ids),
            playbook_count=len(p.playbook_ids),
        )
        for p in policies
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Evaluate Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/knowledge/evaluate", response_model=EvaluateResponse)
async def evaluate_knowledge(
    body: EvaluateRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EvaluateResponse:
    """Evaluate rules, constraints, and SLAs against current world state."""
    require_workspace_access(body.workspace_id, auth)

    from app.modules.world.state_repository import StateRepository
    repo = StateRepository(db)
    state = await repo.get(body.world_id, body.workspace_id, version=body.version)
    if not state:
        raise HTTPException(status_code=404, detail="World state not found")

    rules = [_rules[rid] for rid in body.rule_ids if rid in _rules]
    constraints = [_constraints[cid] for cid in body.constraint_ids if cid in _constraints]
    slas = [_slas[sid] for sid in body.sla_ids if sid in _slas]

    engine = RuleEngine()
    result = engine.evaluate(state, rules=rules, constraints=constraints, slas=slas)

    return EvaluateResponse(
        state_hash=result.state_hash,
        total_rules_evaluated=result.total_rules_evaluated,
        total_constraints_evaluated=result.total_constraints_evaluated,
        total_slas_evaluated=result.total_slas_evaluated,
        fired_rules=[r.to_dict() for r in result.fired_rules],
        constraint_violations=[v.to_dict() for v in result.constraint_violations],
        sla_breaches=[b.to_dict() for b in result.sla_breaches],
        has_blocking_violations=result.has_blocking_violations(),
    )
