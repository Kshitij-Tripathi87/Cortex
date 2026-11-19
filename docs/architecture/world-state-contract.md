# World State contract

Status: frozen for the v0.1 sprint.

The World State is what Cortex Nexus knows, read back in one piece. It is a
projection of rows in PostgreSQL, assembled on every request by
`app/services/world_state_service.py`. Nothing is stored for it and nothing
is cached, so it cannot drift from the records.

## Guarantees

1. **Scoped.** Every query filters on the verified workspace. Another
   workspace's id is answered `404 WORKSPACE_NOT_AVAILABLE`; another
   workspace's project is answered `404 NOT_FOUND`.
2. **From the database.** Every count is a `COUNT` over stored rows at the
   moment of the request. No number is a constant or comes from a fixture.
3. **One snapshot.** All queries of one response run in a single read-only
   `REPEATABLE READ` transaction: counts and lists describe the same instant
   even while an import commits.
4. **Deterministic.** For one database state the response is identical
   except `generated_at`. Every collection has a fixed order (below).
5. **Bounded.** Top-level collections are paged. Nested collections have a
   fixed cap and a count beside them, so a shortened list is visible as such.
6. **Explicit about what is missing.** A value that was never recorded is
   `null`; a relationship that does not exist is an empty list. Missing
   information is also named under `data_quality`.
7. **Facts only.** There is no `risk_score`, `delay_probability`,
   `root_cause`, `recovery_options` or `recommended_action`, and no field
   that compares two dates. Nothing is computed from the clock: the only
   time-dependent value is `generated_at`. A later intelligence layer
   receives its reference date (`as_of`) explicitly and derives findings from
   these facts.

Counts under `summary` include every record whatever its status. Data-quality
warnings leave out records that are themselves `CANCELLED`.

## Workspace summary

`GET /api/v1/workspaces/{workspace_id}/world-state/summary`

```json
{
  "workspace_id": "00000000-0000-4000-8000-000000000001",
  "generated_at": "2026-11-19T07:30:00Z",
  "summary": {
    "projects": 1,
    "suppliers": 8,
    "equipment": 20,
    "purchase_orders": 12,
    "purchase_order_items": 19,
    "milestones": 40,
    "milestone_plan_versions": 40,
    "supplier_commitment_versions": 12
  },
  "data_quality": {
    "valid_records": 131,
    "invalid_records": 0,
    "ingestion": {
      "batches": {"UPLOADED": 0, "PREVIEWED": 0, "COMMITTING": 0, "COMMITTED": 8, "FAILED": 0},
      "rows": {"VALID": 0, "INVALID": 0, "COMMITTED": 131, "SKIPPED": 0, "FAILED": 0}
    },
    "warning_counts": {"PO_ACKNOWLEDGEMENT_NOT_RECORDED": 1},
    "warnings": [
      {
        "dimension": "COMPLETENESS",
        "code": "PO_ACKNOWLEDGEMENT_NOT_RECORDED",
        "entity_type": "purchase_order",
        "entity_id": "5b0c…",
        "reference": "PO-1005",
        "project_id": "9a1e…",
        "message": "No acknowledgement milestone is recorded for this purchase order."
      }
    ],
    "warnings_truncated": false
  }
}
```

The numbers in the example are illustrative.

| Field | Definition |
|---|---|
| `summary.*` | Number of rows of that kind in the workspace |
| `data_quality.valid_records` | Source rows in the ingestion ledger that are `VALID`, `COMMITTED` or `SKIPPED` |
| `data_quality.invalid_records` | Source rows in the ledger that are `INVALID` or `FAILED` |
| `data_quality.ingestion` | Batches and source rows by status; every status is present, zero included |
| `data_quality.warning_counts` | Complete count per warning code; codes with zero occurrences are omitted |
| `data_quality.warnings` | At most 100 warnings, ordered by code, then by `reference` |
| `data_quality.warnings_truncated` | `true` when warnings were left out of the list |

