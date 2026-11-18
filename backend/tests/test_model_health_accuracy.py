"""Model health reports a measured accuracy, or none.

The health summary used to fall back to a fixed figure when a deployed model
had no recorded metric (0.9 for a forecast, 0.92 for a risk model, 0.88
elsewhere), and to 0.0 for a kind of prediction with no model at all. The
Operations page printed those as if they had been measured.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.p0_migration.authoritative_models import (
    AuthoritativeModelRegistry,
    measured_accuracy,
)

# Register the table before the db_engine fixture copies Base.metadata.
from app.modules.nexus_spine.persistence.models import ModelRegistryEntryDB  # noqa: F401


@pytest.mark.parametrize(
    ("model_type", "metrics", "expected"),
    [
        # Measured: the figure comes from the recorded metric.
        ("forecast", {"wape": 0.09}, 0.91),
        ("eta", {"mape": 0.2}, 0.8),
        ("risk", {"f1": 0.91, "accuracy": 0.97}, 0.91),
        ("sla", {"accuracy": 0.87}, 0.87),
        ("gnn", {"accuracy": 0.75}, 0.75),
        # Not measured: no figure. These used to be 0.9, 0.88, 0.92 and 0.88.
        ("forecast", {}, None),
        ("eta", {}, None),
        ("risk", {}, None),
        ("rl", {}, None),
        # A metric of another kind does not stand in for the missing one.
        ("forecast", {"accuracy": 0.99}, None),
        ("eta", {"f1": 0.99}, None),
        # Values that are not numbers are not figures.
        ("risk", {"f1": "0.91"}, None),
        ("risk", {"f1": True}, None),
        ("risk", {"f1": float("nan")}, None),
        # A score outside 0..1 is kept within it, as before.
        ("forecast", {"wape": 1.4}, 0.0),
        ("risk", {"f1": 1.2}, 1.0),
    ],
)
def test_accuracy_comes_from_recorded_metrics_only(
    model_type: str, metrics: dict, expected: float | None
) -> None:
    assert measured_accuracy(model_type, metrics) == expected


async def test_a_workspace_without_models_reports_no_accuracy(db_session: AsyncSession) -> None:
    summary = await AuthoritativeModelRegistry().health_summary(
        db_session, tenant_id="tenant-none", workspace_id="workspace-none"
    )
    assert set(summary) == {
        "Demand forecast",
        "ETA prediction",
        "Supplier risk",
        "SLA prediction",
        "Scenario accuracy",
        "Recommendation success",
    }
    for label, slot in summary.items():
        assert slot["status"] == "unassigned", label
        assert slot["model_id"] is None, label
        # Not 0.0: a missing model is not a model that is always wrong.
        assert slot["accuracy"] is None, label
