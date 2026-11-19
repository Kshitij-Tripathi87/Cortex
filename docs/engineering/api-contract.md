# API contract

Status: frozen for the v0.1 sprint. The machine-readable form is
`docs/engineering/openapi.json`, exported from the code by `make openapi`;
CI fails when it is stale. The World State responses are specified in
`docs/architecture/world-state-contract.md`.

## Conventions

| Topic | Rule |
|---|---|
| Prefix | `/api/v1`; health checks at `/health/live` and `/health/ready` |
| Bind | `127.0.0.1` only |
| Workspace | Every resource path starts with `/api/v1/workspaces/{workspace_id}`. Only the configured development workspace is served |
| Identifiers | UUID strings |
| Dates | `YYYY-MM-DD`, written with the digits 0 to 9. Nothing else is accepted: no timestamp, no date-time, no other calendar |
| Timestamps | ISO 8601 in UTC with `Z` |
| Decimals | JSON **strings** with a fixed scale: money `"1234.56"`, quantity `"2.000"`. Requests may send a string or an integer; a JSON float is rejected, because it cannot carry every decimal exactly. A value with more digits than the field holds is rejected, never rounded |
| Lists | `{"items": [...], "total": n, "limit": n, "offset": n}`; `limit` 1–200, default 50; `offset` 0–2,147,483,647; a fixed, documented order |
| Text | Trimmed; empty text is rejected; bounded in length. The NUL character is rejected (`INVALID_VALUE`): the database cannot store it |
| Whole numbers | A milestone `sequence_no` is a JSON number from 1 to 2,147,483,647. `"1"`, `1.0` and `true` are rejected |
| Partial update | `PATCH` changes only the fields that are present. Unknown fields, natural keys included, are rejected |
| Request id | `X-Request-ID` is returned on every response. A well-formed id sent by the caller (8–128 characters of letters, digits, `.`, `_`, `-`) is kept; otherwise one is generated |

## Status codes

| Status | Use |
|---|---|
| 200 | Read, update, or an operation that changed nothing (replayed commit, duplicate upload, unchanged version) |
| 201 | A record, version or batch was created |
| 400 | The body is not valid JSON |
| 404 | The record or route does not exist, or the record is not in the verified workspace |
| 409 | Natural-key conflict; a batch that is not in a committable state; a commit whose preconditions no longer hold; a request that PostgreSQL rolled back to resolve a deadlock with another writer (send it again) |
| 413 | The upload is larger than `MAX_UPLOAD_SIZE_MB` |
| 415 | The upload is not a CSV or XLSX file |
| 422 | The request is well formed and its content is invalid: a field, a reference, a value the database cannot store, or a file that cannot be read as a table |
| 500 | Unexpected failure: generic message, request id, details only in the log |
| 503 | The database is not reachable |

A record of another workspace is answered exactly like a record that does not
exist. 202 is not used: preview and commit are synchronous.