### Data-quality warnings

Observations about stored records. They say what is not recorded. They do
not say that anything is late, at risk or anyone's fault.

| Code | Dimension | Stated fact |
|---|---|---|
| `EQUIPMENT_WITHOUT_PO_LINE_ITEM` | COMPLETENESS | No purchase order line item names this equipment |
| `EQUIPMENT_REQUIRED_DATE_NOT_RECORDED` | COMPLETENESS | The equipment has no required-on-site date |
| `PO_WITHOUT_LINE_ITEMS` | COMPLETENESS | The purchase order has no line item |
| `PO_ACKNOWLEDGEMENT_NOT_RECORDED` | COMPLETENESS | The purchase order has no `PO_ACKNOWLEDGEMENT` milestone |
| `PO_WITHOUT_SUPPLIER_COMMITMENT` | COMPLETENESS | The purchase order has no supplier commitment |
| `MILESTONE_COMPLETED_WITHOUT_ACTUAL_DATE` | COMPLETENESS | The milestone is `COMPLETED` and has no actual date |

Validity, consistency, uniqueness and referential integrity are enforced when
records are written, so stored records cannot violate them; violations appear
on rejected source rows (`invalid_records`, and per row in the batch detail).
The dimensions are never merged into a percentage.

## Workspace World State

`GET /api/v1/workspaces/{workspace_id}/world-state?limit=50&offset=0`

Everything in the summary, plus the workspace and a page of its projects:

