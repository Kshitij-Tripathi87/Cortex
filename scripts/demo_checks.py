"""Checks of the demo dataset against a World State response.

Shared by the seed (which reads the World State through the service) and the
smoke test (which reads it over HTTP): both hand in the same JSON shapes.

The checks compare stored facts with what the dataset says should be there.
Where a check compares two dates (a commitment before the reference date, an
actual date after a planned one) it is this test harness doing so, with the
fixed reference date of the dataset. The product itself compares nothing.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

DATASET_DIR = Path(__file__).resolve().parents[1] / "data" / "samples" / "nexus_demo"
MANIFEST_PATH = DATASET_DIR / "expected.json"

# Keys that must never appear anywhere in a World State response.
FORBIDDEN_KEYS = frozenset(
    {
        "risk_score",
        "delay_probability",
        "root_cause",
        "recovery_options",
        "recommended_action",
        "days_late",
        "is_late",
        "is_overdue",
        "severity",
        "risk_level",
        "recommendation",
    }
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: Any
    actual: Any

    def line(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return f"{verdict}  {self.name}: expected {self.expected}, actual {self.actual}"


def load_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return manifest


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def _order(project: dict[str, Any], po_number: str) -> dict[str, Any] | None:
    return next(
        (order for order in project["purchase_orders"]["items"] if order["po_number"] == po_number),
        None,
    )


def check_demo_world_state(
    manifest: dict[str, Any], summary: dict[str, Any], project: dict[str, Any]
) -> list[Check]:
    """Every dataset assertion, as a list of checks with expected and actual values.

    ``summary`` is the workspace World State summary; ``project`` is the project
    World State of the demo project, requested with ``include_history=true``
    and page sizes that hold the whole dataset.
    """
    checks: list[Check] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        checks.append(Check(name, expected == actual, expected, actual))

    as_of = date.fromisoformat(manifest["as_of"])
    conditions = manifest["conditions"]

    # --- counts, all taken from the database by the service ---------------------------
    for kind, expected in manifest["counts"].items():
        check(f"workspace count: {kind}", expected, summary["summary"].get(kind))
    check("project code", manifest["project_code"], project["project"]["code"])
    for kind in ("equipment", "purchase_orders", "purchase_order_items", "milestones", "suppliers"):
        check(f"project count: {kind}", manifest["counts"][kind], project["summary"].get(kind))
    check("equipment listed", manifest["counts"]["equipment"], len(project["equipment"]["items"]))
    check(
        "purchase orders listed",
        manifest["counts"]["purchase_orders"],
        len(project["purchase_orders"]["items"]),
    )
    check("source rows rejected", 0, summary["data_quality"]["invalid_records"])

    # --- condition: procurement gap ----------------------------------------------------
    gap_code = conditions["procurement_gap"]["equipment_code"]
    without_order = [
        (item["equipment_code"], item["criticality"])
        for item in project["equipment"]["items"]
        if not item["purchase_orders"]
    ]
    check("procurement gap: equipment without a line item", [(gap_code, "CRITICAL")], without_order)

    # --- condition: missing confirmation -----------------------------------------------
    unconfirmed = conditions["missing_confirmation"]["po_number"]
    without_acknowledgement = [
        order["po_number"]
        for order in project["purchase_orders"]["items"]
        if not any(m["milestone_type"] == "PO_ACKNOWLEDGEMENT" for m in order["milestones"])
    ]
    check(
        "missing confirmation: orders without acknowledgement",
        [unconfirmed],
        without_acknowledgement,
    )

    # --- condition: changed commitment -------------------------------------------------
    changed = conditions["changed_commitment"]
    order = _order(project, changed["po_number"]) or {}
    history = [
        (version["version_no"], version["committed_delivery_date"])
        for version in order.get("commitment_history") or []
    ]
    check("changed commitment: history", [(1, changed["first"]), (2, changed["revised"])], history)
    current = order.get("current_commitment") or {}
    check(
        "changed commitment: current version",
        (2, changed["revised"]),
        (current.get("version_no"), current.get("committed_delivery_date")),
    )
    revised = [
        other["po_number"]
        for other in project["purchase_orders"]["items"]
        if other["commitment_version_count"] > 1
    ]
    check("changed commitment: orders with more than one version", [changed["po_number"]], revised)

    # --- condition: milestone slippage (planned and actual, both kept) -----------------
    slipped = conditions["milestone_slippage"]
    order = _order(project, slipped["po_number"]) or {}
    milestone = next(
        (
            m
            for m in order.get("milestones", [])
            if m["milestone_type"] == slipped["milestone_type"]
            and m["sequence_no"] == slipped["sequence_no"]
        ),
        {},
    )
    planned = (milestone.get("current_plan") or {}).get("planned_date")
    check(
        "milestone slippage: planned and actual dates",
        (slipped["planned_date"], slipped["actual_date"]),
        (planned, milestone.get("actual_date")),
    )
    later = [
        (other["po_number"], m["milestone_type"])
        for other in project["purchase_orders"]["items"]
        for m in other["milestones"]
        if m["actual_date"]
        and m["current_plan"]
        and m["actual_date"] > m["current_plan"]["planned_date"]
    ]
    check(
        "milestone slippage: milestones whose actual date is after the plan",
        [(slipped["po_number"], slipped["milestone_type"])],
        later,
    )

    # --- condition: overdue delivery candidate ------------------------------------------
    overdue = conditions["overdue_delivery_candidate"]
    candidates = []
    for other in project["purchase_orders"]["items"]:
        commitment = other["current_commitment"]
        delivered = any(
            m["milestone_type"] == "DELIVERY" and m["status"] == "COMPLETED"
            for m in other["milestones"]
        )
        if (
            commitment
            and not delivered
            and date.fromisoformat(commitment["committed_delivery_date"]) < as_of
        ):
            candidates.append((other["po_number"], commitment["committed_delivery_date"]))
    check(
        f"overdue delivery candidate: commitment before {as_of} and no completed delivery",
        [(overdue["po_number"], overdue["committed_delivery_date"])],
        candidates,
    )

    # --- what is recorded as missing ---------------------------------------------------
    check(
        "data quality: missing information",
        {
            "EQUIPMENT_WITHOUT_PO_LINE_ITEM": 1,
            "PO_ACKNOWLEDGEMENT_NOT_RECORDED": 1,
            "PO_WITHOUT_SUPPLIER_COMMITMENT": 1,
        },
        project["data_quality"]["warning_counts"],
    )
    check(
        "data quality: which records",
        [
            ("EQUIPMENT_WITHOUT_PO_LINE_ITEM", gap_code),
            ("PO_ACKNOWLEDGEMENT_NOT_RECORDED", unconfirmed),
            ("PO_WITHOUT_SUPPLIER_COMMITMENT", unconfirmed),
        ],
        [(w["code"], w["reference"]) for w in project["data_quality"]["warnings"]],
    )

    # --- nothing but facts -------------------------------------------------------------
    check(
        "no risk, lateness or recommendation field in the World State",
        [],
        sorted((_keys(summary) | _keys(project)) & FORBIDDEN_KEYS),
    )
    return checks


def comparable(world_state: Any) -> Any:
    """A World State response without the one field that changes on every call."""
    if isinstance(world_state, dict):
        return {
            key: comparable(value) for key, value in world_state.items() if key != "generated_at"
        }
    if isinstance(world_state, (list, tuple)):
        return [comparable(item) for item in world_state]
    return world_state
