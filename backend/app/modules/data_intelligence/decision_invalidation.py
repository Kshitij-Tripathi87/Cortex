"""Program T5 & T6 — Decision Invalidation & Dependency Set Tracking.

Tracks the exact dependency set of every synthesized decision in Nexus.
Automatically detects when World State or Graph mutations invalidate prior decisions,
flagging them as INVALIDATED and triggering re-deliberation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class DecisionDependencySet:
    decision_id: str
    graph_version_at_creation: str
    world_state_version_at_creation: int
    dependent_entity_ids: list[str]
    dependent_signal_types: list[str]
    is_valid: bool = True
    invalidation_reason: str | None = None
    invalidated_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "graph_version_at_creation": self.graph_version_at_creation,
            "world_state_version_at_creation": self.world_state_version_at_creation,
            "dependent_entity_ids": self.dependent_entity_ids,
            "dependent_signal_types": self.dependent_signal_types,
            "is_valid": self.is_valid,
            "invalidation_reason": self.invalidation_reason,
            "invalidated_at": self.invalidated_at.isoformat() if self.invalidated_at else None,
            "created_at": self.created_at.isoformat(),
        }


class DecisionInvalidationEngine:
    """Monitors live graph & world state deltas against active decision dependency sets."""

    def __init__(self) -> None:
        self.decisions: dict[str, DecisionDependencySet] = {}

    def register_decision(
        self,
        decision_id: str,
        graph_version: str,
        world_state_version: int,
        dependent_entities: list[str],
        dependent_signals: list[str],
    ) -> DecisionDependencySet:
        dep = DecisionDependencySet(
            decision_id=decision_id,
            graph_version_at_creation=graph_version,
            world_state_version_at_creation=world_state_version,
            dependent_entity_ids=dependent_entities,
            dependent_signal_types=dependent_signals,
        )
        self.decisions[decision_id] = dep
        return dep

    def evaluate_mutation_impact(
        self,
        mutated_entity_id: str,
        mutation_type: str,
        new_world_state_version: int,
    ) -> list[str]:
        """Checks all registered decisions and invalidates any that depend on the mutated entity."""
        invalidated_decisions: list[str] = []

        for dec_id, dep in self.decisions.items():
            if dep.is_valid:  # noqa: SIM102
                # Check entity collision
                if (
                    mutated_entity_id in dep.dependent_entity_ids
                    or mutation_type == "FORCE_MAJOR_DISRUPTION"
                ):
                    dep.is_valid = False
                    dep.invalidation_reason = (
                        f"World State evolved to v{new_world_state_version}: Dependent entity {mutated_entity_id} "
                        f"mutated via {mutation_type}."
                    )
                    dep.invalidated_at = datetime.now(UTC)
                    invalidated_decisions.append(dec_id)

        return invalidated_decisions

    def is_decision_valid(self, decision_id: str) -> bool:
        if decision_id not in self.decisions:
            return False
        return self.decisions[decision_id].is_valid

    def get_invalidated_decisions(self) -> list[DecisionDependencySet]:
        return [d for d in self.decisions.values() if not d.is_valid]

    def get_valid_decisions(self) -> list[DecisionDependencySet]:
        return [d for d in self.decisions.values() if d.is_valid]