```json
{
  "workspace_id": "…",
  "generated_at": "…",
  "workspace": {"id": "…", "name": "Nexus Demo Workspace", "slug": "nexus-demo", "status": "ACTIVE"},
  "summary": {},
  "data_quality": {},
  "projects": {
    "items": [
      {
        "id": "…",
        "code": "DC-IN-001",
        "name": "North Ridge Data Centre Phase 1",
        "location": "Pune, Maharashtra",
        "status": "ACTIVE",
        "target_completion_date": "2027-09-30",
        "counts": {"equipment": 20, "purchase_orders": 12, "purchase_order_items": 19, "milestones": 40}
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

Projects are ordered by `code`. `limit` is 1–200. A workspace without
projects returns `items: []`, `total: 0` and zero counts.

## Project World State

`GET /api/v1/workspaces/{workspace_id}/world-state/projects/{project_id}`

| Query parameter | Default | Meaning |
|---|---|---|
| `equipment_limit`, `equipment_offset` | 50, 0 | Page of equipment (limit 1–200) |
| `po_limit`, `po_offset` | 50, 0 | Page of purchase orders (limit 1–200) |
| `include_history` | `false` | Include plan and commitment version lists |

```json
{
  "workspace_id": "…",
  "generated_at": "…",
  "project": {"id": "…", "code": "DC-IN-001", "name": "…", "location": "…", "status": "ACTIVE", "target_completion_date": "2027-09-30"},
  "summary": {"equipment": 20, "purchase_orders": 12, "purchase_order_items": 19, "milestones": 40, "suppliers": 8},
  "equipment": {
    "items": [
      {
        "id": "…",
        "equipment_code": "DG-003",
        "name": "Diesel generator set 3",
        "category": "GENERATOR",
        "criticality": "CRITICAL",
        "procurement_status": "RFQ",
        "required_on_site_date": "2027-01-18",
        "specification": {"description": "2.5 MVA standby"},
        "purchase_order_count": 0,
        "purchase_orders": []
      }
    ],
    "total": 20, "limit": 50, "offset": 0
  },
  "purchase_orders": {
    "items": [
      {
        "id": "…",
        "po_number": "PO-1007",
        "status": "IN_PRODUCTION",
        "issue_date": "2026-06-22",
        "currency": "EUR",
        "total_value": "412000.00",
        "supplier": {"id": "…", "supplier_code": "SUP-004", "name": "…", "status": "ACTIVE"},
        "line_item_count": 2,
        "line_items": [
          {"id": "…", "equipment_id": "…", "equipment_code": "UPS-001", "equipment_name": "…", "quantity": "1.000", "unit_price": "206000.00"}
        ],
        "milestone_count": 3,
        "milestones": [
          {
            "id": "…",
            "milestone_type": "PO_ACKNOWLEDGEMENT",
            "sequence_no": 1,
            "status": "COMPLETED",
            "actual_date": "2026-06-29",
            "plan_version_count": 1,
            "current_plan": {"version_no": 1, "planned_date": "2026-06-29", "recorded_at": "…", "recorded_by": "…", "source_ingestion_row_id": "…"},
            "plan_history": null
          }
        ],
        "commitment_version_count": 2,
        "current_commitment": {"version_no": 2, "committed_delivery_date": "2026-12-06", "source_reference": "…", "recorded_at": "…", "recorded_by": "…", "source_ingestion_row_id": "…"},
        "commitment_history": null
      }
    ],
    "total": 12, "limit": 50, "offset": 0
  },
  "data_quality": {"warning_counts": {}, "warnings": [], "warnings_truncated": false}
}
```

| Field | Definition |
|---|---|
| `summary.suppliers` | Distinct suppliers named on the project's purchase orders |
| `equipment[].purchase_orders` | The purchase orders whose line items name the equipment, each with its supplier. An empty list means none is recorded; no supplier is inferred |
| `purchase_orders[].current_commitment` | The commitment version with the greatest `version_no`; `null` when none is recorded |
| `milestones[].current_plan` | The plan version with the greatest `version_no` |
| `actual_date` | `null` until an actual completion date is recorded. Planned and actual dates are separate fields and are never compared here |
| `plan_history`, `commitment_history` | `null` unless `include_history=true`; then the versions, oldest first |
| `source_ingestion_row_id` | The source row that introduced the version; `null` for a version created through the API |
| `data_quality` | The warnings above, restricted to records of this project |

### Order and bounds

| Collection | Order | Bound |
|---|---|---|
| `equipment.items` | `equipment_code` | Page |
| `equipment[].purchase_orders` | `po_number` | First 20; `purchase_order_count` is the total |
| `purchase_orders.items` | `po_number` | Page |
| `line_items` | `equipment_code` | First 200; `line_item_count` is the total |
| `milestones` | Lifecycle order of `milestone_type`, then `sequence_no` | First 200; `milestone_count` is the total |
| `plan_history`, `commitment_history` | `version_no` ascending | Latest 50; the version counts are the totals |
| `data_quality.warnings` | Code, then `reference` | First 100; `warning_counts` is complete |

Lifecycle order of milestone types: `PO_ACKNOWLEDGEMENT`,
`DRAWING_SUBMISSION`, `DRAWING_APPROVAL`, `MANUFACTURING_START`,
`FACTORY_ACCEPTANCE_TEST`, `DISPATCH`, `DELIVERY`, `INSTALLATION`.

## The five demo conditions, as facts

The synthetic dataset contains five deliberate conditions. The World State
shows the facts each one consists of; it does not name or rate them.

| Condition | What the World State shows |
|---|---|
| Overdue delivery candidate | `current_commitment.committed_delivery_date` of the purchase order, and no `DELIVERY` milestone with status `COMPLETED` |
| Changed commitment | `commitment_version_count` of 2; both versions under `commitment_history` |
| Missing confirmation | No `PO_ACKNOWLEDGEMENT` milestone on the purchase order; `PO_ACKNOWLEDGEMENT_NOT_RECORDED` under `data_quality` |
| Milestone slippage | `current_plan.planned_date` and `actual_date` of the milestone, side by side |
| Procurement gap | The equipment with `purchase_orders: []`; `EQUIPMENT_WITHOUT_PO_LINE_ITEM` under `data_quality` |
