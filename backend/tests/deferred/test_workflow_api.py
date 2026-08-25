"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Tests for workflow API — template listing and service layer smoke tests.

These tests exercise the in-memory workflow registry and service layer
without requiring a database connection.  Full end-to-end API tests
against FastAPI TestClient require PostgreSQL and are tested separately.
"""

from __future__ import annotations

from app.deferred.workflow_engine.workflow_engine import WorkflowEngine
from app.deferred.workflow_engine.workflow_registry import WorkflowRegistry


class TestWorkflowTemplates:
    """Workflow template registry — no DB required."""

    def test_list_templates_includes_scenario_analysis(self):
        registry = WorkflowRegistry()
        templates = registry.list_templates()

        assert len(templates) > 0
        names = [t["name"] for t in templates]
        assert "scenario_analysis" in names

    def test_get_definition_returns_stages(self):
        registry = WorkflowRegistry()
        definition = registry.get("scenario_analysis")

        assert definition is not None
        assert definition.name == "scenario_analysis"
        assert definition.version == "1.0"
        assert len(definition.stages) == 8

    def test_definition_has_entry_and_exit_stages(self):
        registry = WorkflowRegistry()
        definition = registry.get("scenario_analysis")

        entry = definition.entry_stages
        assert len(entry) == 1
        assert entry[0].stage_id == "init"

        gates = definition.gate_stages
        assert len(gates) == 1
        assert gates[0].stage_id == "human_review"
        assert gates[0].gate is True

    def test_unknown_workflow_returns_none(self):
        registry = WorkflowRegistry()
        assert registry.get("nonexistent") is None

    def test_latest_version_is_returned_when_version_not_specified(self):
        registry = WorkflowRegistry()
        definition = registry.get("scenario_analysis")
        assert definition is not None
        assert definition.version == "1.0"

    def test_downstream_stages_discovery(self):
        registry = WorkflowRegistry()
        definition = registry.get("scenario_analysis")
        assert definition is not None

        downstream = definition.downstream_stages("init")
        assert len(downstream) == 1
        assert downstream[0].stage_id == "validate"

    def test_stage_ids_is_frozenset(self):
        registry = WorkflowRegistry()
        definition = registry.get("scenario_analysis")
        assert definition is not None

        stage_ids = definition.stage_ids
        assert isinstance(stage_ids, frozenset)
        assert "init" in stage_ids
        assert "publish" in stage_ids

    def test_replay_from_instance_preserves_payload(self):
        from app.deferred.workflow_engine.workflow_models import (
            StageDefinition,
            StageInstance,
            StageStatus,
            WorkflowDefinition,
            WorkflowInstance,
        )

        definition = WorkflowDefinition(
            workflow_id="wf_payload",
            name="payload_test",
            version="1.0",
            stages=(
                StageDefinition(
                    stage_id="parse",
                    name="Parse Input",
                    agent="evidence",
                    verb="parse",
                ),
            ),
        )
        old = WorkflowInstance(
            instance_id="old-pay",
            workflow_name="payload_test",
            workspace_id="ws1",
            version="1.0",
            stages=(
                StageInstance(
                    stage_instance_id="ps1",
                    workflow_instance_id="old-pay",
                    stage_id="parse",
                    name="Parse Input",
                    agent="evidence",
                    verb="parse",
                    input_payload={"filename": "data.csv", "encoding": "utf-8"},
                    status=StageStatus.COMPLETED,
                ),
            ),
        )

        engine = WorkflowEngine()
        new_instance = engine.replay_from_instance(definition, old)

        assert len(new_instance.stages) == 1
        assert new_instance.stages[0].input_payload == {"filename": "data.csv", "encoding": "utf-8"}
        assert new_instance.stages[0].status == StageStatus.PENDING
