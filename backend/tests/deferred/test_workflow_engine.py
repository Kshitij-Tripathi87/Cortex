"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Tests for the workflow engine — DAG parsing, stage scheduling, state machine."""

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


class TestWorkflowEngine:
    """Core engine tests: step dispatch, state machine, replay."""

    def test_build_stages_creates_pending_stages(self):
        engine = WorkflowEngine()
        definition = WorkflowDefinition(
            workflow_id="wf_test",
            name="test",
            version="1.0",
            stages=(
                StageDefinition(stage_id="s1", name="step1", agent="evidence", verb="validate"),
                StageDefinition(
                    stage_id="s2",
                    name="step2",
                    agent="knowledge",
                    verb="compile",
                    depends_on=("s1",),
                ),
            ),
        )
        stages = engine.build_stages(definition, "inst-1")

        assert len(stages) == 2
        assert stages[0].stage_id == "s1"
        assert stages[0].status == StageStatus.PENDING
        assert stages[0].workflow_instance_id == "inst-1"
        assert stages[1].depends_on == ("s1",)

    def test_ready_stages_returns_only_stages_with_deps_satisfied(self):
        engine = WorkflowEngine()
        stages = (
            StageInstance(
                stage_instance_id="i1",
                workflow_instance_id="wf1",
                stage_id="s1",
                name="init",
                agent="engine",
                verb="init",
                status=StageStatus.COMPLETED,
            ),
            StageInstance(
                stage_instance_id="i2",
                workflow_instance_id="wf1",
                stage_id="s2",
                name="compile",
                agent="engine",
                verb="compile",
                depends_on=("s1",),
                status=StageStatus.PENDING,
            ),
            StageInstance(
                stage_instance_id="i3",
                workflow_instance_id="wf1",
                stage_id="s3",
                name="publish",
                agent="engine",
                verb="publish",
                depends_on=("s2",),
                status=StageStatus.PENDING,
            ),
        )
        instance = WorkflowInstance(
            instance_id="wf1",
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=stages,
        )

        ready = engine.ready_stages(instance)

        assert len(ready) == 1
        assert ready[0].stage_id == "s2"

    def test_determine_status_running_when_stages_pending(self):
        engine = WorkflowEngine()
        instance = WorkflowInstance(
            instance_id="wf-running",
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=(
                StageInstance(
                    stage_instance_id="a",
                    workflow_instance_id="wf-running",
                    stage_id="a",
                    name="a",
                    agent="x",
                    verb="y",
                    status=StageStatus.PENDING,
                ),
            ),
        )
        assert engine.determine_status(instance) == WorkflowStatus.RUNNING

    def test_determine_status_completed_when_all_stages_completed(self):
        engine = WorkflowEngine()
        instance = WorkflowInstance(
            instance_id="wf-done",
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=(
                StageInstance(
                    stage_instance_id="s1",
                    workflow_instance_id="wf-done",
                    stage_id="s1",
                    name="init",
                    agent="x",
                    verb="y",
                    status=StageStatus.COMPLETED,
                ),
                StageInstance(
                    stage_instance_id="s2",
                    workflow_instance_id="wf-done",
                    stage_id="s2",
                    name="compile",
                    agent="x",
                    verb="y",
                    status=StageStatus.COMPLETED,
                ),
            ),
        )
        assert engine.determine_status(instance) == WorkflowStatus.COMPLETED

    def test_determine_status_failed_when_any_stage_failed(self):
        engine = WorkflowEngine()
        instance = WorkflowInstance(
            instance_id="wf-fail",
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=(
                StageInstance(
                    stage_instance_id="s1",
                    workflow_instance_id="wf-fail",
                    stage_id="s1",
                    name="init",
                    agent="x",
                    verb="y",
                    status=StageStatus.COMPLETED,
                ),
                StageInstance(
                    stage_instance_id="s2",
                    workflow_instance_id="wf-fail",
                    stage_id="s2",
                    name="fail",
                    agent="x",
                    verb="y",
                    status=StageStatus.FAILED,
                ),
            ),
        )
        assert engine.determine_status(instance) == WorkflowStatus.FAILED

    def test_finished_returns_true_when_all_finished(self):
        engine = WorkflowEngine()
        instance = WorkflowInstance(
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=(
                StageInstance(
                    stage_instance_id="a",
                    workflow_instance_id="x",
                    stage_id="a",
                    name="a",
                    agent="x",
                    verb="y",
                    status=StageStatus.COMPLETED,
                ),
                StageInstance(
                    stage_instance_id="b",
                    workflow_instance_id="x",
                    stage_id="b",
                    name="b",
                    agent="x",
                    verb="y",
                    status=StageStatus.SKIPPED,
                ),
            ),
        )
        assert engine.finished(instance)

    def test_rollback_marks_completed_stages_as_rolled_back(self):
        engine = WorkflowEngine()
        instance = WorkflowInstance(
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=(
                StageInstance(
                    stage_instance_id="sa",
                    workflow_instance_id="rb",
                    stage_id="a",
                    name="a",
                    agent="x",
                    verb="y",
                    status=StageStatus.COMPLETED,
                ),
                StageInstance(
                    stage_instance_id="sb",
                    workflow_instance_id="rb",
                    stage_id="b",
                    name="b",
                    agent="x",
                    verb="y",
                    status=StageStatus.COMPLETED,
                ),
                StageInstance(
                    stage_instance_id="sc",
                    workflow_instance_id="rb",
                    stage_id="c",
                    name="c",
                    agent="x",
                    verb="y",
                    status=StageStatus.FAILED,
                ),
            ),
        )
        rolled = engine.rollback_stages(instance, "c")
        assert len(rolled) == 2
        for s in rolled:
            assert s.status == StageStatus.ROLLED_BACK

    def test_replay_produces_fresh_instance(self):
        definition = WorkflowDefinition(
            workflow_id="wf_replay",
            name="replay_test",
            version="1.0",
            stages=(
                StageDefinition(stage_id="init", name="init", agent="simulation", verb="init"),
                StageDefinition(
                    stage_id="run",
                    name="run",
                    agent="simulation",
                    verb="execute",
                    depends_on=("init",),
                ),
            ),
        )
        old_instance = WorkflowInstance(
            instance_id="old-1",
            workflow_name="replay_test",
            workspace_id="ws1",
            version="1.0",
            status=WorkflowStatus.COMPLETED,
            stages=(
                StageInstance(
                    stage_instance_id="s1",
                    workflow_instance_id="old-1",
                    stage_id="init",
                    name="init",
                    agent="simulation",
                    verb="init",
                    status=StageStatus.COMPLETED,
                ),
            ),
        )

        engine = WorkflowEngine()
        new_instance = engine.replay_from_instance(definition, old_instance)

        assert new_instance.instance_id != old_instance.instance_id
        assert new_instance.workflow_name == "replay_test"
        assert all(s.status == StageStatus.PENDING for s in new_instance.stages)

    def test_gate_stage_not_counted_as_ready_until_approved(self):
        engine = WorkflowEngine()
        stages = (
            StageInstance(
                stage_instance_id="before",
                workflow_instance_id="gate-test",
                stage_id="before",
                name="before",
                agent="x",
                verb="y",
                status=StageStatus.COMPLETED,
            ),
            StageInstance(
                stage_instance_id="gate",
                workflow_instance_id="gate-test",
                stage_id="gate",
                name="approval",
                agent="x",
                verb="y",
                depends_on=("before",),
                gate=True,
                status=StageStatus.AWAITING_APPROVAL,
            ),
        )
        instance = WorkflowInstance(
            workflow_name="test",
            workspace_id="ws1",
            version="1.0",
            stages=stages,
        )
        ready = engine.ready_stages(instance)
        awaiting = [s for s in instance.stages if s.status == StageStatus.AWAITING_APPROVAL]
        assert len(awaiting) == 1
        assert len(ready) == 0