## Error envelope

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The supplied record is invalid.",
    "details": [
      {"field": "items.0.quantity", "code": "MUST_BE_POSITIVE", "message": "Input should be greater than 0"}
    ],
    "request_id": "0d7c2b0f5b5c4c57a5a8f2b9a1c3d4e5"
  }
}
```

`details` is always a list. An entry has `code` and `message`, and where they
apply `field` (JSON requests), `row_number` and `column` (imports). No
response contains SQL, a stack trace, a filesystem path, an environment
variable or a submitted value.

## Error codes

Codes are stable. Messages may be reworded.

| Code | Meaning | What to do |
|---|---|---|
| `REQUIRED_FIELD_MISSING` | A required field, column or cell is absent | Supply it |
| `INVALID_DATE` | Not an unambiguous `YYYY-MM-DD` date | Use ISO dates |
| `INVALID_ENUM` | Not one of the allowed values or documented aliases | Use an allowed value |
| `INVALID_DECIMAL` | Malformed, non-finite or too precise a number | Supply plain decimal text |
| `INVALID_INTEGER` | Not a whole number, or one larger than 2,147,483,647 | Supply a whole number in range |
| `OUT_OF_RANGE` | A number outside the documented range of a JSON field or query parameter (`limit`, `offset`, `sequence_no`) | Correct the value |
| `INVALID_VALUE` | A value of the wrong kind, or text with a character that cannot be stored (NUL) | Correct the value |
| `INVALID_CURRENCY` | Not three letters | Use a three-letter currency code |
| `INVALID_UUID` | Not a UUID | Correct the identifier |
| `MUST_BE_POSITIVE` | Must be greater than zero | Correct the value |
| `MUST_BE_NON_NEGATIVE` | Must not be negative | Correct the value |
| `VALUE_TOO_LONG` | Longer than the field allows | Shorten it |
| `UNKNOWN_FIELD` | The request has a field the operation does not accept | Remove it |
| `DUPLICATE_NATURAL_KEY` | The natural key exists already, or rows of one file collide on it with different values | Remove the duplicate or resolve the conflict |
| `REFERENCE_NOT_FOUND` | A referenced record does not exist in this workspace | Import the dependency first or correct the reference |
| `REFERENCE_INACTIVE` | A new purchase order names an inactive supplier | Reactivate the supplier or choose another |
| `CROSS_PROJECT_REFERENCE` | The purchase order and the equipment belong to different projects | Correct the mapping |
| `IMMUTABLE_FIELD_CONFLICT` | An import row names an existing record with a different project or supplier | Correct the row; identities are not rewritten by imports |
| `INCONSISTENT_MILESTONE_STATE` | An actual date on a milestone that is not completed | Correct status or date |
| `AMBIGUOUS_COLUMN_MAPPING` | Two source columns map to one field with different values | Correct the source |
| `ROW_SHAPE_MISMATCH` | A row has more cells than the header | Correct the row |
| `FORMULA_WITHOUT_CACHED_VALUE` | A spreadsheet cell holds a formula without a stored result | Save the workbook with calculated values, or enter the value |
| `UNSUPPORTED_FILE` | Not CSV or XLSX (415) | Save as CSV or XLSX |
| `FILE_TOO_LARGE` | Larger than the upload limit; or a workbook that is too large once uncompressed, holds more cells in one worksheet than a full import, more formatting and structure than can be read, or a single value or tag of more than one megabyte (413) | Split the file. For a workbook: copy the worksheet to import into a workbook of its own |
| `EMPTY_FILE`, `MISSING_HEADER`, `DUPLICATE_HEADER`, `INVALID_ENCODING`, `MALFORMED_FILE`, `ROW_LIMIT_EXCEEDED`, `COLUMN_LIMIT_EXCEEDED`, `CELL_TOO_LONG` | The file cannot be read as a bounded table (422) | Correct the file |
| `MALFORMED_FILE` for a workbook | Besides a damaged archive: a part that declares a document type or entities, rows or cells that are not numbered in ascending order, two worksheets with one name, or a worksheet to import whose name is longer than 160 characters (422). The reader refuses these rather than read a part of the worksheet | Open the workbook in a spreadsheet program and save it again; rename the worksheet |
| `AMBIGUOUS_WORKSHEET`, `WORKSHEET_NOT_FOUND` | The workbook has several data sheets and none was named, or the named one is absent (422). A name is matched exactly, and otherwise with the spaces around it ignored if that fits one worksheet only. The message quotes at most ten names, each shortened to 40 characters | Send `sheet_name` |
| `DUPLICATE_FILE` | The same workbook was already submitted for this entity type with another worksheet (409) | Use the existing batch, or save the worksheet as its own file |
| `REQUEST_TOO_LARGE` | A request body other than an upload is larger than 1 MB (413) | Send less in one request |
| `BATCH_NOT_COMMITTABLE` | The batch is not `PREVIEWED` (409) | Preview a new or corrected file |
| `COMMIT_CONFLICT` | A row that was valid at preview is no longer valid; nothing was committed and the batch is `FAILED` (409) | Fix the cause and upload the file again |
| `COMMIT_FAILED` | The database could not store a value of a validated batch; nothing was committed and the batch is `FAILED` (422). Validation is meant to make this impossible; it is logged as an error | Correct the file and upload it again |
| `CONFLICT` | The request collided with another writer: two requests created the same key at the same moment, or PostgreSQL rolled this one back to resolve a deadlock (409). Nothing was written; after a deadlock a batch stays `PREVIEWED` | Send the request again |
| `WORKSPACE_NOT_AVAILABLE` | The workspace is not the configured one, is missing or is disabled (404) | Use the configured development workspace |
| `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `MALFORMED_REQUEST`, `BAD_REQUEST`, `VALIDATION_ERROR`, `DATABASE_UNAVAILABLE`, `INTERNAL_ERROR` | Generic envelope codes | — |

Warnings (never blocking): `UNKNOWN_SOURCE_COLUMN`, `DUPLICATE_ROW`,
`MULTIPLE_COLUMNS_FOR_FIELD`, `BLANK_ROWS_SKIPPED`,
`FORMULA_CACHED_VALUE_USED`, `REQUIRED_ON_SITE_DATE_NOT_RECORDED`.

`CROSS_WORKSPACE_REFERENCE` from the playbook catalog is deliberately not
returned. A reference to a record of another workspace is indistinguishable
from a reference to nothing (`REFERENCE_NOT_FOUND`); a distinct code would
tell the caller that the record exists elsewhere. The database rejects such a
link independently, through composite foreign keys.

