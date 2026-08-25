"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow registry — centralized registry of workflow templates.

Workflow templates are declarative DAG definitions stored in YAML or
registered programmatically.  The registry provides lookup by name and
lists all available templates.

See workflow_models.py for the WorkflowDefinition and StageDefinition types.
"""

from __future__ import annotations

from app.deferred.workflow_engine.workflow_models import (
    StageDefinition,
    WorkflowDefinition,
)

_DEFAULT_WORKFLOWS: dict[str, WorkflowDefinition] = {}


def _register_builtins() -> None:
    _DEFAULT_WORKFLOWS["scenario_analysis"] = WorkflowDefinition(
        workflow_id="wf_scenario_analysis_v1",
        name="scenario_analysis",
        version="1.0",
        stages=(
            StageDefinition(
                stage_id="init",
                name="Initialize Scenario",
                agent="simulation",
                verb="init_scenario",
            ),
            StageDefinition(
                stage_id="validate",
                name="Validate Graph State",
                agent="knowledge",
                verb="validate_graph_state",
                depends_on=("init",),
                timeout_ms=60000,
            ),
            StageDefinition(
                stage_id="run_simulation",
                name="Execute Simulation",
                agent="simulation",
                verb="execute_plugin",
                depends_on=("validate",),
                timeout_ms=300000,
            ),
            StageDefinition(
                stage_id="evaluate",
                name="Evaluate Results",
                agent="learning",
                verb="evaluate_simulation_result",
                depends_on=("run_simulation",),
            ),
            StageDefinition(
                stage_id="generate_recommendations",
                name="Generate Recommendations",
                agent="operations",
                verb="rank_recommendations",
                depends_on=("evaluate",),
            ),
            StageDefinition(
                stage_id="human_review",
                name="Human Review",
                agent="operations",
                verb="request_approval",
                depends_on=("generate_recommendations",),
                gate=True,
            ),
            StageDefinition(
                stage_id="record_decision",
                name="Record Decision",
                agent="operations",
                verb="commit_decision",
                depends_on=("human_review",),
            ),
            StageDefinition(
                stage_id="publish",
                name="Publish Results",
                agent="operations",
                verb="notify_stakeholders",
                depends_on=("record_decision",),
            ),
        ),
    )


class WorkflowRegistry:
    """Central registry of available workflow templates."""

    def __init__(self) -> None:
        self._templates: dict[str, dict[str, WorkflowDefinition]] = {}
        _register_builtins()
        for _name, definition in _DEFAULT_WORKFLOWS.items():
            self.register(definition)

    def register(self, definition: WorkflowDefinition) -> None:
        self._templates.setdefault(definition.name, {})[definition.version] = definition

    def get(self, name: str, version: str | None = None) -> WorkflowDefinition | None:
        versions = self._templates.get(name)
        if not versions:
            return None
        if version:
            return versions.get(version)
        sorted_versions = sorted(versions.keys(), reverse=True)
        return versions[sorted_versions[0]]

    def list_templates(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for name, versions in self._templates.items():
            for version in versions:
                result.append({"name": name, "version": version})
        return result


registry = WorkflowRegistry()
