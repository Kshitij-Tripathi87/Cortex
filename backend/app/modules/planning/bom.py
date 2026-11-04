"""Deterministic multi-level BOM resolution and explosion."""

from __future__ import annotations

from decimal import Decimal

from app.modules.planning.models import (
    BOMRevision,
    DemandContribution,
    ExplicitMaterialRequirement,
    ItemType,
    OrderRequirementsResult,
    ProductionOrder,
    ProjectionStatus,
    UOMConverter,
)

_EXCLUDED_ORDER_STATUSES = {
    "cancelled",
    "closed",
    "completed",
    "complete",
    "delivered",
    "shipped",
}


class BOMResolutionError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}:{detail}" if detail else code)


def resolve_revision(
    revisions: tuple[BOMRevision, ...],
    *,
    item_id: str,
    item_type: ItemType,
    facility_id: str,
    effective_at,
    explicit_revision_id: str | None = None,
) -> BOMRevision:
    candidates = [
        revision
        for revision in revisions
        if revision.parent_item_id == item_id
        and revision.parent_item_type == item_type
        and revision.is_effective_at(effective_at, facility_id)
    ]
    if explicit_revision_id:
        selected = [
            revision
            for revision in candidates
            if revision.revision_id == explicit_revision_id
        ]
        if len(selected) != 1:
            raise BOMResolutionError("EXPLICIT_BOM_REVISION_NOT_EFFECTIVE", explicit_revision_id)
        return selected[0]

    # A facility-specific revision takes precedence over a global revision,
    # but overlapping revisions at the same specificity are ambiguous.
    specific = [revision for revision in candidates if revision.facility_id == facility_id]
    candidates = specific or [revision for revision in candidates if revision.facility_id is None]
    if not candidates:
        raise BOMResolutionError("NO_VALID_BOM_REVISION", item_id)
    if len(candidates) != 1:
        ids = ",".join(sorted(revision.revision_id for revision in candidates))
        raise BOMResolutionError("AMBIGUOUS_BOM_REVISION", ids)
    return candidates[0]


def _explicit_contributions(
    order: ProductionOrder, converter: UOMConverter
) -> tuple[DemandContribution, ...]:
    if not order.explicit_requirements:
        raise BOMResolutionError("EXPLICIT_REQUIREMENTS_EMPTY", order.order_id)
    result: list[DemandContribution] = []
    seen: set[str] = set()
    for requirement in order.explicit_requirements:
        if requirement.requirement_id in seen:
            raise BOMResolutionError("DUPLICATE_REQUIREMENT_ID", requirement.requirement_id)
        seen.add(requirement.requirement_id)
        if requirement.quantity < 0 or requirement.reserved_quantity < 0:
            raise BOMResolutionError("NEGATIVE_REQUIREMENT_QUANTITY", requirement.requirement_id)
        if requirement.reserved_quantity > requirement.quantity:
            raise BOMResolutionError("RESERVATION_EXCEEDS_REQUIREMENT", requirement.requirement_id)
        quantity = converter.convert(
            requirement.quantity, requirement.uom, requirement.uom
        )
        result.append(
            DemandContribution(
                contribution_id=requirement.requirement_id,
                production_order_id=order.order_id,
                facility_id=order.facility_id,
                material_id=requirement.material_id,
                gross_quantity=quantity,
                reserved_quantity=requirement.reserved_quantity,
                reservation_linked=requirement.reservation_linked,
                uncovered_quantity=quantity - requirement.reserved_quantity,
                uom=requirement.uom,
                need_at=requirement.need_at,
                source_ref=requirement.source_ref or order.source_ref,
            )
        )
    return tuple(result)