## Routes

`{ws}` stands for `/api/v1/workspaces/{workspace_id}`.

| Method | Path | Purpose | Success |
|---|---|---|---|
| GET | `/health/live` | Process liveness | 200 |
| GET | `/health/ready` | Database reachable and schema at the migration head | 200, else 503 |
| GET | `{ws}` | The configured workspace | 200 |
| GET | `{ws}/projects` | List projects (`status`) | 200 |
| POST | `{ws}/projects` | Create a project | 201 |
| GET | `{ws}/projects/{project_id}` | One project | 200 |
| PATCH | `{ws}/projects/{project_id}` | Update name, location, status, target date | 200 |
| GET | `{ws}/suppliers` | List suppliers (`status`) | 200 |
| POST | `{ws}/suppliers` | Create a supplier | 201 |
| GET | `{ws}/suppliers/{supplier_id}` † | One supplier | 200 |
| PATCH | `{ws}/suppliers/{supplier_id}` † | Update name, country, city, status | 200 |
| GET | `{ws}/equipment` | List equipment (`project_id`, `category`, `criticality`, `procurement_status`) | 200 |
| POST | `{ws}/equipment` | Create equipment | 201 |
| GET | `{ws}/equipment/{equipment_id}` | One equipment record | 200 |
| PATCH | `{ws}/equipment/{equipment_id}` | Update the permitted fields | 200 |
| GET | `{ws}/purchase-orders` | List purchase orders (`project_id`, `supplier_id`, `status`) | 200 |
| POST | `{ws}/purchase-orders` | Create a purchase order with its line items, atomically | 201 |
| GET | `{ws}/purchase-orders/{po_id}` | Purchase order with supplier, line items and current commitment | 200 |
| PATCH | `{ws}/purchase-orders/{po_id}` † | Update issue date, currency, total value, status | 200 |
| POST | `{ws}/purchase-orders/{po_id}/milestones` | Add a milestone with its first plan version | 201 |
| GET | `{ws}/purchase-orders/{po_id}/milestones` | Milestones with their plan versions | 200 |
| GET | `{ws}/purchase-orders/{po_id}/milestones/{milestone_id}` † | One milestone with its plan history | 200 |
| PATCH | `{ws}/purchase-orders/{po_id}/milestones/{milestone_id}` † | Record actual date and status | 200 |
| POST | `{ws}/purchase-orders/{po_id}/milestones/{milestone_id}/plan-versions` † | Append a planned date | 201; 200 when the date is already current |
| POST | `{ws}/purchase-orders/{po_id}/commitments` | Append a supplier commitment | 201; 200 when the date is already current |
| GET | `{ws}/purchase-orders/{po_id}/commitments` | Commitment history, oldest version first | 200 |
| POST | `{ws}/ingestion/preview` | Upload, parse, validate and preview a file | 201; 200 for a file already known |
| GET | `{ws}/ingestion/batches` | List batches, newest first (`status`, `entity_type`) | 200 |
| GET | `{ws}/ingestion/sources` † | Source rows behind one canonical record (`entity_type`, `entity_id`) | 200 |
| GET | `{ws}/ingestion/{batch_id}` | One batch with its rows (`status`, `limit`, `offset`) | 200 |
| POST | `{ws}/ingestion/{batch_id}/commit` | Commit the valid rows of a previewed batch | 200 |
| GET | `{ws}/world-state` | Workspace World State | 200 |
| GET | `{ws}/world-state/summary` | Counts and data-quality summary | 200 |
| GET | `{ws}/world-state/projects/{project_id}` | Project World State | 200 |

