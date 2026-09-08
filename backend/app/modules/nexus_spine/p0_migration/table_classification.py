"""Nexus v1.0 P0 — Table classification.

Every persisted Nexus record has exactly one classification, and that
classification is encoded in tests + architecture.

  AUTHORITATIVE  source of truth — never derived; the place where a fact
                 is first written; must be in a transaction with the outbox.
  PROJECTION     materialized view derived from AUTHORITATIVE data; may be
                 rebuilt at any time by replaying events.
  CACHE          ephemeral read cache; can be dropped without losing truth.
  TEMPORARY      per-request, per-session, or per-connection; never shared.

This is the invariant that prevents "three versions of reality."
"""

from __future__ import annotations

from enum import StrEnum


class DataClassification(StrEnum):
    AUTHORITATIVE = "authoritative"
    PROJECTION = "projection"
    CACHE = "cache"
    TEMPORARY = "temporary"


# Map table names to their classification.
TABLE_CLASSIFICATION: dict[str, DataClassification] = {
    # ── World state (authoritative) ────────────────────────────────────────
    "world_states": DataClassification.AUTHORITATIVE,  # canonical world snapshots
    "world_state_events": DataClassification.AUTHORITATIVE,  # append-only event log
    "nexus_entities": DataClassification.AUTHORITATIVE,  # ontology nodes
    "nexus_relationships": DataClassification.AUTHORITATIVE,  # ontology edges
    # ── Decision lifecycle (authoritative) ─────────────────────────────────
    "nexus_decisions": DataClassification.AUTHORITATIVE,
    "nexus_decision_transitions": DataClassification.AUTHORITATIVE,  # append-only audit
    "nexus_approvals": DataClassification.AUTHORITATIVE,
    "nexus_executions": DataClassification.AUTHORITATIVE,
    "nexus_outcomes": DataClassification.AUTHORITATIVE,
    # ── Evidence (authoritative DAG) ───────────────────────────────────────
    "nexus_evidence_nodes": DataClassification.AUTHORITATIVE,
    "nexus_evidence_edges": DataClassification.AUTHORITATIVE,
    # ── Forecasts + observations (authoritative) ───────────────────────────
    "nexus_forecasts": DataClassification.AUTHORITATIVE,
    "nexus_observations": DataClassification.AUTHORITATIVE,
    # ── Recommendations (authoritative) ───────────────────────────────────
    "nexus_recommendations": DataClassification.AUTHORITATIVE,
    # ── Model registry (authoritative) ────────────────────────────────────
    "nexus_model_registry": DataClassification.AUTHORITATIVE,
    # ── Vanessa sessions/messages (authoritative conversation records) ────
    "nexus_vanessa_sessions": DataClassification.AUTHORITATIVE,
    "nexus_vanessa_messages": DataClassification.AUTHORITATIVE,
    # ── Risks (projection over entities + signals; recomputable) ───────────
    "nexus_risks": DataClassification.PROJECTION,
    # ── Scenarios (projection over decision + mutations; replayable) ──────
    "nexus_scenarios": DataClassification.PROJECTION,
    # ── Event outbox (authoritative until published; then archived) ────────
    "nexus_events": DataClassification.AUTHORITATIVE,
}


def classify(table_name: str) -> DataClassification:
    return TABLE_CLASSIFICATION.get(table_name, DataClassification.PROJECTION)


__all__ = ["DataClassification", "TABLE_CLASSIFICATION", "classify"]
