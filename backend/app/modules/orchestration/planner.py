"""Deterministic, framework-independent task planning for Nexus orchestration.

Planning is owned by Nexus, not by any agent framework: a frozen TaskContext
is compiled into a bounded TaskPlan with no model, provider, or framework in
the path. Steps execute sequentially in declared capability order unless the
context constraints declare an explicit dependency map.
"""

from __future__ import annotations

from .contracts import TaskContext, TaskPlan, TaskPlanStep

DETERMINISTIC_AGENT_ROLE = "Nexus Supervisor"


class NexusTaskPlanner:
    """Compile a frozen TaskContext into a deterministic, acyclic TaskPlan."""

    async def plan(self, context: TaskContext) -> TaskPlan:
        if not context.objective.strip():
            raise ValueError("Task objective must not be empty.")
        if not context.capabilities:
            raise ValueError("Task context carries no capabilities to plan.")

        step_ids: list[str] = []
        for capability in context.capabilities:
            if capability.capability_id in step_ids:
                raise ValueError(
                    f"Duplicate capability in task context: {capability.capability_id!r}"
                )
            step_ids.append(capability.capability_id)

        total_budget = sum(capability.budget_units for capability in context.capabilities)
        if total_budget > context.budget + 1e-9:
            raise ValueError(
                f"Planned capabilities exceed the task budget: {total_budget} > {context.budget}"
            )

        dependencies = self._normalize_dependencies(context, step_ids)
        steps = tuple(
            TaskPlanStep(
                step_id=capability.capability_id,
                title=capability.name,
                agent_role=DETERMINISTIC_AGENT_ROLE,
                dependencies=dependencies[capability.capability_id],
                required_capabilities=(capability.capability_id,),
            )
            for capability in context.capabilities
        )
        self._assert_acyclic(steps)
        return TaskPlan(task_id=context.task_id, objective=context.objective, steps=steps)

    @staticmethod
    def _normalize_dependencies(
        context: TaskContext, step_ids: list[str]
    ) -> dict[str, tuple[str, ...]]:
        raw = context.constraints.get("dependencies")
        if raw is None:
            chain: dict[str, tuple[str, ...]] = {}
            previous: str | None = None
            for step_id in step_ids:
                chain[step_id] = (previous,) if previous is not None else ()
                previous = step_id
            return chain

        normalized: dict[str, tuple[str, ...]] = {step_id: () for step_id in step_ids}
        if not isinstance(raw, dict):
            raise ValueError(
                "constraints['dependencies'] must be a mapping of step id to prerequisites."
            )

        known = set(step_ids)
        for target, prerequisites in raw.items():
            if target not in known:
                raise ValueError(f"Unknown step reference in dependencies: {target!r}")
            if not isinstance(prerequisites, (list, tuple)):
                raise ValueError(f"Prerequisites for {target!r} must be a list of step ids.")
            unique: list[str] = []
            for prerequisite in prerequisites:
                if not isinstance(prerequisite, str) or prerequisite not in known:
                    raise ValueError(f"Unknown step reference in dependencies: {prerequisite!r}")
                if prerequisite == target:
                    raise ValueError("A step cannot depend on itself.")
                if prerequisite not in unique:
                    unique.append(prerequisite)
            normalized[target] = tuple(unique)
        return normalized

    @staticmethod
    def _assert_acyclic(steps: tuple[TaskPlanStep, ...]) -> None:
        indegree = {step.step_id: len(step.dependencies) for step in steps}
        dependents: dict[str, list[str]] = {step.step_id: [] for step in steps}
        for step in steps:
            for prerequisite in step.dependencies:
                dependents[prerequisite].append(step.step_id)

        ready = [step_id for step_id, count in indegree.items() if count == 0]
        processed = 0
        while ready:
            current = ready.pop()
            processed += 1
            for dependent in dependents[current]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)

        if processed != len(steps):
            raise ValueError("Plan dependencies contain a cycle.")