def explode_production_order(
    order: ProductionOrder,
    revisions: tuple[BOMRevision, ...],
    converter: UOMConverter | None = None,
    *,
    max_depth: int = 20,
    max_lines: int = 20_000,
) -> OrderRequirementsResult:
    """Explode an order to purchased/material leaves, preserving every BOM path.

    Repeated materials on distinct BOM branches are intentionally additive.
    Cycle detection is ancestry-local, not global, so valid sibling branches
    that share a component are never suppressed.
    """
    converter = converter or UOMConverter()
    status = order.status.strip().lower()
    if status in _EXCLUDED_ORDER_STATUSES:
        return OrderRequirementsResult(
            production_order_id=order.order_id,
            status=ProjectionStatus.COMPLETED,
            contributions=(),
            warnings=("ORDER_EXCLUDED_BY_STATUS",),
        )
    if order.quantity <= 0:
        return OrderRequirementsResult(
            order.order_id, ProjectionStatus.NOT_CALCULABLE, (), error_code="ORDER_QUANTITY_INVALID"
        )

    try:
        if order.explicit_requirements and not order.explicit_requirements_authoritative:
            raise BOMResolutionError("AMBIGUOUS_REQUIREMENTS")
        if order.explicit_requirements_authoritative:
            contributions = _explicit_contributions(order, converter)
            return OrderRequirementsResult(
                order.order_id, ProjectionStatus.COMPLETED, contributions
            )

        root_quantity = converter.convert(order.quantity, order.order_uom, order.item_base_uom)
        root_revision = resolve_revision(
            revisions,
            item_id=order.item_id,
            item_type=order.item_type,
            facility_id=order.facility_id,
            effective_at=order.material_need_at,
            explicit_revision_id=order.bom_revision_id,
        )

        contributions: list[DemandContribution] = []
        visited_lines = 0

        def walk(
            revision: BOMRevision,
            parent_quantity: Decimal,
            path: tuple[str, ...],
            ancestry: frozenset[tuple[ItemType, str]],
            depth: int,
        ) -> None:
            nonlocal visited_lines
            parent_key = (revision.parent_item_type, revision.parent_item_id)
            if parent_key in ancestry:
                raise BOMResolutionError(
                    "BOM_CYCLE",
                    " -> ".join(
                        f"{item_type.value}:{item_id}"
                        for item_type, item_id in sorted(
                            ancestry, key=lambda entry: (entry[0].value, entry[1])
                        )
                    ),
                )
            if depth > max_depth:
                raise BOMResolutionError("BOM_MAX_DEPTH_EXCEEDED", str(max_depth))

            line_ids: set[str] = set()
            next_ancestry = ancestry | {parent_key}
            for line in sorted(revision.lines, key=lambda value: value.line_id):
                visited_lines += 1
                if visited_lines > max_lines:
                    raise BOMResolutionError("BOM_MAX_LINES_EXCEEDED", str(max_lines))
                if line.line_id in line_ids:
                    raise BOMResolutionError("DUPLICATE_BOM_LINE_ID", line.line_id)
                line_ids.add(line.line_id)
                if not line.is_effective_at(order.material_need_at):
                    continue
                if line.usage_quantity <= 0:
                    raise BOMResolutionError("BOM_USAGE_QUANTITY_INVALID", line.line_id)
                factor = line.scrap_factor if line.scrap_factor is not None else Decimal("1")
                if factor <= 0:
                    raise BOMResolutionError("BOM_SCRAP_FACTOR_INVALID", line.line_id)
                child_quantity = converter.convert(
                    parent_quantity * line.usage_quantity * factor,
                    line.usage_uom,
                    line.child_base_uom,
                )
                next_path = path + (line.line_id,)
                if line.child_is_assembly:
                    child_revision = resolve_revision(
                        revisions,
                        item_id=line.child_item_id,
                        item_type=line.child_item_type,
                        facility_id=order.facility_id,
                        effective_at=order.material_need_at,
                    )
                    walk(
                        child_revision,
                        child_quantity,
                        next_path,
                        next_ancestry,
                        depth + 1,
                    )
                else:
                    contributions.append(
                        DemandContribution(
                            contribution_id=f"{order.order_id}:{'/'.join(next_path)}",
                            production_order_id=order.order_id,
                            facility_id=order.facility_id,
                            material_id=line.child_item_id,
                            gross_quantity=child_quantity,
                            reserved_quantity=Decimal("0"),
                            reservation_linked=False,
                            uncovered_quantity=child_quantity,
                            uom=line.child_base_uom,
                            need_at=order.material_need_at,
                            bom_line_path=next_path,
                            source_ref=order.source_ref,
                        )
                    )

        walk(root_revision, root_quantity, (), frozenset(), 1)
        if not contributions:
            raise BOMResolutionError("BOM_HAS_NO_EFFECTIVE_MATERIAL_LINES", order.item_id)
        return OrderRequirementsResult(
            order.order_id, ProjectionStatus.COMPLETED, tuple(contributions)
        )
    except (BOMResolutionError, ValueError) as exc:
        code = exc.code if isinstance(exc, BOMResolutionError) else str(exc)
        return OrderRequirementsResult(
            order.order_id, ProjectionStatus.NOT_CALCULABLE, (), error_code=code
        )


__all__ = ["BOMResolutionError", "explode_production_order", "resolve_revision"]
