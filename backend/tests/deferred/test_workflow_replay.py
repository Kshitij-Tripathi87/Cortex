"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Tests for deterministic workflow replay."""

from __future__ import annotations

from app.deferred.workflow_engine.workflow_engine import WorkflowEngine
from app.deferred.workflow_engine.workflow_models import (
    StageDefinition,
    StageInstance,
    StageStatus,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStatus,
)


class TestWorkflowReplay:
    """Deterministic replay tests."""

    def test_replay_preserves_workflow_definition(self):
        definition = WorkflowDefinition(
            workflow_id="wf_replay",
            name="replay_test",
            version="1.0",
            stages=(
                StageDefinition(
                    stage_id="init",
                    name="Initialize",
                    agent="simulation",
                    verb="init",
                ),
                StageDefinition(
                    stage_id="run",
                    name="Execute",
                    agent="simulation",
                    verb="execute",
                    depends_on=("init",),
                ),
                StageDefinition(
                    stage_id="publish",
                    name="Publish",
                    agent="operations",
                    verb="notify",
                    depends_on=("run",),
                    gate=True,
                ),
            ),
        )
        old_instance = WorkflowInstance(
            instance_id="old-id",
            workflow_name="replay_test",
            workspace_id="ws1",
            version="1.0",
            status=WorkflowStatus.COMPLETED,
            stages=(
                StageInstance(
                    stage_instance_id="sa",
                    workflow_instance_id="old-id",
                    stage_id="init",
                    name="Initialize",
                    agent="simulation",
                    verb="init",
                    status=StageStatus.COMPLETED,
                    input_payload={"param": "value"},
                ),
                StageInstance(
                    stage_instance_id="sb",
                    workflow_instance_id="old-id",
                    stage_id="run",
                    name="Execute",
                    agent="simulation",
                    verb="execute",
                    depends_on=("init",),
                    status=StageStatus.COMPLETED,
                ),
            ),
        )

        engine = WorkflowEngine()
        new_instance = engine.replay_from_instance(definition, old_instance)

        assert new_instance.instance_id != old_instance.instance_id
        assert new_instance.workflow_name == old_instance.workflow_name
        assert new_instance.workspace_id == old_instance.workspace_id
        assert new_instance.version == old_instance.version
        assert len(new_instance.stages) == len(old_instance.stages)
        assert new_instance.status == WorkflowStatus.CREATED

    def test_replay_twice_produces_deterministic_state_structures(self):
        definition = WorkflowDefinition(
            workflow_id="wf_replay2",
            name="replay_det",
            version="1.0",
            stages=(
                StageDefinition(
                    stage_id="one",
                    name="step_one",
                    agent="knowledge",
                    verb="validate",
                ),
                StageDefinition(
                    stage_id="two",
                    name="step_two",
                    agent="operations",
                    verb="rank",
                    depends_on=("one",),
                ),
            ),
        )
        old = WorkflowInstance(
            instance_id="det-old",
            workflow_name="replay_det",
            workspace_id="ws1",
            version="1.0",
            status=WorkflowStatus.COMPLETED,
            stages=(
                StageInstance(
                    stage_instance_id="d1",
                    workflow_instance_id="det-old",
                    stage_id="one",
                    name="step_one",
                    agent="stage",
                    verb="validate",
                    status=StageStatus.COMPLETED,
                    input_payload={"x": 1},
                ),
            ),
        )

        engine = WorkflowEngine()
        r1 = engine.replay_from_instance(definition, old)
        r2 = engine.replay_from_instance(definition, old)

        assert len(r1.stages) == len(r2.stages)
        for s1, s2 in zip(r1.stages, r2.stages, strict=True):
            assert s1.stage_id == s2.stage_id
            assert s1.status == StageStatus.PENDING
            assert s1.agent == s2.agent

    def test_replay_preserves_input_payload(self):
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
                    input_payload={"filename": "data.csv"},
                    status=StageStatus.COMPLETED,
                ),
            ),
        )

        engine = WorkflowEngine()
        new_instance = engine.replay_from_instance(definition, old)

        assert len(new_instance.stages) == 1
        assert new_instance.stages[0].input_payload == {"filename": "data.csv"}
        assert new_instance.stages[0].status == StageStatus.PENDING
