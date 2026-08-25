"""Playbooks — Pre-defined Standard Operating Procedures.

Program J (World State & Digital Twin) playbooks module:

Provides factory functions for common playbooks:
- Supplier disruption response
- Demand surge response
- Factory shutdown response
- Critical inventory shortage
- Cyber incident response
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.knowledge.knowledge_models import (
    Playbook,
    PlaybookStep,
    RuleCondition,
    RuleSeverity,
    RuleTrigger,
)


def supplier_disruption_playbook(
    workspace_id: str,
    playbook_id: str | None = None,
) -> Playbook:
    """Playbook: Respond to Supplier Disruption."""
    return Playbook(
        playbook_id=playbook_id or str(uuid7()),
        workspace_id=workspace_id,
        name="Supplier Disruption Response",
        description="Standard procedure for responding to supplier disruptions",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="lead_time.supplier.*",
                    operator="gt",
                    value=14,
                ),
            ],
        ),
        steps=[
            PlaybookStep(
                step_number=1,
                action="Notify procurement team of supplier disruption",
                required_role="procurement_manager",
                estimated_duration_minutes=15,
            ),
            PlaybookStep(
                step_number=2,
                action="Identify alternative suppliers with available capacity",
                required_role="procurement_analyst",
                estimated_duration_minutes=60,
            ),
            PlaybookStep(
                step_number=3,
                action="Evaluate cost impact of switching suppliers",
                required_role="procurement_manager",
                estimated_duration_minutes=30,
            ),
            PlaybookStep(
                step_number=4,
                action="Issue emergency orders to alternative suppliers",
                required_role="procurement_manager",
                estimated_duration_minutes=20,
                on_success=5,
                on_failure=3,  # Go back to alternatives
            ),
            PlaybookStep(
                step_number=5,
                action="Notify affected customers of potential delays",
                required_role="customer_success",
                estimated_duration_minutes=45,
            ),
        ],
        estimated_total_duration_minutes=170,
        severity=RuleSeverity.HIGH,
        tags=["supply_chain", "disruption", "critical"],
    )


def demand_surge_playbook(
    workspace_id: str,
    playbook_id: str | None = None,
) -> Playbook:
    """Playbook: Respond to Demand Surge."""
    return Playbook(
        playbook_id=playbook_id or str(uuid7()),
        workspace_id=workspace_id,
        name="Demand Surge Response",
        description="Standard procedure for responding to sudden demand increases",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="demand.*",
                    operator="gt",
                    value=1000,
                ),
            ],
        ),
        steps=[
            PlaybookStep(
                step_number=1,
                action="Verify demand signal (real vs forecast noise)",
                required_role="demand_planner",
                estimated_duration_minutes=30,
            ),
            PlaybookStep(
                step_number=2,
                action="Check inventory levels across all warehouses",
                required_role="inventory_manager",
                estimated_duration_minutes=15,
            ),
            PlaybookStep(
                step_number=3,
                action="Assess production capacity headroom",
                required_role="production_planner",
                estimated_duration_minutes=30,
            ),
            PlaybookStep(
                step_number=4,
                action="Expedite orders from suppliers if needed",
                required_role="procurement_manager",
                estimated_duration_minutes=20,
            ),
            PlaybookStep(
                step_number=5,
                action="Communicate with key customers about availability",
                required_role="sales_manager",
                estimated_duration_minutes=45,
            ),
        ],
        estimated_total_duration_minutes=140,
        severity=RuleSeverity.HIGH,
        tags=["demand", "market", "response"],
    )


def factory_shutdown_playbook(
    workspace_id: str,
    playbook_id: str | None = None,
) -> Playbook:
    """Playbook: Respond to Factory Shutdown."""
    return Playbook(
        playbook_id=playbook_id or str(uuid7()),
        workspace_id=workspace_id,
        name="Factory Shutdown Response",
        description="Standard procedure for responding to factory shutdowns",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="capacity.factory.*",
                    operator="lt",
                    value=20,
                ),
            ],
        ),
        steps=[
            PlaybookStep(
                step_number=1,
                action="Assess shutdown cause and expected duration",
                required_role="plant_manager",
                estimated_duration_minutes=60,
            ),
            PlaybookStep(
                step_number=2,
                action="Activate backup production capacity",
                required_role="production_director",
                estimated_duration_minutes=120,
            ),
            PlaybookStep(
                step_number=3,
                action="Reroute orders to other facilities",
                required_role="supply_chain_manager",
                estimated_duration_minutes=90,
            ),
            PlaybookStep(
                step_number=4,
                action="Communicate with customers about delays",
                required_role="customer_success",
                estimated_duration_minutes=60,
            ),
            PlaybookStep(
                step_number=5,
                action="File insurance claim if applicable",
                required_role="finance_manager",
                estimated_duration_minutes=120,
            ),
        ],
        estimated_total_duration_minutes=450,
        severity=RuleSeverity.CRITICAL,
        tags=["production", "disruption", "critical"],
    )


def inventory_shortage_playbook(
    workspace_id: str,
    playbook_id: str | None = None,
) -> Playbook:
    """Playbook: Respond to Critical Inventory Shortage."""
    return Playbook(
        playbook_id=playbook_id or str(uuid7()),
        workspace_id=workspace_id,
        name="Critical Inventory Shortage",
        description="Standard procedure for critical inventory shortages",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="inventory.*",
                    operator="lt",
                    value=5,
                ),
            ],
        ),
        steps=[
            PlaybookStep(
                step_number=1,
                action="Identify shortage scope and affected orders",
                required_role="inventory_manager",
                estimated_duration_minutes=15,
            ),
            PlaybookStep(
                step_number=2,
                action="Check sister warehouse availability for transfer",
                required_role="logistics_manager",
                estimated_duration_minutes=30,
            ),
            PlaybookStep(
                step_number=3,
                action="Expedite emergency replenishment order",
                required_role="procurement_manager",
                estimated_duration_minutes=20,
            ),
            PlaybookStep(
                step_number=4,
                action="Communicate delays to affected customers",
                required_role="customer_success",
                estimated_duration_minutes=45,
            ),
        ],
        estimated_total_duration_minutes=110,
        severity=RuleSeverity.HIGH,
        tags=["inventory", "shortage", "critical"],
    )


def cyber_incident_playbook(
    workspace_id: str,
    playbook_id: str | None = None,
) -> Playbook:
    """Playbook: Respond to Cyber Incident."""
    return Playbook(
        playbook_id=playbook_id or str(uuid7()),
        workspace_id=workspace_id,
        name="Cyber Incident Response",
        description="Standard procedure for cybersecurity incidents",
        steps=[
            PlaybookStep(
                step_number=1,
                action="Isolate affected systems",
                required_role="security_team",
                estimated_duration_minutes=15,
            ),
            PlaybookStep(
                step_number=2,
                action="Assess scope of breach",
                required_role="security_team",
                estimated_duration_minutes=60,
            ),
            PlaybookStep(
                step_number=3,
                action="Notify executive team",
                required_role="ciso",
                estimated_duration_minutes=15,
            ),
            PlaybookStep(
                step_number=4,
                action="Engage incident response firm",
                required_role="ciso",
                estimated_duration_minutes=30,
            ),
            PlaybookStep(
                step_number=5,
                action="File regulatory notifications",
                required_role="legal",
                estimated_duration_minutes=120,
            ),
        ],
        estimated_total_duration_minutes=240,
        severity=RuleSeverity.CRITICAL,
        tags=["security", "incident", "critical"],
    )