† Not in the playbook's route inventory. Each one exposes a service operation
the playbook requires (supplier retrieve and patch, purchase-order patch,
milestone history, plan-version append, actual-date recording) or answers an
audit question it requires to be answerable ("which file supplied this
record?"). Nothing in the inventory was removed.

List orders: projects by `code`; suppliers by `supplier_code`; equipment by
`equipment_code`; purchase orders by `po_number`; milestones by lifecycle
order of the type, then `sequence_no`; versions by `version_no` ascending;
batches by `created_at` descending; batch rows by `row_number`.

## Import

### Preview

`POST {ws}/ingestion/preview`, `multipart/form-data`:

| Part | Meaning |
|---|---|
| `file` | The CSV (UTF-8, comma-separated) or XLSX file |
| `entity_type` | `project`, `supplier`, `equipment`, `purchase_order`, `purchase_order_item`, `milestone`, `supplier_commitment` |
| `sheet_name` | Optional. Required when the workbook has more than one sheet with data |

```json
{
  "batch_id": "d57a9c9c-5a62-4e75-a3dd-5fb8cb2e0e89",
  "status": "PREVIEWED",
  "entity_type": "equipment",
  "original_filename": "equipment.csv",
  "source_format": "CSV",
  "sheet_name": null,
  "file_sha256": "9f2c…",
  "duplicate_file": false,
  "total_rows": 20,
  "valid_rows": 19,
  "invalid_rows": 1,
  "planned_actions": {"CREATE": 19, "UPDATE": 0, "NO_CHANGE": 0},
  "errors_count": 1,
  "warnings_count": 1,
  "quality": {"COMPLETENESS": 0, "VALIDITY": 1, "CONSISTENCY": 0, "UNIQUENESS": 0, "REFERENTIAL_INTEGRITY": 0},
  "errors": [
    {"row_number": 8, "column": "required_on_site_date", "code": "INVALID_DATE", "message": "Use an unambiguous date in YYYY-MM-DD format."}
  ],
  "warnings": [
    {"row_number": 4, "column": "Vendor Notes", "code": "UNKNOWN_SOURCE_COLUMN", "message": "Column retained in raw source data but not mapped to a canonical field."}
  ],
  "truncated": false
}
```

- Preview writes the batch and one ledger row per source row. It writes no
  canonical record.
- `errors` and `warnings` hold at most 100 entries each; the counts are
  complete and `truncated` says whether entries were left out. Every row with
  all its issues is available from `GET {ws}/ingestion/{batch_id}`.
- `column` in an error is the canonical field; in an
  `UNKNOWN_SOURCE_COLUMN` warning it is the source header.
- `quality` counts blocking errors by data-quality dimension. It is not a
  score.
- A file that cannot be read as a table is rejected with 413, 415 or 422 and
  leaves no batch. An `entity_type` outside the list is a 422 with
  `INVALID_ENUM` on the field.
- The request body is bounded while it is read: the declared length is
  checked first, and a body sent without one is counted as it arrives.

**Same bytes again** (`duplicate_file: true`, status 200):

| Existing batch | Result |
|---|---|
| `PREVIEWED` | The same batch, re-validated against the database as it is now. This is how a file previewed before its dependencies were committed becomes committable |
| `COMMITTED` | The recorded result. Nothing is written |
| `FAILED` | Not a duplicate: a new batch is created |

The same new file sent by several clients at the same moment is one batch:
one request creates it (201) and the others are answered with it (200,
`duplicate_file: true`). The file name is display text: only its last path
segment is kept, without control characters.

### Commit

`POST {ws}/ingestion/{batch_id}/commit`, no body.

```json
{
  "batch_id": "d57a9c9c-5a62-4e75-a3dd-5fb8cb2e0e89",
  "status": "COMMITTED",
  "entity_type": "equipment",
  "replayed": false,
  "total_rows": 20,
  "valid_rows": 19,
  "invalid_rows": 1,
  "committed_rows": 19,
  "skipped_rows": 0,
  "failed_rows": 0,
  "entities": {"equipment": {"created": 19, "updated": 0, "unchanged": 0}},
  "committed_at": "2026-11-19T07:30:00Z"
}
```

- Only a `PREVIEWED` batch can be committed. `COMMITTED` means the valid
  rows were processed, not that every row was valid: the four counters keep
  valid, invalid, committed and skipped apart.
- Every valid row is checked again against the database as it is at commit
  time. If any of them fails, or a constraint rejects a write, **nothing** of
  the batch is committed: the answer is `409 COMMIT_CONFLICT` with the failing
  rows in `details`, and the batch becomes `FAILED`.
- A row is `COMMITTED` when it created or changed a record, `SKIPPED` when
  the record already held its values (`UNCHANGED`) or the row repeats an
  earlier row of the file (`DUPLICATE_ROW`). Both are linked to the record.
- Committing a `COMMITTED` batch again returns the recorded result with
  `replayed: true` and writes nothing.
- `entities` counts canonical records by kind. Milestone imports also report
  `milestone_plan_version`; commitment imports report
  `supplier_commitment_version`.
- Two commit requests for one batch are serialised by a row lock: one
  commits, the other gets the recorded result.
- A commit locks the records its rows refer to, in a fixed order, and reads
  "the latest version" only under that lock: a commitment or plan version
  appended by another request at the same time is numbered before or after
  it, never beside it.
- If PostgreSQL ends the commit to resolve a deadlock with another writer,
  the answer is `409 CONFLICT`, nothing is written and the batch stays
  `PREVIEWED`: send the commit again.

### Import order

Projects, suppliers, equipment, purchase orders, line items, milestones,
supplier commitments. A reference must exist as a committed record; a row of
another previewed batch does not count.
