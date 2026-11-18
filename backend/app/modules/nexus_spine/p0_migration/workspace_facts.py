"""Facts derived from the records published in a workspace.

Pure functions over plain records: no database, no model and no clock (the
caller passes "today"). Every derived fact carries the field names and values
it was read from, so an answer can say why an order counts as late or a stock
position as short. Nothing is estimated: a value that cannot be read as a date
or a number is reported as unreadable instead of being guessed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.modules.nexus_spine.p0_migration.country_names import (
    countries_mentioned,
    country_code,
    country_name,
    is_country_field,
)
from app.modules.nexus_spine.p0_migration.question_focus import (
    AGGREGATE_AVERAGE,
    AGGREGATE_MAX,
    AGGREGATE_MIN,
    AGGREGATE_SUM,
    STOP_WORDS,
    TYPE_WORDS,
    fold_word,
)

FLOW_TYPES: tuple[str, ...] = ("PurchaseOrder", "SalesOrder", "Shipment")
INVENTORY_TYPES: tuple[str, ...] = ("InventoryItem", "InventoryLot")
SUPPLY_TYPES: tuple[str, ...] = ("PurchaseOrder", "Shipment")

STATUS_FIELDS: tuple[str, ...] = (
    "status",
    "order_status",
    "po_status",
    "so_status",
    "shipment_status",
    "delivery_status",
    "line_status",
    "state",
)
PROMISED_FIELDS: tuple[str, ...] = (
    "promised_date",
    "promise_date",
    "promised_delivery_date",
    "committed_date",
    "commit_date",
    "due_date",
    "required_date",
    "requested_delivery_date",
    "requested_date",
    "need_by_date",
    "need_by",
    "sla_due_date",
    "planned_delivery_date",
    "planned_date",
    "scheduled_delivery_date",
    "scheduled_date",
)
EXPECTED_FIELDS: tuple[str, ...] = (
    "expected_date",
    "expected_delivery_date",
    "expected_arrival_date",
    "expected_arrival",
    "eta",
    "current_eta",
    "new_eta",
    "revised_eta",
    "estimated_delivery_date",
    "estimated_arrival",
    "estimated_date",
    "revised_date",
    "revised_delivery_date",
    "forecast_delivery_date",
)
ACTUAL_FIELDS: tuple[str, ...] = (
    "actual_delivery_date",
    "actual_date",
    "actual_arrival_date",
    "delivered_date",
    "received_date",
    "receipt_date",
)
QUANTITY_FIELDS: tuple[str, ...] = (
    "quantity",
    "qty",
    "order_quantity",
    "ordered_quantity",
    "quantity_ordered",
    "order_qty",
    "units",
)
ON_HAND_FIELDS: tuple[str, ...] = (
    "quantity_on_hand",
    "on_hand_qty",
    "on_hand_quantity",
    "qty_on_hand",
    "on_hand",
    "stock_on_hand",
    "available_quantity",
    "available_qty",
    "quantity_available",
    "stock_quantity",
    "stock_qty",
    "stock",
    "quantity",
    "qty",
)
THRESHOLD_FIELDS: tuple[str, ...] = (
    "safety_stock",
    "safety_stock_qty",
    "safety_stock_quantity",
    "minimum_stock",
    "min_stock",
    "min_stock_level",
    "reorder_point",
    "reorder_level",
)
BOM_PARENT_FIELDS: tuple[str, ...] = (
    "parent_sku",
    "product_sku",
    "parent_product",
    "parent_item",
    "assembly_sku",
    "finished_good_sku",
    "parent",
)
BOM_CHILD_FIELDS: tuple[str, ...] = (
    "child_sku",
    "component_sku",
    "child_item",
    "component",
    "material_sku",
    "part_sku",
    "child",
)

# Status values, compared after lower-casing and replacing separators with "_".
LATE_STATUSES: frozenset[str] = frozenset(
    {"delayed", "late", "overdue", "past_due", "behind", "behind_schedule"}
)
ATTENTION_STATUSES: frozenset[str] = frozenset(
    {
        "at_risk",
        "on_hold",
        "hold",
        "held",
        "blocked",
        "backordered",
        "back_ordered",
        "backorder",
        "exception",
        "disrupted",
        "stuck",
        "suspended",
    }
)
CLOSED_STATUSES: frozenset[str] = frozenset(
    {
        "delivered",
        "received",
        "closed",
        "complete",
        "completed",
        "cancelled",
        "canceled",
        "fulfilled",
        "done",
        "void",
        "voided",
        "returned",
    }
)

# Fields that hold the record's own name, by entity type.
NAME_FIELDS: dict[str, tuple[str, ...]] = {
    "Supplier": (
        "supplier_name",
        "vendor_name",
        "legal_name",
        "name",
        "company_name",
        "seller_name",
    ),
    "Customer": ("customer_name", "legal_name", "name", "company_name", "client_name"),
    "Carrier": ("carrier_name", "name"),
    "Facility": (
        "facility_name",
        "warehouse_name",
        "plant_name",
        "site_name",
        "dc_name",
        "port_name",
        "name",
    ),
    "Product": (
        "product_name",
        "item_name",
        "material_name",
        "name",
        "description",
        "product_description",
        "item_description",
    ),
    "Route": ("route_name", "name"),
    "Region": ("region_name", "name"),
    "DemandRegion": ("demand_region_name", "region_name", "name"),
}
DEFAULT_NAME_FIELDS: tuple[str, ...] = ("name", "title")

# Parts of a column name that suggest it points at another kind of record.
REFERENCE_HINTS: dict[str, tuple[str, ...]] = {
    "Supplier": ("supplier", "vendor", "seller"),
    "Product": ("sku", "product", "item", "material", "part", "component"),
    "Facility": (
        "facility",
        "warehouse",
        "plant",
        "site",
        "location",
        "depot",
        "factory",
        "port",
        "dc",
    ),
    "Customer": ("customer", "client", "buyer", "consignee"),
    "Carrier": ("carrier", "scac", "forwarder"),
}

MAX_VALUE_LENGTH = 200


def clean(value: Any) -> str | None:
    """Text of a stored value, or None when it is empty."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_status(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def normalize_name(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def parse_number(value: Any) -> float | None:
    """Read a quantity. Only unambiguous notations are accepted."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = clean(value)
    if text is None:
        return None
    text = text.replace(" ", "").replace("\u00a0", "")
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text):
        pass
    elif re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", text) or re.fullmatch(
        r"[+-]?\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?", text
    ):
        # Thousands separators, including lakh/crore grouping (1,23,456).
        text = text.replace(",", "")
    elif re.fullmatch(r"[+-]?\d{1,3}(?:\.\d{3})+,\d+", text):
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[+-]?\d+,\d{1,2}", text):
        text = text.replace(",", ".")
    else:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_date(value: Any) -> date | None:
    """Read an ISO date or timestamp (2026-11-05, 2026/11/05, 2026-11-05T18:00:00Z).

    Day-first and month-first notations cannot be told apart, so they are not read.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean(value)
    if text is None:
        return None
    candidate = text.replace("/", "-")
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    if not re.match(r"^\d{4}-\d{2}-\d{2}", candidate):
        return None
    try:
        return datetime.fromisoformat(candidate).date()
    except ValueError:
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError:
            return None


