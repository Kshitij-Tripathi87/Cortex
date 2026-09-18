"""017 — Nexus MAF-4 durable task runtime tables

Revision ID: 017_nexus_task_runtime
Revises: 016_outbox_claim_lease
Create Date: 2026-09-18

Creates the orchestration runtime tables in dependency order:

    nexus_tasks, nexus_task_transitions, nexus_task_intents,
    nexus_task_plans, nexus_task_runs, nexus_task_steps,
    nexus_task_invocations, nexus_task_evidence, nexus_task_proposals,
    nexus_task_approvals, nexus_task_executions, nexus_task_outcomes

PostgreSQL is authoritative for the task lifecycle. Each table is created
only when missing (same idempotent guard style as migrations 013/016); fresh
databases are owned by init_db/create_all.
"""

import sqlalchemy as sa

from alembic import op

revision = "017_nexus_task_runtime"
down_revision = "016_outbox_claim_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "nexus_tasks" not in existing:
        op.create_table(
            "nexus_tasks",
            sa.Column("task_id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("workspace_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("actor_id", sa.String(length=64), nullable=False),
            sa.Column("trace_id", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, index=True),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("world_state_version", sa.Integer(), nullable=False),
            sa.Column("budget", sa.Float(), nullable=False),
            sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
            sa.Column("requires_approval", sa.Boolean(), nullable=False),
            sa.Column("blocked_reason", sa.Text(), nullable=True),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("policy_context", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_nexus_tasks_tenant_workspace_status",
            "nexus_tasks",
            ["tenant_id", "workspace_id", "status"],
        )

    if "nexus_task_transitions" not in existing:
        op.create_table(
            "nexus_task_transitions",
            sa.Column("transition_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("from_status", sa.String(length=40), nullable=True),
            sa.Column("to_status", sa.String(length=40), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("actor_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "nexus_task_intents" not in existing:
        op.create_table(
            "nexus_task_intents",
            sa.Column("intent_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("intent_payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "nexus_task_plans" not in existing:
        op.create_table(
            "nexus_task_plans",
            sa.Column("plan_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("plan_payload", sa.JSON(), nullable=False),
            sa.Column("assumptions", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "nexus_task_runs" not in existing:
        op.create_table(
            "nexus_task_runs",
            sa.Column("run_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("run_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("world_state_version", sa.Integer(), nullable=False),
            sa.Column("checkpoint_step", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("task_id", "run_number"),
        )

    if "nexus_task_steps" not in existing:
        op.create_table(
            "nexus_task_steps",
            sa.Column("step_run_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "run_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_task_runs.run_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("task_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("step_id", sa.String(length=64), nullable=False),
            sa.Column("agent_role", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("error", sa.String(length=128), nullable=True),
            sa.Column("invocation_ids", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("outputs", sa.JSON(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("run_id", "step_id"),
        )

    if "nexus_task_invocations" not in existing:
        op.create_table(
            "nexus_task_invocations",
            sa.Column("invocation_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("run_id", sa.String(length=64), nullable=False, index=True),
            sa.Column("step_id", sa.String(length=64), nullable=False),
            sa.Column("capability_id", sa.String(length=128), nullable=False),
            sa.Column("capability_version", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("side_effect", sa.String(length=40), nullable=False),
            sa.Column("world_state_version", sa.Integer(), nullable=False),
            sa.Column("arguments_sha256", sa.String(length=128), nullable=False),
            sa.Column("authorization", sa.JSON(), nullable=False),
            sa.Column("provenance", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("result_data", sa.JSON(), nullable=True),
            sa.Column("error", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_nexus_task_invocations_resume",
            "nexus_task_invocations",
            ["task_id", "step_id", "capability_id", "arguments_sha256"],
        )

    if "nexus_task_evidence" not in existing:
        op.create_table(
            "nexus_task_evidence",
            sa.Column("evidence_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("ref", sa.String(length=160), nullable=False),
            sa.Column("source_invocation_id", sa.String(length=64), nullable=True),
            sa.Column("payload_digest", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("task_id", "ref"),
        )

    if "nexus_task_proposals" not in existing:
        op.create_table(
            "nexus_task_proposals",
            sa.Column("proposal_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("agent_id", sa.String(length=64), nullable=False),
            sa.Column("agent_role", sa.String(length=64), nullable=False),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("actions", sa.JSON(), nullable=False),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("assumptions", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "nexus_task_approvals" not in existing:
        op.create_table(
            "nexus_task_approvals",
            sa.Column("approval_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("decision", sa.String(length=20), nullable=False),
            sa.Column("approver_id", sa.String(length=64), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if "nexus_task_executions" not in existing:
        op.create_table(
            "nexus_task_executions",
            sa.Column("execution_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=False),
            sa.Column("failure_reason", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "nexus_task_outcomes" not in existing:
        op.create_table(
            "nexus_task_outcomes",
            sa.Column("outcome_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "task_id",
                sa.String(length=64),
                sa.ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("recommendation", sa.Text(), nullable=True),
            sa.Column("result_payload", sa.JSON(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for name in (
        "nexus_task_outcomes",
        "nexus_task_executions",
        "nexus_task_approvals",
        "nexus_task_proposals",
        "nexus_task_evidence",
        "nexus_task_invocations",
        "nexus_task_steps",
        "nexus_task_runs",
        "nexus_task_plans",
        "nexus_task_intents",
        "nexus_task_transitions",
        "nexus_tasks",
    ):
        if name in existing:
            op.drop_table(name)
