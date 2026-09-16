from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.modules.orchestration import EvidenceRequirement, RiskClass, TaskIntent, TimeHorizon


def requirement(key: str = "inventory.on_hand") -> EvidenceRequirement:
    return EvidenceRequirement(key=key, description="Authoritative on-hand inventory")


def test_task_intent_normalizes_objective_and_preserves_explicit_scope():
    intent = TaskIntent(
        objective="  Fix   the inventory shortage  ",
        constraints={"max_expedite_cost": 5000},
        entity_ids=("sku-1", "warehouse-7"),
        time_horizon=TimeHorizon(label="next 14 days"),
        risk_class=RiskClass.HIGH,
        required_evidence=(requirement(),),
    )

    assert intent.objective == "Fix the inventory shortage"
    assert intent.entity_ids == ("sku-1", "warehouse-7")
    assert intent.risk_class is RiskClass.HIGH
    assert intent.requires_consequential_governance is True


def test_missing_required_evidence_is_detectable():
    intent = TaskIntent(
        objective="Investigate stockout risk",
        required_evidence=(
            requirement("inventory.on_hand"),
            requirement("purchase_orders.open"),
            EvidenceRequirement(
                key="warehouse.capacity", description="Current available warehouse capacity", required=False
            ),
        ),
    )

    assert intent.missing_evidence({"inventory.on_hand"}) == ("purchase_orders.open",)


def test_duplicate_entities_are_rejected():
    with pytest.raises(ValidationError, match="entity_ids must be unique"):
        TaskIntent(objective="Inspect inventory", entity_ids=("sku-1", "sku-1"))


def test_duplicate_evidence_keys_are_rejected():
    with pytest.raises(ValidationError, match="required_evidence keys must be unique"):
        TaskIntent(
            objective="Inspect inventory",
            required_evidence=(requirement("inventory.on_hand"), requirement("inventory.on_hand")),
        )


def test_reversed_time_horizon_is_rejected():
    start = datetime(2026, 9, 16, tzinfo=timezone.utc)
    end = datetime(2026, 9, 15, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="time horizon end"):
        TimeHorizon(start=start, end=end)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        TaskIntent(objective="Inspect inventory", unexpected="hallucinated field")
