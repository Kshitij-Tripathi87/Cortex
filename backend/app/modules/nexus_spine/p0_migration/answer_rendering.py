"""Plain-language answers from tool evidence, without a model.

Used by the built-in assistant (no AI model configured). Every sentence is
assembled from values present in the evidence: identifiers, names, counts,
dates and quantities are copied, never estimated. Where the evidence cannot
support a statement, the text says what is missing instead.

Output is plain text for a UI that shows line breaks as written: short
paragraphs, and lists as lines starting with "- ". No JSON, no markup.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.modules.nexus_spine.p0_migration.workspace_facts import format_number

MAX_BULLETS = 8
MAX_INLINE_IDS = 8
MAX_FIELDS_PER_RECORD = 7
MAX_FIELD_CHANGES = 4

_KIND_NOUNS: dict[str, tuple[str, str]] = {
    "Supplier": ("supplier", "suppliers"),
    "Customer": ("customer", "customers"),
    "Carrier": ("carrier", "carriers"),
    "Facility": ("facility", "facilities"),
    "Product": ("product", "products"),
    "BOM": ("bill-of-materials line", "bill-of-materials lines"),
    "InventoryItem": ("inventory record", "inventory records"),
    "InventoryLot": ("inventory lot", "inventory lots"),
    "PurchaseOrder": ("purchase order", "purchase orders"),
    "SalesOrder": ("sales order", "sales orders"),
    "Shipment": ("shipment", "shipments"),
    "Route": ("route", "routes"),
    "Region": ("region", "regions"),
    "DemandRegion": ("demand region", "demand regions"),
    "Organization": ("organization", "organizations"),
}

_FLOW_KINDS: frozenset[str] = frozenset({"PurchaseOrder", "SalesOrder", "Shipment"})

_BATCH_STATE_ORDER: tuple[str, ...] = (
    "blocked",
    "review_required",
    "ready_to_publish",
    "nothing_accepted",
    "not_prepared",
    "published",
)

EXAMPLE_QUESTIONS: tuple[str, ...] = (
    "Which purchase orders are late?",
    "What is below safety stock?",
    "Which orders are exposed?",
    "What changed?",
    "Is my data ready?",
)


# ── Small wording helpers ────────────────────────────────────────────────────


def _noun(entity_type: str, count: int = 2) -> str:
    """Everyday name of a record kind, singular for 1 and plural otherwise."""
    known = _KIND_NOUNS.get(entity_type)
    if known:
        return known[0] if count == 1 else known[1]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", entity_type).lower() or "record"
    return words if count == 1 else f"{words}s"


def _counted(count: int, entity_type: str) -> str:
    return f"{format_number(count)} {_noun(entity_type, count)}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{format_number(count)} {singular if count == 1 else (plural or singular + 's')}"


def _join(items: Sequence[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _listed(items: Sequence[str], total: int | None = None, limit: int = MAX_INLINE_IDS) -> str:
    """Inline list that says how many more there are when it is cut."""
    total = len(items) if total is None else total
    shown = list(items[:limit])
    remaining = total - len(shown)
    if remaining > 0:
        return f"{', '.join(shown)} and {format_number(remaining)} more"
    return _join(shown)


def _num(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return format_number(float(value))


def _label(ref: Mapping[str, Any] | None) -> str:
    """'S-101 Bharat Castings Pvt Ltd', or just the identifier when unnamed."""
    if not ref:
        return ""
    entity_id = str(ref.get("entity_id") or "")
    name = ref.get("name")
    return f"{entity_id} {name}" if name and str(name) != entity_id else entity_id


def _field(name: Any) -> str:
    return str(name).replace("_", " ")


def _is_are(count: int) -> str:
    return "is" if count == 1 else "are"


def _as_of(value: Any) -> str:
    return f"as of {value} (UTC)"


def _day(value: Any) -> str:
    """Date part of an ISO timestamp, with the time when it is present."""
    text = str(value or "")
    match = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", text)
    return f"{match.group(1)} {match.group(2)} UTC" if match else text[:10]


def _bullets(lines: Sequence[str], total: int | None = None, limit: int = MAX_BULLETS) -> list[str]:
    """Bullet lines, with a closing line when more exist than are shown."""
    total = len(lines) if total is None else total
    shown = [f"- {line}" for line in lines[:limit]]
    remaining = total - len(shown)
    if remaining > 0:
        shown.append(f"- and {format_number(remaining)} more.")
    return shown


def _dict(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


# ── Records, orders and stock ────────────────────────────────────────────────


def _assessed_phrase(count: int, assessed: Mapping[str, Any]) -> str:
    """'4 of 7 purchase orders' / '4 of 19 orders and shipments'."""
    kinds = [str(kind) for kind, number in assessed.items() if number]
    total = sum(int(number) for number in assessed.values())
    if len(kinds) == 1:
        noun = _noun(kinds[0], total)
    elif kinds and all(kind.endswith("Order") for kind in kinds):
        noun = "orders"
    else:
        noun = "orders and shipments"
    if count == 0:
        return f"None of the {format_number(total)} {noun}" if total != 1 else f"The 1 {noun}"
    return f"{format_number(count)} of {format_number(total)} {noun}"


def _flow_subject(flow: Mapping[str, Any]) -> str:
    """'400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd'."""
    parts: list[str] = []
    product = _label(_dict(flow.get("product")))
    quantity = flow.get("quantity")
    if product and quantity is not None:
        parts.append(f"{_num(quantity)} x {product}")
    elif product:
        parts.append(product)
    elif quantity is not None:
        parts.append(f"{_num(quantity)} units")
    supplier = _label(_dict(flow.get("supplier")))
    if supplier:
        parts.append(f"from {supplier}")
    customer = _label(_dict(flow.get("customer")))
    if customer:
        parts.append(f"for {customer}")
    return " ".join(parts)


def _flow_line(flow: Mapping[str, Any]) -> str:
    subject = _flow_subject(flow)
    reasons = "; ".join(str(reason) for reason in _list(flow.get("reasons")))
    head = str(flow.get("entity_id"))
    if subject:
        head = f"{head}: {subject}"
    return f"{head}; {reasons}." if reasons else f"{head}."


def _stock_phrase(position: Mapping[str, Any], *, known: str = "") -> str:
    """Stock position in words.

    'C-2000 Cast Iron Housing at WH-PUNE: 120 on hand against a safety stock of
    300 (180 short)'. ``known`` names what the reader already knows and is left
    out: "product" gives '120 on hand at WH-PUNE against ...', "facility" gives
    'C-2000 Cast Iron Housing: 120 on hand against ...'.
    """
    product = _label(_dict(position.get("product")))
    facility = _label(_dict(position.get("facility")))
    on_hand = f"{_num(position.get('on_hand'))} on hand"
    if known == "product":
        text = (
            f"{on_hand} at {facility}" if facility else f"{on_hand} ({position.get('entity_id')})"
        )
    elif known == "facility":
        text = f"{product or position.get('entity_id')}: {on_hand}"
    else:
        where = f"{product} at {facility}" if product and facility else product or facility
        text = f"{where or position.get('entity_id')}: {on_hand}"
    threshold = position.get("threshold")
    if threshold is None:
        return f"{text}, with no safety-stock or reorder field to judge it against"
    text += (
        f" against a {_field(position.get('threshold_field') or 'threshold')} of {_num(threshold)}"
    )
    shortfall = position.get("shortfall")
    if shortfall:
        text += f" ({_num(shortfall)} short)"
    return text


def _stock_compact(position: Mapping[str, Any]) -> str:
    """'C-2000 at WH-PUNE (120 on hand, safety stock 300)'."""
    product = str(_dict(position.get("product")).get("entity_id") or "")
    facility = str(_dict(position.get("facility")).get("entity_id") or "")
    where = f"{product} at {facility}" if product and facility else product or facility
    text = f"{where or position.get('entity_id')} ({_num(position.get('on_hand'))} on hand"
    if position.get("threshold") is not None:
        text += (
            f", {_field(position.get('threshold_field') or 'threshold')} "
            f"{_num(position.get('threshold'))}"
        )
    return f"{text})"


def _supply_phrase(item: Mapping[str, Any]) -> str:
    """'PO-5004 (200 units, due 2026-12-01)'."""
    details: list[str] = []
    if item.get("quantity") is not None:
        details.append(f"{_num(item.get('quantity'))} units")
    if item.get("due"):
        details.append(f"due {item.get('due')}")
    text = str(item.get("entity_id"))
    return f"{text} ({', '.join(details)})" if details else text


def _record_fields(record: Mapping[str, Any], limit: int = MAX_FIELDS_PER_RECORD) -> str:
    """'country: DE; tier: tier_1; ...' without repeating the identifier or the name."""
    entity_id = str(record.get("entity_id") or "")
    name = record.get("name")
    pairs: list[str] = []
    attributes = _dict(record.get("attributes"))
    skipped = 0
    for key, value in attributes.items():
        if str(value) == entity_id or (name and str(value) == str(name)):
            continue
        if len(pairs) >= limit:
            skipped += 1
            continue
        pairs.append(f"{key}: {value}")
    text = "; ".join(pairs)
    if skipped:
        text += f"; and {skipped} more {'field' if skipped == 1 else 'fields'}"
    return text


def _record_line(record: Mapping[str, Any]) -> str:
    fields = _record_fields(record)
    label = _label(record)
    return f"{label}: {fields}" if fields else label


def _filter_phrase(filters: Sequence[Mapping[str, Any]]) -> str:
    parts = [
        f"{item['field']} other than {item['value']}"
        if item.get("negated")
        else f"{item['field']} = {item['value']}"
        for item in filters
    ]
    return _join(parts)


# ── Workspace answers, one per kind of result ────────────────────────────────


def _holds(workspace: Mapping[str, Any]) -> str:
    """'6 suppliers, 7 products and 2 facilities'."""
    counts = _dict(workspace.get("entity_counts"))
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
    return _join([_counted(int(count), str(kind)) for kind, count in ordered])


def _source_line(workspace: Mapping[str, Any]) -> str:
    version = workspace.get("world_state_version")
    if not version:
        return ""
    files: list[str] = []
    for source in _list(workspace.get("sources")):
        for name in _list(_dict(source).get("files")):
            if name not in files:
                files.append(str(name))
    if not files:
        return f"Source: your published data, version {version}."
    return f"Source: your published data, version {version} ({_listed(files, limit=6)})."


def _attention_lines(attention: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    assessed = _dict(attention.get("flows_assessed"))
    late_count = int(attention.get("late_count") or 0)
    if not assessed:
        lines.append("No orders or shipments are published, so lateness cannot be judged.")
    elif late_count:
        ids: list[str] = []
        for group in _dict(attention.get("late_by_type")).values():
            ids.extend(str(item) for item in _list(_dict(group).get("examples")))
        lines.append(
            f"{_assessed_phrase(late_count, assessed)} {_is_are(late_count)} late or flagged: "
            f"{_listed(ids, late_count)}."
        )
    else:
        lines.append(f"{_assessed_phrase(0, assessed)} is late or flagged.")

    stock_assessed = int(attention.get("stock_assessed") or 0)
    short_count = int(attention.get("stock_short_count") or 0)
    if not stock_assessed:
        lines.append(
            "No inventory with a readable quantity is published, so stock cannot be judged."
        )
    elif short_count:
        phrases = [_stock_compact(_dict(item)) for item in _list(attention.get("stock_short"))]
        lines.append(
            f"{format_number(short_count)} of {_plural(stock_assessed, 'stock position')} "
            f"{_is_are(short_count)} below threshold: {_listed(phrases, short_count, 4)}."
        )
    else:
        lines.append(
            f"None of the {_plural(stock_assessed, 'stock position')} is below its threshold."
        )

    flagged = [_dict(item) for item in _list(attention.get("flagged"))]
    flagged_count = int(attention.get("flagged_count") or 0)
    if flagged_count:
        phrases = [f"{_label(item)} ({item.get('status')})" for item in flagged]
        lines.append(
            f"{_plural(flagged_count, 'supplier or partner', 'suppliers or partners')} "
            f"{_is_are(flagged_count)} flagged by their own status: {_listed(phrases, flagged_count)}."
        )
    return lines


def _batch_line(batch: Mapping[str, Any]) -> str:
    files = [_dict(item) for item in _list(batch.get("files"))]
    names = []
    for item in files:
        rows = item.get("rows")
        names.append(
            f"{item.get('name')} ({_plural(int(rows), 'row')})" if rows else str(item.get("name"))
        )
    title = _join(names) or f"upload {str(batch.get('batch_id'))[:8]}"
    state = batch.get("state")
    pending = int(batch.get("claims_pending_review") or 0)
    accepted = int(batch.get("claims_accepted") or 0)
    conflicts = int(batch.get("open_conflicts") or 0)
    blocking = int(batch.get("blocking_conflicts") or 0)
    if state == "published":
        return f"{title}: published as version {batch.get('published_version')}."
    if state == "not_prepared":
        return f"{title}: uploaded, not prepared for review yet."
    if state == "blocked":
        return f"{title}: blocked by {_plural(blocking, 'conflict')} that must be resolved first."
    if state == "review_required":
        waiting = []
        if pending:
            waiting.append(f"{_plural(pending, 'claim')} waiting for review")
        if conflicts:
            waiting.append(f"{_plural(conflicts, 'open conflict')}")
        return f"{title}: {_join(waiting)}."
    if state == "nothing_accepted":
        return f"{title}: reviewed, but no claim was accepted, so there is nothing to publish."
    return f"{title}: ready to publish ({_plural(accepted, 'claim')} accepted)."


def _intake_lines(intake: Mapping[str, Any], *, only_open: bool = False) -> list[str]:
    batches = [_dict(item) for item in _list(intake.get("batches"))]
    batches.sort(
        key=lambda item: (
            _BATCH_STATE_ORDER.index(str(item.get("state")))
            if str(item.get("state")) in _BATCH_STATE_ORDER
            else len(_BATCH_STATE_ORDER)
        )
    )
    if only_open:
        batches = [item for item in batches if item.get("state") != "published"]
    return [_batch_line(item) for item in batches]


def _render_intake(result: Mapping[str, Any]) -> list[str]:
    total = int(result.get("batch_count") or 0)
    if not total:
        return [
            "Nothing has been uploaded to this workspace yet. Upload a file on the Upload page to start."
        ]
    by_state = _dict(result.get("by_state"))
    listed = int(result.get("batches_listed") or 0)
    published = int(by_state.get("published") or 0)
    open_count = listed - published
    lines: list[str]
    if open_count == 0:
        lead = (
            "Your upload is published."
            if listed == 1
            else f"All {format_number(listed)} uploads are published."
        )
        lines = [lead, *_bullets(_intake_lines(result), limit=10)]
    else:
        lines = [
            f"{format_number(open_count)} of {_plural(listed, 'upload')} "
            f"{_is_are(open_count)} not published yet:",
            *_bullets(_intake_lines(result, only_open=True), limit=10),
        ]
        if published:
            lines.append(f"The other {format_number(published)} {_is_are(published)} published.")
    if total > listed:
        lines.append(
            f"This covers the {format_number(listed)} most recent of {format_number(total)} uploads."
        )
    return lines


def _render_overview(evidence: Mapping[str, Any]) -> list[str]:
    workspace = _dict(evidence.get("workspace"))
    counts = _dict(workspace.get("entity_counts"))
    total = sum(int(value) for value in counts.values())
    relationships = sum(
        int(value) for value in _dict(workspace.get("relationship_counts")).values()
    )
    lines = [
        f"Your workspace holds {_plural(total, 'published record')}: {_holds(workspace)}, "
        f"joined by {_plural(relationships, 'relationship')}."
    ]
    attention = _dict(evidence.get("attention"))
    if attention:
        lines.append("")
        lines.append(f"What stands out {_as_of(attention.get('as_of'))}:")
        lines.extend(_bullets(_attention_lines(attention)))
    intake = _dict(_dict(evidence.get("result")).get("intake"))
    open_lines = _intake_lines(intake, only_open=True) if intake else []
    if open_lines:
        lines.append("")
        lines.append(f"{_plural(len(open_lines), 'upload')} not published yet:")
        lines.extend(_bullets(open_lines, limit=5))
    return lines


def _supplier_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        orders = int(row.get("order_count") or 0)
        late = int(row.get("late_order_count") or 0)
        flag = _dict(row.get("flag"))
        parts: list[str] = []
        if late:
            ids = [str(item) for item in _list(row.get("late_orders"))]
            parts.append(
                f"{format_number(late)} of {_plural(orders, 'order')} late ({_listed(ids, late)})"
            )
        elif orders:
            parts.append(f"none of its {_plural(orders, 'order')} is late")
        else:
            parts.append("no orders published for it")
        if flag:
            parts.append(f"its own {flag.get('status_field')} is {flag.get('status')}")
        lines.append(f"{_label(row)}: {'; '.join(parts)}.")
    return lines


def _render_late(evidence: Mapping[str, Any], *, brief: bool) -> list[str]:
    result = _dict(evidence.get("result"))
    focus = _dict(evidence.get("question_focus"))
    assessed = _dict(result.get("assessed"))
    late = [_dict(item) for item in _list(result.get("late"))]
    late_count = int(result.get("late_count") or 0)
    matched = [_dict(item) for item in _list(focus.get("matched"))]
    matched_ids = {str(item.get("entity_id")) for item in matched}
    about = f" linked to {_join([_label(item) for item in matched[:3]])}" if matched else ""
    as_of = _as_of(result.get("as_of"))
    lines: list[str] = []

    suppliers = [_dict(item) for item in _list(result.get("suppliers"))]
    # A supplier the question names is covered by its orders below; the
    # supplier list is for questions about suppliers in general.
    named_suppliers = [row for row in suppliers if str(row.get("entity_id")) in matched_ids]
    if suppliers and not named_suppliers:
        lines.append(
            f"{_plural(len(suppliers), 'supplier')} "
            f"{'has' if len(suppliers) == 1 else 'have'} late orders or a warning status {as_of}:"
        )
        lines.extend(_bullets(_supplier_lines(suppliers)))
        lines.append("")

    if not assessed:
        lines.append(
            f"I found no orders or shipments{about} in your published data, so I cannot tell "
            "what is late. Publish purchase orders, sales orders or shipments to answer this."
        )
        return lines

    named_flows = [item for item in matched if item.get("entity_type") in _FLOW_KINDS]
    if named_flows and len(named_flows) == len(matched):
        # The question names the orders themselves: answer for each one.
        by_id = {str(flow.get("entity_id")): flow for flow in late}
        for item in named_flows:
            flow = by_id.get(str(item.get("entity_id")))
            if flow:
                subject = _flow_subject(flow)
                reasons = "; ".join(str(reason) for reason in _list(flow.get("reasons")))
                lines.append(
                    f"{item.get('entity_id')} is late or flagged {as_of}: "
                    f"{reasons}. It is for {subject}."
                    if subject
                    else f"{item.get('entity_id')} is late or flagged {as_of}: {reasons}."
                )
            else:
                lines.append(f"{item.get('entity_id')} is not late or flagged {as_of}.")
    elif late_count:
        lines.append(
            f"{_assessed_phrase(late_count, assessed)}{about} {_is_are(late_count)} late or "
            f"flagged {as_of}:"
        )
        lines.extend(_bullets([_flow_line(flow) for flow in late], late_count))
    else:
        lines.append(f"{_assessed_phrase(0, assessed)}{about} is late or flagged {as_of}.")
        lines.append(
            "An order counts as late when its status says so, when its expected date is after "
            "its promised date, or when its promised date has passed and it is not marked delivered."
        )
    for row in named_suppliers:
        flag = _dict(row.get("flag"))
        if flag:
            lines.append(
                f"{_label(row)}'s own {flag.get('status_field')} field says {flag.get('status')}."
            )

    delivered = int(result.get("delivered_late_count") or 0)
    if delivered:
        ids = [str(_dict(item).get("entity_id")) for item in _list(result.get("delivered_late"))]
        lines.append(
            f"{format_number(delivered)} more arrived late and {_is_are(delivered)} closed: "
            f"{_listed(ids, delivered)}."
        )
    unreadable = int(result.get("unreadable_date_count") or 0)
    if unreadable:
        lines.append(
            f"{_plural(unreadable, 'record')} {'has a date' if unreadable == 1 else 'have dates'} "
            "I could not read (I read dates written as YYYY-MM-DD), so lateness there rests on "
            "the status field alone."
        )

    exposure = _dict(result.get("exposure"))
    parts = [_dict(item) for item in _list(exposure.get("parts_at_risk"))]
    if brief and parts:
        lines.append("")
        lines.extend(_decision_brief(exposure))
    elif parts and late_count:
        part_count = int(exposure.get("parts_at_risk_count") or len(parts))
        short = [
            _label(_dict(part.get("product")))
            for part in parts
            if part.get("stock_state") == "below_threshold"
        ]
        note = (
            f"{'This delay affects' if late_count == 1 else 'These delays affect'} "
            f"{_plural(part_count, 'part')}"
        )
        if short:
            note += f"; {_listed(short, limit=4)} {_is_are(len(short))} already below threshold"
        lines.append("")
        lines.append(f'{note}. Ask "which orders are exposed?" for the full trace.')
    return lines


def _render_stock(evidence: Mapping[str, Any]) -> list[str]:
    result = _dict(evidence.get("result"))
    assessed = int(result.get("assessed") or 0)
    short_count = int(result.get("short_count") or 0)
    without_quantity = int(result.get("without_quantity") or 0)
    without_threshold = int(result.get("without_threshold") or 0)
    lines: list[str] = []
    if not assessed and not without_quantity:
        return [
            "No inventory is published in this workspace, so I cannot judge stock. Publish an "
            "inventory file with on-hand and safety-stock columns to answer this."
        ]
    if short_count:
        lines.append(
            f"{format_number(short_count)} of {_plural(assessed, 'stock position')} "
            f"{_is_are(short_count)} below threshold or empty:"
        )
        phrases = [f"{_stock_phrase(_dict(item))}." for item in _list(result.get("short"))]
        lines.extend(_bullets(phrases, short_count))
    elif assessed:
        lines.append(f"None of the {_plural(assessed, 'stock position')} is below its threshold.")
    if without_threshold:
        lines.append(
            f"{_plural(without_threshold, 'position')} {'has' if without_threshold == 1 else 'have'} "
            "no safety-stock or reorder field, so I could not judge "
            f"{'it' if without_threshold == 1 else 'them'}."
        )
    if without_quantity:
        lines.append(
            f"{_plural(without_quantity, 'inventory record')} "
            f"{'has' if without_quantity == 1 else 'have'} no readable on-hand quantity."
        )
    return lines


def _part_stock_sentence(part: Mapping[str, Any]) -> str:
    stock = [_dict(item) for item in _list(part.get("stock"))]
    state = part.get("stock_state")
    if state == "no_inventory_record" or not stock:
        return "No inventory record is published for it, so its cover is unknown."
    phrases = [_stock_phrase(item, known="product") for item in stock]
    total = int(part.get("stock_position_count") or len(stock))
    listed = _listed(phrases, total, 3)
    if state == "below_threshold":
        return f"Stock is already below threshold: {listed}."
    if state == "above_threshold":
        return f"Stock is above threshold: {listed}."
    return f"Stock: {listed}."


def _part_line(part: Mapping[str, Any]) -> str:
    product = _label(_dict(part.get("product")))
    orders = [str(item) for item in _list(part.get("late_orders"))]
    order_count = int(part.get("late_order_count") or len(orders))
    suppliers = [_label(_dict(item)) for item in _list(part.get("suppliers"))]
    quantity = part.get("late_quantity")
    head = f"{_num(quantity)} units late" if quantity is not None else "late"
    text = f"{product}: {head} on {_listed(orders, order_count, 4)}"
    if suppliers:
        text += f" from {_join(suppliers[:3])}"
    text += f". {_part_stock_sentence(part)}"
    goes_into = [_label(_dict(item)) for item in _list(part.get("goes_into"))]
    if goes_into:
        text += f" It goes into {_listed(goes_into, limit=4)}."
    customer_orders = int(part.get("customer_order_count") or 0)
    if customer_orders:
        text += f" {_plural(customer_orders, 'open customer order')} {'needs' if customer_orders == 1 else 'need'} it."
    return text


def _gap_lines(gaps: Sequence[Any], *, has_customer_orders: bool) -> list[str]:
    lines: list[str] = []
    if "no_sales_orders" in gaps:
        lines.append(
            "No sales orders are published, so I cannot trace these delays to customer deliveries."
        )
    elif "no_bill_of_materials" in gaps:
        lines.append(
            "No bill of materials is published, so customer orders are matched only when they "
            "are for the late part itself, not for a product that contains it."
        )
    if "no_inventory" in gaps:
        lines.append("No inventory is published, so stock cover for these parts is unknown.")
    if not lines and not has_customer_orders:
        lines.append("No open customer order in your published data needs these parts.")
    return lines


def _customer_order_line(order: Mapping[str, Any]) -> str:
    product = _label(_dict(order.get("product")))
    quantity = order.get("quantity")
    what = f"{_num(quantity)} x {product}" if quantity is not None and product else product
    text = str(order.get("entity_id"))
    customer = _label(_dict(order.get("customer")))
    if customer:
        text += f" for {customer}"
    if what:
        text += f": {what}"
    if order.get("promised_date"):
        text += f", promised {order.get('promised_date')}"
    part = _label(_dict(order.get("needs_part")))
    if order.get("through_product") and part:
        text += f" (contains {part})"
    return f"{text}."


def _render_exposure(evidence: Mapping[str, Any], *, brief: bool) -> list[str]:
    result = _dict(evidence.get("result"))
    focus = _dict(evidence.get("question_focus"))
    matched = [_dict(item) for item in _list(focus.get("matched"))]
    about = f" linked to {_join([_label(item) for item in matched[:3]])}" if matched else ""
    late_supply = int(result.get("late_supply_count") or 0)
    parts = [_dict(item) for item in _list(result.get("parts_at_risk"))]
    part_count = int(result.get("parts_at_risk_count") or len(parts))
    lines: list[str] = []

    suppliers = [_dict(item) for item in _list(result.get("suppliers"))]
    if suppliers:
        lines.append(
            f"{_plural(len(suppliers), 'supplier')} "
            f"{'has' if len(suppliers) == 1 else 'have'} late orders or a warning status:"
        )
        lines.extend(_bullets(_supplier_lines(suppliers)))
        lines.append("")

    late_customer = int(result.get("late_customer_flow_count") or 0)
    if not late_supply and not late_customer:
        lines.append(
            f"No order or shipment{about} in your published data is late or flagged "
            f"{_as_of(result.get('as_of'))}, so no delay is putting orders at risk."
        )
        attention = _dict(evidence.get("attention"))
        short = int(attention.get("stock_short_count") or 0)
        if short:
            lines.append(
                f"Separately, {_plural(short, 'stock position')} {_is_are(short)} below threshold. "
                'Ask "what is below safety stock?" for the list.'
            )
        return lines

    if late_supply:
        lines.append(
            f"{_plural(late_supply, 'late or flagged supply order')}{about} "
            f"{'affects' if late_supply == 1 else 'affect'} {_plural(part_count, 'part')} "
            f"{_as_of(result.get('as_of'))}:"
        )
        lines.extend(_bullets([_part_line(part) for part in parts], part_count))
        unlinked = [str(item) for item in _list(result.get("late_supply_without_product"))]
        if unlinked:
            lines.append(
                f"{_listed(unlinked)} {'names' if len(unlinked) == 1 else 'name'} no published "
                "product, so I could not trace "
                f"{'it' if len(unlinked) == 1 else 'them'} further."
            )

    customer_orders = [_dict(item) for item in _list(result.get("customer_orders"))]
    customer_count = int(result.get("customer_order_count") or 0)
    if customer_count:
        lines.append("")
        lines.append(
            f"{_plural(customer_count, 'open customer order')} "
            f"{'depends' if customer_count == 1 else 'depend'} on these parts:"
        )
        lines.extend(
            _bullets([_customer_order_line(order) for order in customer_orders], customer_count)
        )
    if late_customer:
        flows = [_dict(item) for item in _list(result.get("late_customer_flows"))]
        lines.append("")
        lines.append(
            f"{_plural(late_customer, 'customer order or shipment', 'customer orders or shipments')} "
            f"{_is_are(late_customer)} late or flagged:"
        )
        lines.extend(_bullets([_flow_line(flow) for flow in flows], late_customer))
    if late_supply:
        gap_lines = _gap_lines(_list(result.get("gaps")), has_customer_orders=bool(customer_count))
        if gap_lines:
            lines.append("")
            lines.extend(gap_lines)
    if brief and parts:
        lines.append("")
        lines.extend(_decision_brief(result, include_parts=False))
    return lines


def _decision_brief(exposure: Mapping[str, Any], *, include_parts: bool = True) -> list[str]:
    """Facts that bear on what to do about late supply. States options the data
    shows (cover on hand, on-time orders, other suppliers on record) and never
    picks one."""
    parts = [_dict(item) for item in _list(exposure.get("parts_at_risk"))]
    part_count = int(exposure.get("parts_at_risk_count") or len(parts))
    lines: list[str] = []
    if include_parts:
        lines.append(f"What that puts at risk ({_plural(part_count, 'part')}):")
        lines.extend(_bullets([_part_line(part) for part in parts], part_count))
        lines.append("")
    lines.append("What your data shows about the options:")
    option_lines: list[str] = []
    for part in parts[:MAX_BULLETS]:
        product = _label(_dict(part.get("product")))
        facts: list[str] = []
        on_time = [_dict(item) for item in _list(part.get("on_time_supply"))]
        on_time_count = int(part.get("on_time_supply_count") or len(on_time))
        if on_time_count:
            described = [_supply_phrase(item) for item in on_time]
            facts.append(
                f"{_plural(on_time_count, 'other open order')} for it "
                f"{_is_are(on_time_count)} on time: {_listed(described, on_time_count, 3)}"
            )
        else:
            facts.append("no other open order for it is on time")
        others = [_dict(item) for item in _list(part.get("other_suppliers"))]
        other_count = int(part.get("other_supplier_count") or len(others))
        if other_count:
            described = [
                f"{_label(item)} ({_plural(int(item.get('order_count') or 0), 'order')}, "
                f"{format_number(int(item.get('late_order_count') or 0))} late)"
                for item in others
            ]
            facts.append(
                f"{_plural(other_count, 'other supplier')} "
                f"{'appears' if other_count == 1 else 'appear'} on your orders for it: "
                f"{_listed(described, other_count, 3)}"
            )
        else:
            facts.append("no other supplier appears on your published orders for it")
        spare = [
            _dict(item)
            for item in _list(part.get("stock"))
            if not _dict(item).get("below_threshold")
            and _dict(item).get("threshold") is not None
            and float(_dict(item).get("on_hand") or 0) > float(_dict(item).get("threshold") or 0)
        ]
        if spare:
            described = [
                f"{_label(_dict(item.get('facility'))) or item.get('entity_id')} holds "
                f"{_num(item.get('on_hand'))} against a "
                f"{_field(item.get('threshold_field') or 'threshold')} of {_num(item.get('threshold'))}"
                for item in spare
            ]
            facts.append(f"stock above threshold: {_listed(described, limit=3)}")
        option_lines.append(f"{product}: {'; '.join(facts)}.")
    lines.extend(_bullets(option_lines, part_count))
    lines.append("")
    lines.append(
        "These are facts from your published data. They do not show whether another supplier "
        "has capacity or what a change would cost, and this built-in assistant does not choose "
        "an action for you."
    )
    return lines


def _render_changes(evidence: Mapping[str, Any]) -> list[str]:
    result = _dict(evidence.get("result"))
    focus = _dict(evidence.get("question_focus"))
    latest = _dict(result.get("latest"))
    if not latest:
        return ["Nothing has been published yet, so there are no changes to report."]
    files = [str(item) for item in _list(latest.get("files"))]
    origin = f", from {_join(files)}" if files else ""
    when = f" (published {_day(latest.get('sealed_at'))})" if latest.get("sealed_at") else ""
    lines = [f"The latest publish is version {latest.get('version')}{origin}{when}."]

    added = _dict(latest.get("added"))
    wanted = [str(kind) for kind in _list(focus.get("entity_types"))]
    if wanted:
        named = [kind for kind in wanted if kind in added]
        if named:
            for kind in named:
                group = _dict(added.get(kind))
                count = int(group.get("count") or 0)
                ids = [str(item) for item in _list(group.get("examples"))]
                lines.append(f"It added {_counted(count, kind)}: {_listed(ids, count)}.")
        else:
            lines.append(f"It added no {_join([_noun(kind) for kind in wanted[:3]])}.")

    bullets: list[str] = []
    for kind, group in added.items():
        if wanted and kind in wanted:
            continue
        count = int(_dict(group).get("count") or 0)
        ids = [str(item) for item in _list(_dict(group).get("examples"))]
        bullets.append(f"Added {_counted(count, str(kind))}: {_listed(ids, count)}.")
    relationships = int(latest.get("relationships_added_count") or 0)
    if relationships:
        bullets.append(f"Added {_plural(relationships, 'relationship')} between records.")
    updated = [_dict(item) for item in _list(latest.get("updated"))]
    updated_count = int(latest.get("updated_count") or 0)
    if updated_count:
        bullets.append(f"Changed {_plural(updated_count, 'existing record')}:")
    lines.extend(_bullets(bullets, limit=12))
    for item in updated[:MAX_BULLETS]:
        changes = [_dict(change) for change in _list(item.get("changes"))]
        described = [
            f"{change.get('field')} {change.get('before') or '(empty)'} -> {change.get('after')}"
            for change in changes[:MAX_FIELD_CHANGES]
        ]
        extra = len(changes) - len(described)
        if extra > 0:
            described.append(f"{extra} more {'field' if extra == 1 else 'fields'}")
        lines.append(f"  - {_label(item)}: {'; '.join(described)}.")
    if updated_count > len(updated[:MAX_BULLETS]):
        lines.append(f"  - and {format_number(updated_count - len(updated[:MAX_BULLETS]))} more.")

    completed = [_dict(item) for item in _list(latest.get("completed"))]
    completed_count = int(latest.get("completed_count") or 0)
    if completed_count:
        lines.append(
            f"- Filled in {_plural(completed_count, 'record')} that earlier files only referred "
            f"to: {_listed([_label(item) for item in completed], completed_count)}."
        )
    placeholders = [_dict(item) for item in _list(latest.get("placeholders"))]
    placeholder_count = int(latest.get("placeholder_count") or 0)
    if placeholder_count:
        described = [
            f"{_noun(str(item.get('entity_type')), 1)} {item.get('entity_id')}"
            for item in placeholders
        ]
        lines.append(
            f"- It refers to {_plural(placeholder_count, 'record')} that no published file "
            f"describes yet: {_listed(described, placeholder_count)}."
        )
    unchanged = int(latest.get("resubmitted_unchanged_count") or 0)
    if unchanged:
        lines.append(
            f"- {_plural(unchanged, 'record')} {'was' if unchanged == 1 else 'were'} resubmitted with no change."
        )
    if not (
        added or relationships or updated_count or completed_count or placeholder_count or unchanged
    ):
        lines.append("It did not add or change any record.")
    if latest.get("truncated"):
        lines.append("This publish is large; the list of changed records above is partial.")

    history = [_dict(item) for item in _list(result.get("history"))]
    if history:
        lines.append("")
        lines.append("Earlier versions:")
        earlier = [
            f"Version {item.get('version')}: {_join([str(name) for name in _list(item.get('files'))]) or 'source not recorded'}"
            f" ({_day(item.get('sealed_at'))[:10]}), touched {_plural(int(item.get('records_written') or 0), 'record')}."
            for item in history
        ]
        lines.extend(_bullets(earlier, limit=4))
    return lines


def _render_entity_list(evidence: Mapping[str, Any]) -> list[str]:
    result = _dict(evidence.get("result"))
    focus = _dict(evidence.get("question_focus"))
    filters = [_dict(item) for item in _list(focus.get("filters"))]
    related = [_dict(item) for item in _list(result.get("related_to"))]
    lines: list[str] = []
    for group in [_dict(item) for item in _list(result.get("groups"))]:
        kind = str(group.get("entity_type"))
        total = int(group.get("published_total") or 0)
        matched = int(group.get("matched") or 0)
        records = [_dict(item) for item in _list(group.get("records"))]
        # "1 of 7 ... refers to / matches", otherwise "refer to / match".
        refer, match = ("refers", "matches") if matched == 1 else ("refer", "match")
        if related:
            condition = f"{refer} to {_join([_label(item) for item in related[:3]])}"
            if filters:
                condition += f" and {match} {_filter_phrase(filters)}"
        elif filters:
            condition = f"{match} {_filter_phrase(filters)}"
        else:
            condition = ""
        if lines:
            lines.append("")
        if condition:
            if matched:
                lines.append(f"{format_number(matched)} of {_counted(total, kind)} {condition}:")
            else:
                lines.append(f"None of the {_counted(total, kind)} {condition}.")
        elif matched:
            lines.append(f"You have {_counted(matched, kind)}:")
        else:
            lines.append(f"There are no {_noun(kind)} in your published data.")
        lines.extend(_bullets([_record_line(record) for record in records], matched))
    if not lines:
        lines.append("Nothing in your published data matches that.")
    return lines


def _relationship_lines(relationships: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in relationships:
        examples = [_dict(example) for example in _list(item.get("examples"))]
        count = int(item.get("count") or 0)
        if not examples or not count:
            continue
        kind = str(examples[0].get("entity_type"))
        labels = [_label(example) for example in examples]
        if item.get("direction") == "incoming":
            lines.append(
                f"{_counted(count, kind)} {'refers' if count == 1 else 'refer'} to it: "
                f"{_listed(labels, count)}."
            )
        else:
            lines.append(f"It refers to {_noun(kind, count)} {_listed(labels, count)}.")
    return lines


def _render_entity_detail(evidence: Mapping[str, Any], *, brief: bool) -> list[str]:
    result = _dict(evidence.get("result"))
    lines: list[str] = []
    for entity in [_dict(item) for item in _list(result.get("entities"))]:
        record = _dict(entity.get("record"))
        kind = str(record.get("entity_type"))
        noun = record.get("facility_kind") or _noun(kind, 1)
        article = "an" if str(noun)[:1] in "aeiou" else "a"
        name = record.get("name")
        if lines:
            lines.append("")
        lines.append(
            f"{record.get('entity_id')} is {article} {noun} in your published data"
            + (f": {name}." if name else ".")
        )
        bullets: list[str] = []
        fields = _record_fields(record, limit=12)
        if fields:
            bullets.append(f"Fields: {fields}.")
        bullets.extend(
            _relationship_lines([_dict(item) for item in _list(entity.get("relationships"))])
        )

        parties = _dict(entity.get("counterparties"))
        for role, lead in (
            ("suppliers", "Ordered from"),
            ("customers", "Ordered by"),
            ("products", "Its orders are for"),
        ):
            rows = [_dict(item) for item in _list(parties.get(role))]
            if rows:
                described = [
                    f"{_label(row)} ({_plural(int(row.get('order_count') or 0), 'order')}, "
                    f"{format_number(int(row.get('late_order_count') or 0))} late)"
                    for row in rows
                ]
                bullets.append(f"{lead}: {_listed(described, limit=5)}.")

        late = _dict(entity.get("late"))
        assessed = _dict(late.get("assessed"))
        late_flows = [_dict(item) for item in _list(late.get("late"))]
        late_count = int(late.get("late_count") or 0)
        is_flow = kind in _FLOW_KINDS
        if is_flow and assessed:
            own = next(
                (flow for flow in late_flows if flow.get("entity_id") == record.get("entity_id")),
                None,
            )
            if own:
                reasons = "; ".join(str(reason) for reason in _list(own.get("reasons")))
                bullets.append(f"Timing: late or flagged {_as_of(late.get('as_of'))}: {reasons}.")
            else:
                bullets.append(f"Timing: not late or flagged {_as_of(late.get('as_of'))}.")
        elif assessed:
            if late_count:
                described = [
                    f"{flow.get('entity_id')} ({'; '.join(str(r) for r in _list(flow.get('reasons')))})"
                    for flow in late_flows
                ]
                bullets.append(
                    f"Orders: {_assessed_phrase(late_count, assessed)} linked to it "
                    f"{_is_are(late_count)} late or flagged {_as_of(late.get('as_of'))}: "
                    f"{_listed(described, late_count, 4)}."
                )
            else:
                bullets.append(
                    f"Orders: {_assessed_phrase(0, assessed)} linked to it is late or flagged "
                    f"{_as_of(late.get('as_of'))}."
                )

        stock = _dict(entity.get("stock"))
        positions = [_dict(item) for item in _list(stock.get("positions"))]
        if positions:
            known = {"Product": "product", "Facility": "facility"}.get(kind, "")
            phrases = [_stock_phrase(item, known=known) for item in positions]
            bullets.append(
                f"Stock: {_listed(phrases, int(stock.get('assessed') or len(positions)), 4)}."
            )

        exposure = _dict(entity.get("exposure"))
        parts = [_dict(item) for item in _list(exposure.get("parts_at_risk"))]
        if parts and kind == "Supplier":
            part_count = int(exposure.get("parts_at_risk_count") or len(parts))
            for part in parts[:3]:
                bullets.append(f"At risk: {_part_line(part)}")
            if part_count > 3:
                bullets.append(f"At risk: and {_plural(part_count - 3, 'more part')}.")

        source = _dict(entity.get("source"))
        first_files = [str(item) for item in _list(source.get("first_published_from"))]
        if source.get("first_published_version"):
            text = f"History: first published in version {source.get('first_published_version')}"
            if first_files:
                text += f" from {_join(first_files)}"
            last = source.get("last_touched_version")
            if last and last != source.get("first_published_version"):
                last_files = [str(item) for item in _list(source.get("last_touched_from"))]
                text += f"; last referenced or updated in version {last}"
                if last_files:
                    text += f" ({_join(last_files)})"
            bullets.append(f"{text}.")
        lines.extend(_bullets(bullets, limit=12))
        if brief and parts:
            lines.append("")
            lines.extend(_decision_brief(exposure))

    also = [_label(_dict(item)) for item in _list(result.get("also_matched"))]
    if also:
        lines.append("")
        lines.append(
            f"Your question also matched: {_listed(also)}. Ask about one of them for detail."
        )
    return lines


def _try_asking(workspace: Mapping[str, Any]) -> str:
    examples = _dict(workspace.get("examples"))
    counts = _dict(workspace.get("entity_counts"))
    suggestions: list[str] = []
    if any(kind in counts for kind in ("PurchaseOrder", "SalesOrder", "Shipment")):
        suggestions.append('"which orders are late?"')
    if any(kind in counts for kind in ("InventoryItem", "InventoryLot")):
        suggestions.append('"what is below safety stock?"')
    for kind in ("Supplier", "Product", "PurchaseOrder", "Customer", "Facility"):
        ids = _list(examples.get(kind))
        if ids:
            suggestions.append(f'"tell me about {ids[0]}"')
            break
    suggestions.append('"what changed?"')
    return f"Try asking: {_join(suggestions[:4])}."


def _render_no_match(evidence: Mapping[str, Any]) -> list[str]:
    result = _dict(evidence.get("result"))
    workspace = _dict(evidence.get("workspace"))
    missing = [str(kind) for kind in _list(result.get("kinds_not_published"))]
    unmatched = [
        str(item)
        for item in _list(_dict(evidence.get("question_focus")).get("unmatched_identifiers"))
    ]
    if missing:
        lead = (
            f"There are no {_join([_noun(kind) for kind in missing[:3]])} in your published data."
        )
    elif unmatched:
        lead = f"I could not find {_join(unmatched[:5])} in your published data."
    else:
        lead = "I could not match that question to anything in your published data."
    return [lead, f"It holds {_holds(workspace)}.", _try_asking(workspace)]


def _render_empty(evidence: Mapping[str, Any]) -> list[str]:
    intake = _dict(_dict(evidence.get("result")).get("intake"))
    lines = ["Nothing is published in this workspace yet, so I have no data to answer from."]
    open_lines = _intake_lines(intake, only_open=True) if intake else []
    if open_lines:
        lines.append("")
        lines.append(f"{_plural(len(open_lines), 'upload')} in progress:")
        lines.extend(_bullets(open_lines, limit=6))
        lines.append("")
        lines.append("Finish the review on the Evidence page and publish, then ask again.")
    else:
        lines.append(
            "Upload a file on the Upload page, review it on the Evidence page and publish it, "
            "then ask again."
        )
    return lines


def render_workspace_answer(
    evidence: Mapping[str, Any], *, brief: bool = False, also: str = ""
) -> str:
    """Answer text for one piece of workspace evidence.

    ``brief`` adds the facts that bear on a decision (asked for with "what
    should I do" style questions). ``also`` is one more line of context shown
    above the source line.
    """
    result = _dict(evidence.get("result"))
    focus = _dict(evidence.get("question_focus"))
    workspace = _dict(evidence.get("workspace"))
    kind = result.get("kind")
    if kind == "empty_workspace":
        return "\n".join([*_render_empty(evidence), *([also] if also else [])])
    if kind == "overview":
        lines = _render_overview(evidence)
    elif kind == "late":
        lines = _render_late(evidence, brief=brief)
    elif kind == "stock":
        lines = _render_stock(evidence)
    elif kind == "exposure":
        lines = _render_exposure(evidence, brief=brief)
    elif kind == "changes":
        lines = _render_changes(evidence)
    elif kind == "intake":
        lines = _render_intake(result)
    elif kind == "entity_list":
        lines = _render_entity_list(evidence)
    elif kind == "entity_detail":
        lines = _render_entity_detail(evidence, brief=brief)
    else:
        lines = _render_no_match(evidence)

    notes: list[str] = []
    unmatched = [str(item) for item in _list(focus.get("unmatched_identifiers"))]
    if unmatched and kind != "no_match":
        notes.append(f"I could not find {_join(unmatched[:5])} in your published data.")
    coverage = _dict(workspace.get("coverage"))
    if coverage and not coverage.get("complete"):
        limited = [
            f"{format_number(int(_dict(value).get('loaded') or 0))} of "
            f"{_counted(int(_dict(value).get('total') or 0), str(kind_name))}"
            for kind_name, value in _dict(coverage.get("limited_types")).items()
        ]
        notes.append(
            f"This workspace is larger than I read for one answer: I read {_listed(limited, limit=4)}. "
            "Findings above about late orders, stock and exposure cover only the records read."
        )
    source = _source_line(workspace)
    text = "\n".join(lines).strip()
    tail = [note for note in (*notes, also, source) if note]
    return f"{text}\n\n" + "\n".join(tail) if tail else text


# ── Other tools ──────────────────────────────────────────────────────────────

_UNAVAILABLE_ACTIONS: dict[str, str] = {
    "nexus.decision.approve": "Approving a decision",
    "nexus.decision.execute": "Executing a decision",
    "nexus.decision.create": "Creating a decision",
    "nexus.outcome.record": "Recording an outcome",
    "nexus.observation.record": "Recording an observation",
    "nexus.policy.approve": "Approving a policy",
}


def _scalar_lines(data: Mapping[str, Any], limit: int = 8) -> list[str]:
    """Readable 'field: value' lines for simple values; collections are counted."""
    lines: list[str] = []
    for key, value in data.items():
        if len(lines) >= limit:
            break
        if value is None or key in {"tenant_id", "workspace_id"}:
            continue
        if isinstance(value, (str, int, float, bool)):
            text = (
                _num(value)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else str(value)
            )
            lines.append(f"{_field(key)}: {text[:200]}")
        elif isinstance(value, (list, tuple)):
            lines.append(f"{_field(key)}: {_plural(len(value), 'item')}")
        elif isinstance(value, Mapping):
            lines.append(f"{_field(key)}: {_plural(len(value), 'field')}")
    return lines


def _item_title(item: Mapping[str, Any]) -> str:
    """Short label for a risk, decision, scenario, signal or forecast row."""
    identifier = next(
        (
            str(item[key])
            for key in ("decision_id", "risk_id", "scenario_id", "signal_id", "forecast_id", "id")
            if item.get(key)
        ),
        "",
    )
    title = next(
        (
            str(item[key])
            for key in ("title", "name", "signal_name", "situation", "description", "sku")
            if item.get(key)
        ),
        "",
    )
    status = next(
        (
            str(item[key])
            for key in ("severity", "status", "phase", "outcome_status")
            if item.get(key)
        ),
        "",
    )
    text = " ".join(part for part in (identifier, title[:140]) if part) or "item"
    return f"{text} ({status})" if status else text


def _render_collection(
    data: Mapping[str, Any], key: str, singular: str, plural: str, empty: str
) -> str:
    items = [_dict(item) for item in _list(data.get(key))]
    count = int(data.get("count") or len(items))
    if not count:
        return empty
    lines = [f"{_plural(count, singular, plural)} in this workspace:"]
    lines.extend(_bullets([_item_title(item) for item in items], count))
    return "\n".join(lines)


def _render_forecasts(data: Mapping[str, Any]) -> str:
    forecasts = [_dict(item) for item in _list(data.get("forecasts"))]
    sku = data.get("sku_filter")
    scope = f" for {sku}" if sku else ""
    if not forecasts:
        return (
            f"No forecast is stored{scope} in this workspace. Forecasts appear here after a "
            "demand run; uploading files does not create one."
        )
    lines = [f"{_plural(int(data.get('count') or len(forecasts)), 'stored forecast')}{scope}:"]
    described = []
    for item in forecasts:
        quantiles = ", ".join(
            f"{name.upper()} {_num(item[name])}"
            for name in ("p50", "p80", "p95")
            if item.get(name) is not None
        )
        described.append(
            f"{item.get('sku')}: {quantiles} over {item.get('horizon_days')} days "
            f"(created {_day(item.get('created_at'))[:10]})."
        )
    lines.extend(_bullets(described, int(data.get("count") or len(forecasts))))
    return "\n".join(lines)


def _render_signals(data: Mapping[str, Any]) -> str:
    signals = [_dict(item) for item in _list(data.get("signals"))]
    count = int(data.get("count") or len(signals))
    if not count:
        return "No signals are active for this workspace."
    lines = [f"{_plural(count, 'active signal')}:"]
    described = [
        f"{item.get('signal_name')} ({item.get('severity')}): {str(item.get('explanation') or '')[:200]}"
        for item in signals
    ]
    lines.extend(_bullets(described, count))
    lines.append("")
    lines.append(
        "Signals are computed from how records link to each other in the graph, not from the "
        "dates, statuses or quantities in your files. For those, ask what is late or what is "
        "below safety stock."
    )
    return "\n".join(lines)


def _render_explain(data: Mapping[str, Any]) -> str:
    steps = [str(item) for item in _list(data.get("architecture"))]
    lines = ["How Cortex works, from upload to decision:"]
    lines.extend(f"{index}. {step}." for index, step in enumerate(steps, start=1))
    boundary = data.get("authority_boundary")
    if boundary:
        lines.append("")
        lines.append(str(boundary).replace("Vanessa", "The assistant"))
    return "\n".join(lines)


def _render_generic(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()[:1200]
    mapping = _dict(data)
    if not mapping:
        return "The lookup returned no data."
    for key in ("summary", "message"):
        if isinstance(mapping.get(key), str) and mapping[key].strip():
            return str(mapping[key]).strip()
    lines = _scalar_lines(mapping)
    return "\n".join(f"- {line}" for line in lines) if lines else "The lookup returned no data."


def _register_line(tool: str | None, data: Mapping[str, Any]) -> str:
    """One line about the risk register / decisions that travel with a tool payload."""
    if tool == "nexus.risk.read":
        count = int(data.get("count") or 0)
        if not count:
            return "Risk register: no open risks are recorded for this workspace."
        titles = [_item_title(_dict(item)) for item in _list(data.get("open_risks"))]
        return f"Risk register: {_plural(count, 'open risk')}: {_listed(titles, count, 4)}."
    if tool == "nexus.cockpit.read":
        risk_count = int(data.get("risk_count") or 0)
        decision_count = int(data.get("recent_decision_count") or 0)
        return (
            f"Risk register: {_plural(risk_count, 'open risk')}. "
            f"Decisions recorded: {format_number(decision_count)}."
        )
    if tool == "nexus.recommend":
        context = _dict(data.get("analysis_context"))
        risk_count = int(_dict(context.get("open_risks")).get("count") or 0)
        scenario_count = int(_dict(context.get("scenarios")).get("count") or 0)
        decision_count = len(_list(context.get("recent_decisions")))
        return (
            f"Also on record: {_plural(risk_count, 'open risk')}, "
            f"{_plural(scenario_count, 'saved scenario')} and "
            f"{_plural(decision_count, 'recent decision')}."
        )
    return ""


def render_tool_answer(tool: str | None, data: Any, *, intent: str = "") -> str:
    """Answer text for the evidence returned by one tool."""
    mapping = _dict(data)
    if mapping and set(mapping) == {"error"}:
        action = _UNAVAILABLE_ACTIONS.get(tool or "")
        not_registered = mapping.get("error") == "tool not registered"
        if action and not_registered:
            return (
                f"{action} is not available from the Ask box. Use the decision and approval "
                "workflow for that; asking here changes nothing."
            )
        if not_registered:
            return (
                f"That lookup ({tool or 'tool'}) is not available from the Ask box. Nothing "
                "was changed."
            )
        # The cause is logged with the request's trace id. It is not repeated
        # here: an error text can name internal hosts and addresses.
        return (
            f"I could not read that data: the lookup ({tool or 'tool'}) failed. Nothing was "
            "changed. Please try again; if it keeps failing, the cause is in the service log."
        )
    workspace_data = _dict(mapping.get("workspace_data"))
    if workspace_data:
        return render_workspace_answer(
            workspace_data,
            brief=intent in {"recommend", "compare"},
            also=_register_line(tool, mapping),
        )
    if tool == "nexus.forecast.read" and "forecasts" in mapping:
        return _render_forecasts(mapping)
    if tool == "nexus.decision.list" and "decisions" in mapping:
        return _render_collection(
            mapping,
            "decisions",
            "decision",
            "decisions",
            "No decisions are recorded in this workspace.",
        )
    if tool == "nexus.trace.get" and "recent_decision_memory" in mapping:
        return _render_collection(
            mapping,
            "recent_decision_memory",
            "decision in memory",
            "decisions in memory",
            "No decision history is recorded in this workspace yet.",
        )
    if tool == "nexus.scenario.read" and "scenarios" in mapping:
        return _render_collection(
            mapping,
            "scenarios",
            "saved scenario",
            "saved scenarios",
            "No scenarios are saved in this workspace.",
        )
    if tool == "nexus.signal.read" and "signals" in mapping:
        return _render_signals(mapping)
    if tool == "nexus.explain" and "architecture" in mapping:
        return _render_explain(mapping)
    return _render_generic(data)


def no_evidence_answer(intent: str) -> str:
    """Text when no tool ran: help, greeting, an unreadable question."""
    examples = " ".join(f'"{question}"' for question in EXAMPLE_QUESTIONS)
    if intent == "help":
        return (
            "I answer questions from the data published in this workspace: suppliers, products, "
            "orders, shipments, inventory and facilities, plus what is late, what is short, what "
            "is exposed, what changed and where each upload stands.\n\n"
            f"For example: {examples}\n\n"
            "You can also name a record by its ID or name (a supplier, an order, a SKU), or "
            "ask about forecasts, decisions, scenarios and signals. I only read: approving or "
            "executing a decision goes through its own workflow."
        )
    if intent == "greeting":
        return f"Hello. Ask me about the data published in this workspace, for example: {examples}"
    if intent == "unknown":
        return (
            "I could not tell what that question is about. I answer from the data published in "
            f"this workspace. For example: {examples}"
        )
    return (
        f"I read that as a {intent.replace('_', ' ')} request, but no data came back for it, "
        "so I have nothing to report."
    )


def render_answer(intent: str, evidence: Sequence[tuple[str | None, Any]]) -> str:
    """Full answer for the built-in assistant."""
    if not evidence:
        return no_evidence_answer(intent)
    blocks = [render_tool_answer(tool, data, intent=intent) for tool, data in evidence]
    return "\n\n".join(block for block in blocks if block)


def summarize_evidence(tool: str | None, data: Any) -> str:
    """One line saying what a tool read, for the evidence list in the UI."""
    mapping = _dict(data)
    if mapping and set(mapping) == {"error"}:
        if mapping.get("error") == "tool not registered":
            return "Lookup not available."
        return "Lookup failed."
    workspace_data = _dict(mapping.get("workspace_data"))
    if workspace_data:
        workspace = _dict(workspace_data.get("workspace"))
        coverage = _dict(workspace.get("coverage"))
        focus = _dict(workspace_data.get("question_focus"))
        version = workspace.get("world_state_version")
        if not version:
            return "Nothing is published in this workspace yet."
        text = (
            f"Read {_plural(int(coverage.get('records_loaded') or 0), 'published record')} "
            f"from version {version}"
        )
        matched = [_label(_dict(item)) for item in _list(focus.get("matched"))]
        if matched:
            text += f"; matched {_listed(matched, limit=3)}"
        return f"{text}."
    for key, singular in (
        ("forecasts", "forecast"),
        ("decisions", "decision"),
        ("recent_decision_memory", "decision in memory"),
        ("scenarios", "scenario"),
        ("signals", "signal"),
        ("open_risks", "open risk"),
    ):
        if key in mapping:
            return f"Read {_plural(int(mapping.get('count') or len(_list(mapping.get(key)))), singular)}."
    if isinstance(mapping.get("summary"), str):
        return str(mapping["summary"])[:200]
    if isinstance(mapping.get("message"), str):
        return str(mapping["message"])[:200]
    if isinstance(mapping.get("status"), str):
        return f"Status: {mapping['status']}."
    return "Read workspace data."


# ── Wording shared with the Command Center ──────────────────────────────────
#
# The cockpit lists what stands out in the published records. It uses these
# functions, so a line there reads the same as the matching line of an answer.


def kind_noun(entity_type: str, count: int = 2) -> str:
    """Everyday name of a record kind: 'purchase order', 'purchase orders'."""
    return _noun(entity_type, count)


def late_flow_parts(flow: Mapping[str, Any]) -> tuple[str, str]:
    """What a late order or shipment carries, and why it counts as late.

    ('400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd',
    'promised for 2026-11-10 and not marked as delivered 8 days later'). The
    first part is empty when the record names no product, quantity or partner.
    """
    reasons = "; ".join(str(reason) for reason in _list(flow.get("reasons")))
    return _flow_subject(flow), reasons


def late_flow_sentence(flow: Mapping[str, Any]) -> str:
    """One late order or shipment as the answer to "which orders are late?" lists it."""
    return _flow_line(flow)


def stock_sentence(position: Mapping[str, Any]) -> str:
    """'C-2000 Cast Iron Housing at WH-PUNE: 120 on hand against a safety stock of 300 (180 short)'."""
    return _stock_phrase(position)


def stock_parts(position: Mapping[str, Any]) -> tuple[str, str]:
    """``stock_sentence`` as (which stock, the figures it is judged on).

    ('C-2000 Cast Iron Housing at WH-PUNE', '120 on hand against a safety
    stock of 300 (180 short)').
    """
    product = _label(_dict(position.get("product")))
    facility = _label(_dict(position.get("facility")))
    where = f"{product} at {facility}" if product and facility else product or facility
    head = str(where or position.get("entity_id"))
    sentence = _stock_phrase(position)
    prefix = f"{head}: "
    return (head, sentence[len(prefix) :]) if sentence.startswith(prefix) else (head, sentence)


def flagged_sentence(flag: Mapping[str, Any]) -> str:
    """'S-102 Borealis Plastics: status is delayed.'"""
    field_name = _field(flag.get("status_field") or "status")
    return f"{_label(flag)}: {field_name} is {flag.get('status')}."


def attention_sentences(attention: Mapping[str, Any]) -> list[str]:
    """The sentences an overview answer gives about late orders, stock and flagged partners."""
    return _attention_lines(attention)


def world_state_version_of(data: Any) -> int | None:
    """Published data version a tool answered from, when it reports one."""
    mapping = _dict(data)
    candidates = (
        _dict(_dict(mapping.get("workspace_data")).get("workspace")).get("world_state_version"),
        mapping.get("world_state_version"),
        _dict(mapping.get("graph")).get("world_state_version"),
    )
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None
