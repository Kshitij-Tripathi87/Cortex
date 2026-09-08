"""Nexus v0.7 — Bounded RL (candidate generation only).

RL policy generates candidate actions, which then go through:
  RL → Candidate actions → Digital Twin → Simulation
     → Deterministic KPI comparison → Policy → Human approval

The RL model NEVER directly executes an action. It is strictly a
candidate proposal layer that feeds into the governance architecture.
"""

from app.modules.nexus_spine.rl.candidate_generator import (
    CANDIDATE_ACTION_TYPES,
    CandidateAction,
    CandidateGenerator,
    RLCandidateGenerator,
    get_candidate_generator,
    reset_candidate_generator,
)

__all__ = [
    "CANDIDATE_ACTION_TYPES",
    "CandidateAction",
    "CandidateGenerator",
    "RLCandidateGenerator",
    "get_candidate_generator",
    "reset_candidate_generator",
]