def format_number(value: float) -> str:
    """Whole numbers without decimals, others with up to two."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


@dataclass
class NodeRecord:
    """One published record (graph node) with case-insensitive field access."""

    node_id: str
    entity_type: str
    entity_id: str
    attributes: Mapping[str, Any]
    first_seen_version: int = 0
    last_modified_version: int = 0
    _keys: dict[str, str] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._keys = {
            str(key).strip().lower(): str(key)
            for key in self.attributes
            if not str(key).startswith("_")
        }

    def value(self, *names: str) -> tuple[str, str] | None:
        """(stored field name, text) of the first named field that has a value."""
        for name in names:
            key = self._keys.get(name)
            if key is None:
                continue
            text = clean(self.attributes.get(key))
            if text is not None:
                return key, text
        return None

    def items(self) -> list[tuple[str, str]]:
        """Non-empty fields in stored order, without internal bookkeeping keys."""
        result: list[tuple[str, str]] = []
        for key in self._keys.values():
            text = clean(self.attributes.get(key))
            if text is not None:
                result.append((key, text))
        return result

    @property
    def facility_kind(self) -> str | None:
        return clean(self.attributes.get("_facility_type"))

    @property
    def name(self) -> str | None:
        found = self.value(*NAME_FIELDS.get(self.entity_type, DEFAULT_NAME_FIELDS))
        return found[1] if found else None

    @property
    def label(self) -> str:
        name = self.name
        return f"{self.entity_id} {name}" if name and name != self.entity_id else self.entity_id

    def ref(self) -> dict[str, Any]:
        return {"entity_type": self.entity_type, "entity_id": self.entity_id, "name": self.name}

    def summary(self, *, max_attributes: int | None = None) -> dict[str, Any]:
        """JSON-ready view: identity, name and stored fields (long values shortened)."""
        attributes: dict[str, str] = {}
        for key, text in self.items():
            if max_attributes is not None and len(attributes) >= max_attributes:
                break
            attributes[key] = (
                text if len(text) <= MAX_VALUE_LENGTH else text[:MAX_VALUE_LENGTH] + "…"
            )
        result: dict[str, Any] = {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "name": self.name,
            "attributes": attributes,
            "first_seen_version": self.first_seen_version,
            "last_modified_version": self.last_modified_version,
        }
        if self.facility_kind:
            result["facility_kind"] = self.facility_kind
        return result


class WorkspaceIndex:
    """Lookup tables over the loaded records."""

    def __init__(self, records: Iterable[NodeRecord]) -> None:
        self.records: list[NodeRecord] = list(records)
        self.by_type: dict[str, list[NodeRecord]] = {}
        self._by_id: dict[str, dict[str, NodeRecord]] = {}
        self._by_folded_id: dict[str, dict[str, NodeRecord]] = {}
        self._by_name: dict[str, dict[str, NodeRecord | None]] = {}
        for record in self.records:
            self.by_type.setdefault(record.entity_type, []).append(record)
            self._by_id.setdefault(record.entity_type, {})[record.entity_id] = record
            self._by_folded_id.setdefault(record.entity_type, {}).setdefault(
                record.entity_id.lower(), record
            )
            name = record.name
            if name:
                names = self._by_name.setdefault(record.entity_type, {})
                key = normalize_name(name)
                # A name shared by two records identifies neither of them.
                names[key] = None if key in names and names[key] is not record else record
        for records_of_type in self.by_type.values():
            records_of_type.sort(key=lambda item: item.entity_id)

    def of_types(self, entity_types: Iterable[str]) -> list[NodeRecord]:
        return [
            record for entity_type in entity_types for record in self.by_type.get(entity_type, [])
        ]

    def get(self, entity_type: str, entity_id: str) -> NodeRecord | None:
        return self._by_id.get(entity_type, {}).get(entity_id)

    def lookup(self, entity_type: str, text: str) -> NodeRecord | None:
        """Record of a type identified by an ID (exact, then case-insensitive) or a unique name."""
        exact = self._by_id.get(entity_type, {}).get(text)
        if exact is not None:
            return exact
        folded = self._by_folded_id.get(entity_type, {}).get(text.lower())
        if folded is not None:
            return folded
        return self._by_name.get(entity_type, {}).get(normalize_name(text))

    def reference(self, record: NodeRecord, target_type: str) -> NodeRecord | None:
        """The record of ``target_type`` that ``record`` points at, if any.

        A field counts as a pointer when its name suggests the target kind and
        its value is the ID or the unique name of a published record of that kind.
        """
        hints = REFERENCE_HINTS.get(target_type, ())
        if not hints or not self.by_type.get(target_type):
            return None
        for key, text in record.items():
            lowered = key.lower()
            if not any(hint in lowered for hint in hints):
                continue
            target = self.lookup(target_type, text)
            if target is not None and target is not record:
                return target
        return None

    def reference_by_fields(
        self, record: NodeRecord, target_type: str, fields: Sequence[str]
    ) -> NodeRecord | None:
        found = record.value(*fields)
        if found is None:
            return None
        return self.lookup(target_type, found[1])


def _ref(record: NodeRecord | None) -> dict[str, Any] | None:
    return record.ref() if record is not None else None


def assess_flow(record: NodeRecord, index: WorkspaceIndex, today: date) -> dict[str, Any]:
    """Lateness of one order or shipment, with the fields the verdict rests on."""
    status = record.value(*STATUS_FIELDS)
    status_key = normalize_status(status[1]) if status else ""
    promised = record.value(*PROMISED_FIELDS)
    expected = record.value(*EXPECTED_FIELDS)
    actual = record.value(*ACTUAL_FIELDS)
    promised_on = parse_date(promised[1]) if promised else None
    expected_on = parse_date(expected[1]) if expected else None
    actual_on = parse_date(actual[1]) if actual else None
    unreadable = [
        found[0]
        for found, parsed in ((promised, promised_on), (expected, expected_on), (actual, actual_on))
        if found is not None and parsed is None
    ]

    is_open = status_key not in CLOSED_STATUSES and actual_on is None
    reasons: list[str] = []
    days_late: int | None = None

    if status and (status_key in LATE_STATUSES or status_key in ATTENTION_STATUSES):
        reasons.append(f"{status[0]} is {status[1]}")
    if promised_on and expected_on and expected_on > promised_on:
        days_late = (expected_on - promised_on).days
        reasons.append(
            f"now expected {expected_on.isoformat()}, {_days(days_late)} after the promised "
            f"{promised_on.isoformat()}"
        )
    delivered_late = bool(promised_on and actual_on and actual_on > promised_on)
    if delivered_late and promised_on and actual_on:
        days_late = (actual_on - promised_on).days
        reasons.append(
            f"arrived {actual_on.isoformat()}, {_days(days_late)} after the promised "
            f"{promised_on.isoformat()}"
        )
    if is_open and promised_on and promised_on < today:
        overdue = (today - promised_on).days
        if days_late is None:
            days_late = overdue
            reasons.append(
                f"promised for {promised_on.isoformat()} and not marked as delivered "
                f"{_days(overdue)} later"
            )
        if expected_on and expected_on < today:
            reasons.append(f"the expected date {expected_on.isoformat()} has also passed")

    quantity = record.value(*QUANTITY_FIELDS)
    quantity_value = parse_number(quantity[1]) if quantity else None
    return {
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "status": status[1] if status else None,
        "status_field": status[0] if status else None,
        "open": is_open,
        "late": bool(reasons) and is_open,
        "delivered_late": delivered_late and not is_open,
        "days_late": days_late,
        "reasons": reasons,
        "promised_date": promised_on.isoformat() if promised_on else None,
        "promised_field": promised[0] if promised else None,
        "expected_date": expected_on.isoformat() if expected_on else None,
        "expected_field": expected[0] if expected else None,
        "actual_date": actual_on.isoformat() if actual_on else None,
        "actual_field": actual[0] if actual else None,
        "unreadable_date_fields": unreadable,
        "quantity": quantity_value,
        "quantity_text": quantity[1] if quantity else None,
        "supplier": _ref(index.reference(record, "Supplier")),
        "customer": _ref(index.reference(record, "Customer")),
        "product": _ref(index.reference(record, "Product")),
        "facility": _ref(index.reference(record, "Facility")),
    }


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def assess_stock(record: NodeRecord, index: WorkspaceIndex) -> dict[str, Any] | None:
    """Stock position of one inventory record against its own threshold field."""
    on_hand: tuple[str, float] | None = None
    for name in ON_HAND_FIELDS:
        found = record.value(name)
        if found is None:
            continue
        number = parse_number(found[1])
        if number is not None:
            on_hand = (found[0], number)
            break
    if on_hand is None:
        return None
    threshold: tuple[str, float] | None = None
    for name in THRESHOLD_FIELDS:
        found = record.value(name)
        if found is None:
            continue
        number = parse_number(found[1])
        if number is not None:
            threshold = (found[0], number)
            break
    below = threshold is not None and on_hand[1] < threshold[1]
    return {
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "product": _ref(index.reference(record, "Product")),
        "facility": _ref(index.reference(record, "Facility")),
        "on_hand": on_hand[1],
        "on_hand_field": on_hand[0],
        "threshold": threshold[1] if threshold else None,
        "threshold_field": threshold[0] if threshold else None,
        "below_threshold": below,
        "shortfall": (threshold[1] - on_hand[1]) if threshold and below else None,
        "out_of_stock": on_hand[1] <= 0,
    }


def flagged_status(record: NodeRecord) -> dict[str, Any] | None:
    """A record whose own status field says it is late or needs attention."""
    status = record.value(*STATUS_FIELDS)
    if status is None:
        return None
    key = normalize_status(status[1])
    if key not in LATE_STATUSES and key not in ATTENTION_STATUSES:
        return None
    return {**record.ref(), "status": status[1], "status_field": status[0]}


def _late_sort_key(item: Mapping[str, Any]) -> tuple[int, str, str]:
    days = item.get("days_late")
    return (
        -(days if isinstance(days, int) else -1),
        str(item["entity_type"]),
        str(item["entity_id"]),
    )


def _involves(item: Mapping[str, Any], focus: set[tuple[str, str]]) -> bool:
    """True when an assessed order or stock position is, or points at, a focus record."""
    if (str(item["entity_type"]), str(item["entity_id"])) in focus:
        return True
    for role in ("supplier", "customer", "product", "facility"):
        ref = item.get(role)
        if isinstance(ref, Mapping) and (str(ref["entity_type"]), str(ref["entity_id"])) in focus:
            return True
    return False


def _focus_keys(focus: Sequence[NodeRecord]) -> set[tuple[str, str]]:
    return {(record.entity_type, record.entity_id) for record in focus}


def late_flows(
    index: WorkspaceIndex,
    today: date,
    *,
    entity_types: Sequence[str] = FLOW_TYPES,
    focus: Sequence[NodeRecord] = (),
) -> dict[str, Any]:
    """Orders and shipments that are late or flagged, and those that arrived late."""
    types = [entity_type for entity_type in entity_types if entity_type in FLOW_TYPES] or list(
        FLOW_TYPES
    )
    keys = _focus_keys(focus)
    assessed: dict[str, int] = {}
    late: list[dict[str, Any]] = []
    delivered_late: list[dict[str, Any]] = []
    unreadable = 0
    for record in index.of_types(types):
        flow = assess_flow(record, index, today)
        if keys and not _involves(flow, keys):
            continue
        assessed[record.entity_type] = assessed.get(record.entity_type, 0) + 1
        if flow["unreadable_date_fields"]:
            unreadable += 1
        if flow["late"]:
            late.append(flow)
        elif flow["delivered_late"]:
            delivered_late.append(flow)
    late.sort(key=_late_sort_key)
    delivered_late.sort(key=_late_sort_key)
    return {
        "as_of": today.isoformat(),
        "assessed": assessed,
        "late": late,
        "late_count": len(late),
        "delivered_late": delivered_late,
        "delivered_late_count": len(delivered_late),
        "unreadable_date_count": unreadable,
    }


def stock_positions(index: WorkspaceIndex, *, focus: Sequence[NodeRecord] = ()) -> dict[str, Any]:
    """Inventory records below their threshold or with nothing on hand."""
    keys = _focus_keys(focus)
    assessed = 0
    without_quantity = 0
    without_threshold = 0
    short: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    for record in index.of_types(INVENTORY_TYPES):
        position = assess_stock(record, index)
        if position is None:
            if not keys or (record.entity_type, record.entity_id) in keys:
                without_quantity += 1
            continue
        if keys and not _involves(position, keys):
            continue
        assessed += 1
        positions.append(position)
        if position["threshold"] is None:
            without_threshold += 1
        if position["below_threshold"] or position["out_of_stock"]:
            short.append(position)
    short.sort(
        key=lambda item: (
            -(item["shortfall"] if item["shortfall"] is not None else 0.0),
            str(item["entity_id"]),
        )
    )
    return {
        "assessed": assessed,
        "positions": positions,
        "short": short,
        "short_count": len(short),
        "without_quantity": without_quantity,
        "without_threshold": without_threshold,
    }


def flagged_records(
    index: WorkspaceIndex, entity_types: Sequence[str] = ("Supplier",)
) -> list[dict[str, Any]]:
    """Records of the given kinds whose own status marks them late or at risk."""
    return [
        flag
        for record in index.of_types(entity_types)
        if (flag := flagged_status(record)) is not None
    ]


def supplier_rollup(index: WorkspaceIndex, today: date) -> list[dict[str, Any]]:
    """Per supplier: its orders, how many are open and late, and its own status flag."""
    rows: dict[str, dict[str, Any]] = {}
    for supplier in index.by_type.get("Supplier", []):
        rows[supplier.entity_id] = {
            **supplier.ref(),
            "flag": flagged_status(supplier),
            "order_count": 0,
            "open_order_count": 0,
            "late_order_count": 0,
            "late_orders": [],
        }
    for record in index.of_types(SUPPLY_TYPES):
        flow = assess_flow(record, index, today)
        supplier_ref = flow["supplier"]
        if not supplier_ref:
            continue
        row = rows.get(str(supplier_ref["entity_id"]))
        if row is None:
            continue
        row["order_count"] += 1
        if flow["open"]:
            row["open_order_count"] += 1
        if flow["late"]:
            row["late_order_count"] += 1
            row["late_orders"].append(flow["entity_id"])
    return sorted(
        rows.values(),
        key=lambda row: (-int(row["late_order_count"]), row["flag"] is None, str(row["entity_id"])),
    )


_COUNTERPARTY_ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    # kind of the record -> (its role on an order, the roles to report)
    "Product": ("product", ("supplier", "customer")),
    "Supplier": ("supplier", ("product",)),
    "Customer": ("customer", ("product",)),
}


def counterparties(index: WorkspaceIndex, today: date, record: NodeRecord) -> dict[str, Any]:
    """Who a product is ordered from and by, or what a supplier or customer's
    orders are for, counted from the published orders and shipments."""
    roles = _COUNTERPARTY_ROLES.get(record.entity_type)
    if roles is None:
        return {}
    own_role, other_roles = roles
    found: dict[str, dict[str, dict[str, Any]]] = {role: {} for role in other_roles}
    for flow_record in index.of_types(FLOW_TYPES):
        flow = assess_flow(flow_record, index, today)
        own = flow[own_role]
        if not own or own["entity_id"] != record.entity_id:
            continue
        for role in other_roles:
            ref = flow[role]
            if not ref:
                continue
            row = found[role].setdefault(
                str(ref["entity_id"]), {**ref, "order_count": 0, "late_order_count": 0}
            )
            row["order_count"] += 1
            if flow["late"]:
                row["late_order_count"] += 1
    return {
        f"{role}s": sorted(
            rows.values(), key=lambda row: (-int(row["order_count"]), str(row["entity_id"]))
        )
        for role, rows in found.items()
        if rows
    }


def _bom_parents(index: WorkspaceIndex) -> dict[str, set[str]]:
    """Component product ID -> product IDs it goes into, from published BOM records."""
    parents: dict[str, set[str]] = {}
    for record in index.by_type.get("BOM", []):
        parent = index.reference_by_fields(record, "Product", BOM_PARENT_FIELDS)
        child = index.reference_by_fields(record, "Product", BOM_CHILD_FIELDS)
        if parent is None or child is None or parent is child:
            continue
        parents.setdefault(child.entity_id, set()).add(parent.entity_id)
    return parents


def _ancestors(product_id: str, parents: Mapping[str, set[str]]) -> list[str]:
    """Every product a component ends up in, following the BOM upwards."""
    seen: set[str] = set()
    queue = [product_id]
    while queue:
        current = queue.pop()
        for parent in sorted(parents.get(current, ())):
            if parent not in seen and parent != product_id:
                seen.add(parent)
                queue.append(parent)
    return sorted(seen)


def build_exposure(
    index: WorkspaceIndex, today: date, *, focus: Sequence[NodeRecord] = ()
) -> dict[str, Any]:
    """Trace late supply to the parts it carries, their stock, and the customer orders needing them.

    Late purchase orders and inbound shipments are grouped by product. Each
    product is checked against its inventory records, followed up the bill of
    materials, and matched with open sales orders for it or for anything it
    goes into. Links the published data cannot support are listed as gaps.
    """
    keys = _focus_keys(focus)
    flows = [assess_flow(record, index, today) for record in index.of_types(FLOW_TYPES)]

    def is_supply(flow: Mapping[str, Any]) -> bool:
        if flow["entity_type"] == "PurchaseOrder":
            return True
        return flow["entity_type"] == "Shipment" and flow["customer"] is None

    late_supply = [flow for flow in flows if flow["late"] and is_supply(flow)]
    late_customer = [flow for flow in flows if flow["late"] and not is_supply(flow)]
    if keys:
        late_supply = [flow for flow in late_supply if _involves(flow, keys)]
        late_customer = [flow for flow in late_customer if _involves(flow, keys)]
    late_supply.sort(key=_late_sort_key)
    late_customer.sort(key=_late_sort_key)

    stock_by_product: dict[str, list[dict[str, Any]]] = {}
    for record in index.of_types(INVENTORY_TYPES):
        position = assess_stock(record, index)
        if position is None or not position["product"]:
            continue
        stock_by_product.setdefault(str(position["product"]["entity_id"]), []).append(position)

    supply_by_product: dict[str, list[dict[str, Any]]] = {}
    for flow in flows:
        if is_supply(flow) and flow["product"]:
            supply_by_product.setdefault(str(flow["product"]["entity_id"]), []).append(flow)

    parents = _bom_parents(index)
    open_sales = [flow for flow in flows if flow["entity_type"] == "SalesOrder" and flow["open"]]

    parts: dict[str, dict[str, Any]] = {}
    unlinked: list[str] = []
    for flow in late_supply:
        product = flow["product"]
        if not product:
            unlinked.append(str(flow["entity_id"]))
            continue
        product_id = str(product["entity_id"])
        part = parts.setdefault(
            product_id,
            {
                "product": product,
                "late_orders": [],
                "late_quantity": 0.0,
                "late_quantity_complete": True,
                "suppliers": [],
                "stock": stock_by_product.get(product_id, []),
                "goes_into": [],
                "customer_orders": [],
            },
        )
        part["late_orders"].append(flow["entity_id"])
        if flow["quantity"] is None:
            part["late_quantity_complete"] = False
        else:
            part["late_quantity"] += float(flow["quantity"])
        supplier = flow["supplier"]
        if supplier and supplier not in part["suppliers"]:
            part["suppliers"].append(supplier)

    customer_orders: list[dict[str, Any]] = []
    for product_id, part in sorted(parts.items()):
        ancestors = _ancestors(product_id, parents)
        part["goes_into"] = [
            ref
            for ancestor in ancestors
            if (ref := _ref(index.get("Product", ancestor))) is not None
        ]
        needed = {product_id, *ancestors}
        for order in open_sales:
            ordered = order["product"]
            if not ordered or str(ordered["entity_id"]) not in needed:
                continue
            via = str(ordered["entity_id"])
            entry = {
                "entity_type": order["entity_type"],
                "entity_id": order["entity_id"],
                "customer": order["customer"],
                "product": ordered,
                "quantity": order["quantity"],
                "promised_date": order["promised_date"],
                "status": order["status"],
                "needs_part": part["product"],
                "through_product": ordered if via != product_id else None,
            }
            part["customer_orders"].append(order["entity_id"])
            customer_orders.append(entry)
        late_supplier_ids = {str(ref["entity_id"]) for ref in part["suppliers"]}
        late_order_ids = set(part["late_orders"])
        on_time: list[dict[str, Any]] = []
        others: dict[str, dict[str, Any]] = {}
        for flow in supply_by_product.get(product_id, []):
            if flow["open"] and not flow["late"] and flow["entity_id"] not in late_order_ids:
                on_time.append(
                    {
                        "entity_type": flow["entity_type"],
                        "entity_id": flow["entity_id"],
                        "quantity": flow["quantity"],
                        "due": flow["expected_date"] or flow["promised_date"],
                        "supplier": flow["supplier"],
                    }
                )
            supplier = flow["supplier"]
            if supplier and str(supplier["entity_id"]) not in late_supplier_ids:
                other = others.setdefault(
                    str(supplier["entity_id"]),
                    {**supplier, "order_count": 0, "late_order_count": 0},
                )
                other["order_count"] += 1
                if flow["late"]:
                    other["late_order_count"] += 1
        # Open supply for the same part that is not late, and other suppliers
        # that appear on published orders for it. Both are read from the data;
        # neither says the supplier has capacity or would accept an order.
        part["on_time_supply"] = sorted(
            on_time, key=lambda item: (str(item["due"] or "9999"), str(item["entity_id"]))
        )
        part["other_suppliers"] = [others[supplier_id] for supplier_id in sorted(others)]

        stock = part["stock"]
        if not stock:
            part["stock_state"] = "no_inventory_record"
        elif any(position["below_threshold"] or position["out_of_stock"] for position in stock):
            part["stock_state"] = "below_threshold"
        elif all(position["threshold"] is None for position in stock):
            part["stock_state"] = "no_threshold"
        else:
            part["stock_state"] = "above_threshold"

    customer_orders.sort(
        key=lambda item: (str(item["promised_date"] or "9999"), str(item["entity_id"]))
    )
    gaps: list[str] = []
    if not index.by_type.get("SalesOrder"):
        gaps.append("no_sales_orders")
    if not index.by_type.get("BOM"):
        gaps.append("no_bill_of_materials")
    if not index.of_types(INVENTORY_TYPES):
        gaps.append("no_inventory")
    return {
        "as_of": today.isoformat(),
        "late_supply": late_supply,
        "late_supply_count": len(late_supply),
        "parts_at_risk": [parts[product_id] for product_id in sorted(parts)],
        "late_supply_without_product": unlinked,
        "customer_orders": customer_orders,
        "customer_order_count": len({item["entity_id"] for item in customer_orders}),
        "late_customer_flows": late_customer,
        "gaps": gaps,
    }


def attention_summary(index: WorkspaceIndex, today: date) -> dict[str, Any]:
    """Counts and identifiers of what stands out in the published records."""
    late = late_flows(index, today)
    stock = stock_positions(index)
    flagged = flagged_records(index, ("Supplier", "Carrier", "Customer"))
    late_by_type: dict[str, list[str]] = {}
    for flow in late["late"]:
        late_by_type.setdefault(str(flow["entity_type"]), []).append(str(flow["entity_id"]))
    return {
        "as_of": today.isoformat(),
        "late_by_type": late_by_type,
        "late_count": late["late_count"],
        "flows_assessed": late["assessed"],
        "stock_short": [
            {
                "entity_id": position["entity_id"],
                "product": position["product"],
                "facility": position["facility"],
                "on_hand": position["on_hand"],
                "threshold": position["threshold"],
                "threshold_field": position["threshold_field"],
            }
            for position in stock["short"]
        ],
        "stock_short_count": stock["short_count"],
        "stock_assessed": stock["assessed"],
        "flagged": flagged,
        "flagged_count": len(flagged),
    }


def diff_attributes(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, str | None]]:
    """Fields whose value differs between two versions of a record.

    ``after`` holds only the fields the newer source supplied; a field it does
    not mention keeps its earlier value and is therefore not a change.
    """
    changes: list[dict[str, str | None]] = []
    for key, value in after.items():
        if str(key).startswith("_"):
            continue
        new = clean(value)
        old = clean(before.get(key))
        if new is None or new == old:
            continue
        changes.append({"field": str(key), "before": old, "after": new})
    return changes


# ── Matching a question against the published records ────────────────────────

# Company forms, kinds of place and filler words that do not identify a named
# record. Compared after folding plurals, so the entries are singular.
_GENERIC_NAME_WORDS: frozenset[str] = frozenset(
    {
        "ab", "ag", "and", "as", "branch", "bv", "central", "co", "company", "corp", "division",
        "east", "enterprise", "first", "for", "general", "global", "gmbh", "group", "holding",
        "hub", "inc", "industry", "international", "kk", "lda", "limited", "llc", "logistic",
        "ltd", "main", "manufacturing", "national", "new", "north", "nv", "of", "office", "oy",
        "plant", "plc", "pvt", "sa", "service", "shop", "solution", "south", "spa", "srl",
        "storage", "store", "system", "the", "trading", "united", "warehouse", "west", "work",
        "yard",
    }
)  # fmt: skip
_STOP_VALUES: frozenset[str] = frozenset(
    {
        "all",
        "and",
        "any",
        "are",
        "for",
        "n a",
        "none",
        "not",
        "null",
        "other",
        "the",
        "unknown",
        "yes",
    }
)
_NEGATIONS: tuple[str, ...] = (
    "not",
    "non",
    "no",
    "except",
    "excluding",
    "without",
    "other than",
    "isn t",
    "aren t",
    "isnt",
    "arent",
    "outside",
)
# Words that may stand between a negation and the value it negates: "not in
# DE", "not from the US", "outside of Germany".
_BETWEEN_NEGATION_AND_VALUE: frozenset[str] = frozenset(
    {"in", "from", "at", "of", "to", "the", "a", "an", "with", "by", "on", "based", "located"}
)
MAX_FILTER_VALUE_LENGTH = 40
MAX_SINGLE_WORD_MATCHES = 3
MAX_BREAKDOWN_ROWS = 10
MAX_EXTREME_RECORDS = 5


def _negated(before: str) -> bool:
    """True when the text in front of a value negates it ("not", "not in", "outside of")."""
    words = before.split()
    skipped = 0
    while words and words[-1] in _BETWEEN_NEGATION_AND_VALUE and skipped < 3:
        words.pop()
        skipped += 1
    if not words:
        return False
    tail = " ".join(words[-2:])
    return any(tail == word or tail.endswith(f" {word}") for word in _NEGATIONS)


def _specific(words: Sequence[str]) -> bool:
    """True when at least one of the words could identify a record.

    Company forms ("GmbH"), record kinds ("warehouse", "distribution centre")
    and everyday words do not: "which distribution centre is short?" must not
    be read as naming "Hamburg Distribution Centre".
    """
    for word in words:
        folded = fold_word(word)
        if (
            len(folded) >= 3
            and folded not in _GENERIC_NAME_WORDS
            and folded not in TYPE_WORDS
            and folded not in STOP_WORDS
        ):
            return True
    return False


def link_names(normalized_question: str, index: WorkspaceIndex) -> list[dict[str, Any]]:
    """Records whose own name appears in the question.

    A record matches on its full name, on the first two or more words of it,
    on two or more consecutive words from inside it, or on its first word
    alone when that word is distinctive and no other record's name starts
    with it. Regular plurals are ignored on both sides, so "ball bearings"
    names "Ball Bearing 6205". Part of a name counts only when it holds a
    word that could identify a record (not just "distribution centre"). Each
    match reports the text it matched on.
    """
    padded = f" {normalized_question} "
    folded_question = f" {' '.join(fold_word(word) for word in normalized_question.split())} "

    def present(tokens: Sequence[str]) -> bool:
        return (
            f" {' '.join(tokens)} " in padded
            or f" {' '.join(fold_word(token) for token in tokens)} " in folded_question
        )

    named: list[tuple[NodeRecord, list[str]]] = []
    first_words: dict[str, int] = {}
    for record in index.records:
        name = record.name
        if not name:
            continue
        tokens = normalize_name(name).split()
        if not tokens:
            continue
        named.append((record, tokens))
        first_words[tokens[0]] = first_words.get(tokens[0], 0) + 1

    matches: list[dict[str, Any]] = []
    for record, tokens in named:
        full = " ".join(tokens)
        matched_on: str | None = None
        text = ""
        if len(full) >= 3 and present(tokens):
            matched_on, text = "name", full
        else:
            for size in range(len(tokens) - 1, 1, -1):
                if _specific(tokens[:size]) and present(tokens[:size]):
                    matched_on, text = "start_of_name", " ".join(tokens[:size])
                    break
        if matched_on is None:
            # Two or more consecutive words from inside the name: "iron housing".
            for size in range(len(tokens) - 1, 1, -1):
                for start in range(1, len(tokens) - size + 1):
                    part = tokens[start : start + size]
                    if _specific(part) and present(part):
                        matched_on, text = "part_of_name", " ".join(part)
                        break
                if matched_on is not None:
                    break
        if matched_on is None:
            first = tokens[0]
            if (
                len(first) >= 4
                and first.isalpha()
                and fold_word(first) not in _GENERIC_NAME_WORDS
                and first_words.get(first) == 1
                and present([first])
            ):
                matched_on, text = "first_word_of_name", first
        if matched_on is not None:
            matches.append({"record": record, "matched_on": matched_on, "text": text})
    matches.sort(key=lambda item: (-len(str(item["text"])), item["record"].entity_id))
    return matches


def link_single_words(
    words: Sequence[str],
    index: WorkspaceIndex,
    *,
    avoid_types: Iterable[str] = (),
    max_matches: int = MAX_SINGLE_WORD_MATCHES,
) -> list[dict[str, Any]]:
    """Records named by one word from inside their name, as a last resort.

    For words of a question that nothing else explained: "who supplies
    bearings?" names no record by any other rule, but one product is called
    "Ball Bearing 6205". A word counts when it could identify a record (see
    ``_specific``) and at most ``max_matches`` records carry it. When the
    question lists a kind of record (``avoid_types``), a record of another
    kind is preferred: the question asks about the bearings, not about the
    supplier called "Kyoto Bearings".
    """
    avoided = frozenset(avoid_types)
    by_word: dict[str, list[NodeRecord]] = {}
    for record in index.records:
        name = record.name
        if not name:
            continue
        for token in {fold_word(token) for token in normalize_name(name).split()}:
            by_word.setdefault(token, []).append(record)

    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for word in words:
        folded = fold_word(word)
        if len(folded) < 4 or not folded.isalpha() or not _specific([folded]):
            continue
        candidates = by_word.get(folded, [])
        preferred = [record for record in candidates if record.entity_type not in avoided]
        chosen = preferred or candidates
        if not chosen or len(chosen) > max_matches:
            continue
        for record in sorted(chosen, key=lambda item: (item.entity_type, item.entity_id)):
            key = (record.entity_type, record.entity_id)
            if key not in seen:
                seen.add(key)
                matches.append({"record": record, "matched_on": "word_in_name", "text": word})
    return matches


def match_value_filters(
    residual: str,
    records: Sequence[NodeRecord],
    *,
    exclude: Iterable[str] = (),
    short_codes: Iterable[str] = (),
    question: str = "",
) -> list[dict[str, Any]]:
    """Stored field values that the question spells out ("in transit", "tier 1").

    ``residual`` is the question without its topic and record-kind words. Values
    in ``exclude`` (already matched names and identifiers) are not used again. A
    value preceded by a negation ("not active", "not in DE") becomes an
    excluding filter. Values shorter than three characters are too easily
    ordinary words ("in", "us"); one is used only when the question wrote
    exactly that value in capitals (``short_codes``, e.g. the country code "DE").

    A country can be asked for by name while the file stores its code, or the
    other way round: with ``question`` (the text as typed), "Germany" and
    "German" select the stored value "DE" in a country column. Such a filter
    carries ``asked_as``, the words that named the country.
    """
    padded = f" {residual} "
    excluded = {normalize_name(value) for value in exclude}
    codes = frozenset(short_codes)
    checked: dict[tuple[str, str], dict[str, Any] | None] = {}
    for record in records:
        own_name = record.name
        for key, text in record.items():
            if text == record.entity_id or text == own_name:
                continue
            value = normalize_name(text)
            identity = (key, value)
            if identity in checked:
                continue
            checked[identity] = None
            if (
                (len(value) < 3 and text.strip() not in codes)
                or len(value) > MAX_FILTER_VALUE_LENGTH
                or not any(character.isalpha() for character in value)
                or value in _STOP_VALUES
                or value in excluded
            ):
                continue
            position = padded.find(f" {value} ")
            if position < 0:
                continue
            checked[identity] = {
                "field": key,
                "value": text,
                "negated": _negated(padded[: position + 1]),
            }

    # Countries: the question names one, a country column stores it another way.
    mentioned = dict(countries_mentioned(question)) if question else {}
    for code in codes:
        if country_name(code) and code not in mentioned:
            mentioned[code] = code
    if mentioned:
        inside_a_name = {
            code
            for code, words in mentioned.items()
            if any(f" {normalize_name(words)} " in f" {name} " for name in excluded)
        }
        country_fields: list[str] = []
        stored_codes: set[str] = set()
        for record in records:
            for key, text in record.items():
                if not is_country_field(key):
                    continue
                if key not in country_fields:
                    country_fields.append(key)
                stored = country_code(text)
                if stored is None:
                    continue
                stored_codes.add(stored)
                identity = (key, normalize_name(text))
                if checked.get(identity) is not None:
                    continue
                if stored not in mentioned or stored in inside_a_name:
                    continue
                words = mentioned[stored]
                position = padded.find(f" {normalize_name(words)} ")
                checked[identity] = {
                    "field": key,
                    "value": text,
                    "negated": position >= 0 and _negated(padded[: position + 1]),
                    "asked_as": words,
                    "means": country_name(stored),
                }
        # A country named in words that none of these records is in. The list
        # is then empty; leaving the filter out would answer "which suppliers
        # are in France?" with every supplier. Bare two-letter codes are not
        # used for this: "QA" and "IT" are too often something else.
        named = countries_mentioned(question) if question else {}
        for code, words in named.items():
            if code in stored_codes or code in inside_a_name or not country_fields:
                continue
            key = next(
                (name for name in country_fields if name.lower() == "country"), country_fields[0]
            )
            label = country_name(code) or words
            position = padded.find(f" {normalize_name(words)} ")
            checked[(key, normalize_name(label))] = {
                "field": key,
                "value": label,
                "negated": position >= 0 and _negated(padded[: position + 1]),
                "asked_as": words,
                "means": None,
                "absent": True,
            }
    return sorted(
        (item for item in checked.values() if item is not None),
        key=lambda item: (str(item["field"]), str(item["value"])),
    )


def apply_value_filters(
    records: Sequence[NodeRecord], filters: Sequence[Mapping[str, Any]]
) -> list[NodeRecord]:
    """Keep records that satisfy the filters: any listed value within one field, every field."""
    by_field: dict[str, list[Mapping[str, Any]]] = {}
    for item in filters:
        by_field.setdefault(str(item["field"]), []).append(item)
    kept: list[NodeRecord] = []
    for record in records:
        satisfied = True
        for key, wanted in by_field.items():
            found = record.value(key.lower())
            actual = normalize_name(found[1]) if found else None
            positives = [
                normalize_name(str(item["value"])) for item in wanted if not item["negated"]
            ]
            negatives = [normalize_name(str(item["value"])) for item in wanted if item["negated"]]
            if positives and actual not in positives:
                satisfied = False
            if negatives and actual in negatives:
                satisfied = False
            if not satisfied:
                break
        if satisfied:
            kept.append(record)
    return kept


def points_at(index: WorkspaceIndex, record: NodeRecord, target: NodeRecord) -> bool:
    """True when any pointer field of ``record`` names ``target``."""
    hints = REFERENCE_HINTS.get(target.entity_type, ())
    if record is target or not hints:
        return False
    for key, text in record.items():
        lowered = key.lower()
        if (
            any(hint in lowered for hint in hints)
            and index.lookup(target.entity_type, text) is target
        ):
            return True
    return False


def _pointed_at(index: WorkspaceIndex, record: NodeRecord, target_type: str) -> list[NodeRecord]:
    """Every record of ``target_type`` that a pointer field of ``record`` names."""
    hints = REFERENCE_HINTS.get(target_type, ())
    found: list[NodeRecord] = []
    if not hints or not index.by_type.get(target_type):
        return found
    for key, text in record.items():
        lowered = key.lower()
        if not any(hint in lowered for hint in hints):
            continue
        target = index.lookup(target_type, text)
        if target is not None and target is not record and target not in found:
            found.append(target)
    return found


_FLOW_ROLES: tuple[str, ...] = ("supplier", "customer", "product", "facility")


def related_records(
    index: WorkspaceIndex,
    today: date,
    entity_type: str,
    targets: Sequence[NodeRecord],
) -> dict[str, Any]:
    """Records of one kind that are linked to the records a question names.

    Three kinds of link are tried, and the first that finds anything is used:

    * ``refers_to``: the record itself names a target ("purchase orders from
      S-101": the order has a supplier field);
    * ``referred_by``: a target names the record ("which warehouse is PO-5001
      for?": the order has a warehouse field);
    * ``orders``: an order or shipment names both ("who supplies C-2004?": a
      supplier record never mentions a product, but purchase orders name the
      supplier and the product). Each record then carries how many such
      orders there are and how many of them are late.
    """
    candidates = index.by_type.get(entity_type, [])
    direct = [
        record
        for record in candidates
        if any(points_at(index, record, target) for target in targets)
    ]
    if direct:
        return {"via": "refers_to", "records": direct, "orders": {}}

    reverse: list[NodeRecord] = []
    for target in targets:
        for record in _pointed_at(index, target, entity_type):
            if record not in reverse:
                reverse.append(record)
    if reverse:
        reverse.sort(key=lambda item: item.entity_id)
        return {"via": "referred_by", "records": reverse, "orders": {}}

    keys = _focus_keys(targets)
    counts: dict[str, dict[str, int]] = {}
    for flow_record in index.of_types(FLOW_TYPES):
        if flow_record.entity_type == entity_type:
            continue
        flow = assess_flow(flow_record, index, today)
        if not _involves(flow, keys):
            continue
        for role in _FLOW_ROLES:
            ref = flow[role]
            if not ref or ref["entity_type"] != entity_type:
                continue
            if (str(ref["entity_type"]), str(ref["entity_id"])) in keys:
                continue
            row = counts.setdefault(
                str(ref["entity_id"]), {"order_count": 0, "late_order_count": 0}
            )
            row["order_count"] += 1
            if flow["late"]:
                row["late_order_count"] += 1
    through = [record for record in candidates if record.entity_id in counts]
    through.sort(key=lambda item: (-counts[item.entity_id]["order_count"], item.entity_id))
    return {"via": "orders" if through else "refers_to", "records": through, "orders": counts}


def open_flows(
    index: WorkspaceIndex, today: date, records: Sequence[NodeRecord]
) -> list[NodeRecord]:
    """The orders and shipments among ``records`` that have not arrived or been closed."""
    return [
        record
        for record in records
        if record.entity_type not in FLOW_TYPES or assess_flow(record, index, today)["open"]
    ]


# ── One figure over a list of records ───────────────────────────────────────

_NOT_A_MEASURE = re.compile(
    r"(?:^|_)(?:id|ids|no|number|num|code|sku|ref|key|zip|postcode|postal|phone|fax|year)$"
    r"|date|(?:^|_)(?:lat|lng|lon|latitude|longitude)(?:_|$)"
)
# Everyday words for a measure that a column name may not contain. They are
# tried in addition to the word itself, never instead of it.
_FIELD_SYNONYMS: dict[str, str] = {
    "qty": "quantity",
    "piece": "quantity",
    "pc": "quantity",
    "volume": "quantity",
    "cost": "price",
    "expensive": "price",
    "cheapest": "price",
    "costliest": "price",
}


def numeric_fields(records: Sequence[NodeRecord]) -> list[str]:
    """Stored names of the fields of these records that hold numbers.

    A field counts when at least four in five of its filled values read as
    numbers. Identifiers, codes and dates are not measures and are left out.
    """
    filled: dict[str, int] = {}
    numeric: dict[str, int] = {}
    for record in records:
        for key, text in record.items():
            if text == record.entity_id or _NOT_A_MEASURE.search(key.lower()):
                continue
            filled[key] = filled.get(key, 0) + 1
            if parse_number(text) is not None:
                numeric[key] = numeric.get(key, 0) + 1
    return [key for key, count in filled.items() if numeric.get(key, 0) * 5 >= count * 4]


def _field_words(field_name: str) -> list[str]:
    return [fold_word(word) for word in re.split(r"[^a-z0-9]+", field_name.lower()) if word]


def resolve_numeric_field(
    question_words: Sequence[str], records: Sequence[NodeRecord], *, allow_usual: bool = True
) -> str | None:
    """The numeric field a question asks about, or None when it names none clearly.

    A field is named by the words of its own name ("lead time" names
    ``lead_time_days``). The field that shares the most words wins; between
    two that share as many, the one whose whole name the question uses; a tie
    names neither. When the question uses no word of any field, the usual quantity
    of the records is used: the ordered quantity of orders and shipments, the
    quantity on hand of inventory records. ``allow_usual`` switches that off:
    a question that asks for something else by name ("total value") must not
    be answered with the quantity.
    """
    available = numeric_fields(records)
    if not available:
        return None
    asked = {fold_word(word) for word in question_words}
    asked |= {_FIELD_SYNONYMS[word] for word in asked if word in _FIELD_SYNONYMS}
    scored: list[tuple[int, int, int, str]] = []
    for key in available:
        words = _field_words(key)
        shared = {word for word in words if word in asked}
        # "on" and "time" are in half of all questions: a field is named by
        # a word that means something ("rate" for on_time_rate), and the
        # small words only decide between fields that share one. A name the
        # question spells out in full wins over one it only touches
        # ("quantity" over "quantity_on_hand").
        meaningful = {word for word in shared if len(word) >= 3 and word not in STOP_WORDS}
        if meaningful:
            in_full = int(len(shared) == len(set(words)))
            scored.append((len(meaningful), len(shared), in_full, key))
    if scored:
        scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        if len(scored) > 1 and scored[0][:3] == scored[1][:3]:
            return None
        return scored[0][3]

    if not allow_usual:
        return None
    kinds = {record.entity_type for record in records}
    lowered = {key.lower(): key for key in available}
    usual: tuple[str, ...] = ()
    if kinds and kinds <= set(FLOW_TYPES):
        usual = QUANTITY_FIELDS
    elif kinds and kinds <= set(INVENTORY_TYPES):
        usual = ON_HAND_FIELDS
    for name in usual:
        if name in lowered:
            return lowered[name]
    return None


def aggregate_records(
    index: WorkspaceIndex,
    records: Sequence[NodeRecord],
    field_name: str,
    operation: str,
) -> dict[str, Any]:
    """Sum, average, highest or lowest value of one numeric field over the records.

    Records whose value is missing or does not read as a number are counted
    and left out; nothing is assumed for them. A total over orders or stock
    is also broken down by product, because units of different parts add up
    to a number that means little on its own.
    """
    valued: list[tuple[NodeRecord, float]] = []
    for record in records:
        found = record.value(field_name.lower())
        number = parse_number(found[1]) if found else None
        if number is not None:
            valued.append((record, number))
    result: dict[str, Any] = {
        "operation": operation,
        "field": field_name,
        "considered": len(records),
        "with_value": len(valued),
        "without_value": len(records) - len(valued),
        "value": None,
        "lowest": None,
        "highest": None,
        "breakdown": None,
    }
    if not valued:
        return result
    numbers = [number for _record, number in valued]
    low, high = min(numbers), max(numbers)

    def holders(wanted: float) -> dict[str, Any]:
        records_with = [record.ref() for record, number in valued if number == wanted]
        return {
            "value": wanted,
            "records": records_with[:MAX_EXTREME_RECORDS],
            "record_count": len(records_with),
        }

    result["lowest"] = holders(low)
    result["highest"] = holders(high)
    if operation == AGGREGATE_SUM:
        result["value"] = math.fsum(numbers)
    elif operation == AGGREGATE_AVERAGE:
        result["value"] = math.fsum(numbers) / len(numbers)
    elif operation == AGGREGATE_MAX:
        result["value"] = high
    elif operation == AGGREGATE_MIN:
        result["value"] = low

    if operation == AGGREGATE_SUM:
        groups: dict[str, dict[str, Any]] = {}
        unassigned = 0
        for record, number in valued:
            product = (
                None if record.entity_type == "Product" else index.reference(record, "Product")
            )
            if product is None:
                unassigned += 1
                continue
            row = groups.setdefault(
                product.entity_id, {**product.ref(), "value": 0.0, "record_count": 0}
            )
            row["value"] += number
            row["record_count"] += 1
        if len(groups) > 1 and unassigned == 0:
            rows = sorted(
                groups.values(), key=lambda row: (-float(row["value"]), str(row["entity_id"]))
            )
            result["breakdown"] = {
                "by": "Product",
                "rows": rows[:MAX_BREAKDOWN_ROWS],
                "row_count": len(rows),
            }
    return result
