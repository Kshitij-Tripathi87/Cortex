# 05 — API Design Standards

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `02-ontology.md`, `03-canonical-data-model.md`, `04-graph-and-events.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

This document freezes Cortex's HTTP API conventions and the catalog of endpoint
groups. The goal is to make every later endpoint implementable without
re-deciding conventions. Phase 1 does not enumerate every method/URL exhaustively
— it specifies the rules and the grouped shape so the catalog can be completed
deterministically in implementation.

---

## 2. Transport and shape

- HTTPS only. HTTP is redirected to HTTPS.
- JSON request and response bodies, UTF-8, no BOM.
- All requests and responses use `Content-Type: application/json; charset=utf-8`
  except file upload/download endpoints, which use `multipart/form-data` and
  `application/octet-stream` respectively.
- Snake_case for JSON field names. Enum values are lowercase snake_case.
- Timestamps are ISO-8601 UTC with `Z` suffix.
- Identifiers are stringified UUIDv7 in JSON.
- Money is `{amount: string(decimal), currency: ISO4217}`. Never float.
- Quantities are `{value: string(decimal), unit: enum}`. Never float.
- Pagination, errors, and metadata use stable, frozen wrapper shapes (§6, §7, §8).

---

## 3. Versioning strategy (frozen)

- URL path versioning: `/api/v1/...`. Major versions are integers.
- A new major version is a parallel deployment path; the old version is kept
  supported per the deprecation policy (§3.2).
- Within a major version the API is **backward-compatible only**. Additive
  changes (new optional fields, new endpoints, new enum values that clients can
  ignore) are allowed without a version bump.
- Breaking changes (renamed/removed fields, changed semantics, narrowed enums,
  changed status codes, changed auth) require a new major version.
- Every response carries `X-Cortex-API-Version: v1` (and the contract version of
  the response payload where relevant, see §4).

### 3.1 Contract vs. runtime version
- **Contract version** — the OpenAPI schema digest. Sent on responses as
  `X-Cortex-Contract: <group>:<version>`. Generated from the backend; the
  frontend client is generated from this. Drift blocks release.
- **Runtime version** — `v1`. Sent in the URL and on `X-Cortex-API-Version`.

### 3.2 Deprecation policy
- Deprecated endpoints return `Sunset` and `Deprecation` headers per RFC 8594 /
  RFC 9745. Minimum support window: 12 months after deprecation announcement.
- Removal requires a new major version.

---

## 4. Request IDs, idempotency, correlation

### 4.1 Request ID
- Clients MAY send `X-Request-ID: <uuid>`. If absent, the server generates one.
- The request id is echoed on every response as `X-Request-ID`.
- The request id is written into the audit event `request_id` field for any
  state-changing call.

### 4.2 Correlation ID
- Clients MAY send `X-Correlation-ID: <uuid>` to tie a user action to downstream
  worker events. If absent, mirror `X-Request-ID`.
- Echoed on responses as `X-Correlation-ID`.
- Used as the `correlation_id` in audit events.

### 4.3 Idempotency
- State-changing calls accept `Idempotency-Key: <client-generated-uuid>` plus an
  optional `Idempotency-Scope: <string>` (defaults to `default`).
- `(user_id, workspace_id, idempotency_key, idempotency_scope)` is unique and
  stored in the `idempotency_records` table for 24h (configurable).
- On hit, the server returns the original response body and status code; the
  audit log records a *replay* of the original `request_id`, not a new event.
- Idempotency applies to: `POST`, `PUT`, `PATCH`, and `DELETE` of an idempotent
  resource (retries). `GET` is inherently idempotent.
- Without an `Idempotency-Key`, a retried state-changing call may produce a
  duplicate; clients MUST send a key for any non-GET they cannot safely retry.

---

## 5. Authentication and workspace scoping

### 5.1 Auth strategy
- Bearer tokens (`Authorization: Bearer <jwt>`). JWTs are RS256, short-lived
  (15 min access), rotated by refresh tokens (90 day sliding, revocable).
- Service-to-service (worker → backend, ML → backend) uses short-lived
  workload-identity tokens, never long-lived secrets.
- No anonymous access. Health/readiness endpoints are the only unauthenticated
  paths and return only boolean status.
- Authn/z details and threat model in `09-security.md`.

### 5.2 Workspace scoping
- Every state-changing endpoint (and most reads) requires a workspace context.
- Sent as `X-Cortex-Workspace: <workspace_id>` header on EVERY request that
  touches workspace data.
- The backend resolves the workspace id, verifies the caller's membership and
  role, and scopes all DB queries via the `workspace_id` row-level predicate.
- Workspace id missing on a workspace endpoint ⇒ `400 invalid_request` with
  code `missing_workspace`. Workspace id present but caller lacks access ⇒
  `403 forbidden` with code `workspace_access_denied`.
- A small set of read endpoints (cross-workspace indexes for shared entities
  like supplier directories) omit the header; they are explicitly listed in §10.

### 5.3 Tenant scoping
- Tenant is implicit from the JWT claim; never user-supplied. Cross-tenant
  access is impossible: DB row-level policies use tenant id from the JWT, and
  the workspace must belong to that tenant (validated at auth time).

---

## 6. Error response format (frozen)

A single error shape is used everywhere. Multiple errors are returned together.

```jsonc
{
  "error": {
    "code": "validation_error",        // machine-readable, snake_case
    "message": "3 fields are invalid", // human-readable, stable within a major version
    "details": [
      { "field": "quantity", "issue": "out_of_range", "min": 0 },
      { "field": "currency", "issue": "invalid_currency", "allowed": ["USD","EUR","CNY"] }
    ],
    "request_id": "01HXYZ...",
    "target": "POST /api/v1/workspaces/{id}/uploads"
  }
}
```

Status codes are a closed subset:
- 200 OK, 201 Created, 202 Accepted (async), 204 No Content.
- 400 `invalid_request` (validation or schema).
- 401 `unauthenticated`.
- 403 `forbidden`.
- 404 `not_found`.
- 409 `conflict` (state conflict — including idempotency-key reuse with
  different payload).
- 422 `validation_error` (semantic — e.g. claim fails an integrity rule).
- 429 `rate_limited`.
- 500 `internal_error` (never leaks stack/internal ids beyond a correlation).
- 503 `unavailable`.

`details[*].issue` is a closed enum per error code (Phase 1 freezes the names
for the foundation errors; the rest are added via the schema registry). The
`error.code` and HTTP status pairing is frozen in §6.1.

### 6.1 Frozen code ↔ status map

| HTTP | code |
|---|---|
| 400 | `invalid_request` |
| 401 | `unauthenticated` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 409 | `conflict` |
| 422 | `validation_error` |
| 429 | `rate_limited` |
| 500 | `internal_error` |
| 503 | `unavailable` |

---

## 7. Pagination convention (frozen)

List endpoints use cursor pagination:

Request:
- `limit` — integer, default 50, max 200. Exceeding max ⇒ `400 invalid_request`.
- `cursor` — opaque string (base64url of internal paging token).
- `sort` — `<field>:asc|desc`; default endpoint-specific.
- `include_deleted=false` — soft-deleted records excluded by default.

Response wrapper:
```jsonc
{
  "data": [ ... ],
  "page": {
    "next_cursor": "eyJ...",        // null when no more
    "prev_cursor": "eyJ...",        // null at the start
    "limit": 50,
    "has_more": true
  }
}
```

Cursors are opaque and signed; clients must not construct or modify them. The
server ignores unknown sort fields with `400 invalid_request`. Pagination is
stable for a single sealed snapshot; reading "current" lists while new versions
are added is bounded by the same snapshot semantics (`04-graph-and-events.md`).

For graph neighbors/paths: same shape; `data` contains nodes and edges
grouped as `{node, edges: [...]}`.

---

## 8. Metadata and standard response headers

Every JSON response carries:
- `X-Request-ID`, `X-Correlation-ID`
- `X-Cortex-API-Version: v1`
- `X-Cortex-Contract: <group>:<version>`
- `X-Cortex-Workspace: <workspace_id>` (echoed if a workspace context was used)
- `X-Cortex-Snapshot: <snapshot_id>` (for any read that is bound to a sealed
  snapshot; null for live meta/admin reads)
- `X-Cortex-Resolved-As-Of: <iso8601>` (snapshot's `created_at` when applicable)

Resource representations do not embed pagination metadata; pagination lives in
`page`. Resource representations always include `evidence_refs` and
`provenance` where the resource is a canonical or graph object (this is the
API-level enforcement of evidence first).

---

## 9. Schema validation expectations

- Every request body is validated against the OpenAPI schema. Invalid ⇒ `400
  invalid_request` with `schema_validation_error` details.
- Every response body is validated in tests against the schema (contract tests).
- Shared DTOs (e.g., `EvidenceRef`, `Provenance`, `CanonicalAttributeEnvelope`)
  are defined once and reused across endpoint groups.

---

## 10. Audit event emission

- Every state-changing endpoint emits exactly the audit events defined in
  `04-graph-and-events.md` §11 within the same DB transaction where the state
  changes.
- Endpoints never emit audit events out-of-band without a DB state change
- recorded somewhere. Where a change lives only in object storage (e.g. an
  upload's bytes), the event is emitted after the storage write succeeds and
  carries the object's `content_hash` (binding storage and audit).
- The endpoint returns `202 Accepted` with a `Location` header pointing to a
  job-status resource whenever the change is processed asynchronously (e.g.
  upload validation, snapshot build). The job-status resource is part of the
  admin group (§13.10).

---

## 11. Endpoint groups (catalog structure)

End{oint groups map 1:1 to backend modules (`01-architecture.md` §7). Each
group has a frozen URL prefix. Within a group, CRUD+action shapes are uniform
and frozen here.

| Group | URL prefix | Module | MVP? |
|---|---|---|---|
| 1 Auth | `/api/v1/auth` | `auth` | MVP |
| 2 Workspaces | `/api/v1/workspaces` | `workspace` | MVP |
| 3 Uploads | `/api/v1/uploads` | `ingestion` | MVP |
| 4 Evidence | `/api/v1/evidence` | `ingestion` | MVP |
| 5 Claims | `/api/v1/claims` | `resolution` | MVP |
| 6 Conflicts | `/api/v1/conflicts` | `resolution` | MVP |
| 7 Reviews | `/api/v1/reviews` | `resolution` | MVP |
| 8 Entities | `/api/v1/entities` | `persistence` + `domain` | MVP |
| 9 Graph | `/api/v1/graph` | `graph` | MVP |
| 10 Snapshots | `/api/v1/snapshots` | `graph` | MVP |
| 11 Signals | `/api/v1/signals` | `intelligence` | later |
| 12 Scenarios | `/api/v1/scenarios` | `intelligence` | later |
| 13 Recommendations | `/api/v1/recommendations` | `intelligence` | later |
| 14 Decisions | `/api/v1/decisions` | `decisions` | later |
| 15 Models | `/api/v1/models` | `ml` + `admin` | later |
| 16 Admin | `/api/v1/admin` | `admin` | MVP (subset) |

### 11.1 Uniform CRUD shape (frozen)
- `GET /<prefix>` — list with pagination.
- `POST /<prefix>` — create (idempotent key supported).
- `GET /<prefix>/{id}` — read.
- `PATCH /<prefix>/{id}` — partial update with state-machine validations; no
  direct PUT of forbidden fields (immutable fields return `422
  validation_error` with `field_immutable`).
- `DELETE /<prefix>/{id}` — soft delete unless the resource is append-only
  (returns `409 conflict` with `resource_append_only` for append-only
  resources).

### 11.2 Action endpoints
- `POST /<prefix>/{id}/<action>` — perform a lifecycle transition or
  domain-specific action. Body is the action payload; response is `200 OK` with
  the updated resource or `202 Accepted` with `Location` to the job for
  long-running transitions.
- All actions are type-safe: an unknown action ⇒ `404 not_found`; an action
  illegal in the current state ⇒ `409 conflict` with `invalid_state_transition`.

---

## 12. Group-specific endpoint contracts (MVP detailed)

This section lists the concrete MVP endpoints whose shape is directly
implementable. Later-phase groups (signals/scenarios/recommendations/decisions
beyond the MVP subset) follow the same shapes; their concrete endpoints are
defined in their implementation phase, not Phase 1.

### 12.1 Auth (`/api/v1/auth`) — MVP
- `POST /token` — exchange credentials/refresh for access+refresh.
- `POST /logout` — revoke current refresh.
- `GET /me` — current user, tenants, workspaces, roles.
- `POST /workspaces/{id}/switch` — set active workspace in session.

### 12.2 Workspaces (`/api/v1/workspaces`) — MVP
- `GET /` — list workspaces the caller can access.
- `POST /` — create (admin only).
- `GET /{id}` — read.
- `PATCH /{id}` — update metadata.
- `DELETE /{id}` — archive (soft; never hard).
- `POST /{id}/members` — add member with role.
- `PATCH /{id}/members/{user_id}` — change role.
- `DELETE /{id}/members/{user_id}` — remove member.

### 12.3 Uploads (`/api/v1/uploads`) — MVP
- `POST /` — request an upload target. Returns `{upload_id, upload_url,
  method, expires_at, required_headers}`. The caller PUTs bytes to object
  storage; the server-side webhook (or the `POST /{id}/complete` callback)
  triggers parsing.
- `POST /{id}/complete` — confirm upload bytes are present (used when the
  storage provider supports an explicit finalize step).
- `GET /{id}` — status (received, validated, rejected, parsed).
- `GET /{id}/artifacts` — list extracted source objects + evidence records.
- `POST /{id}/schema-mapping` — apply or override mapping (admin role).
- `POST /{id}/revalidate` — trigger re-validation job.
- `POST /{id}/extract` — trigger extraction job.
- `GET /?status=&source_system=` — filter.

### 12.4 Evidence (`/api/v1/evidence`) — MVP
- `GET /?upload_id=&claim_id=` — list evidence.
- `GET /{id}` — read.
- `GET /{id}/content` — signed URL to the supporting bytes (valid ≤15 min).
- `GET /{id}/claims` — claims backed by this evidence.

### 12.5 Claims (`/api/v1/claims`) — MVP
- `GET /?workspace_id=&state=&entity_type=&attribute=` — list.
- `GET /{id}` — read.
- `POST /{id}/review` — request human review.
- `POST /{id}/accept` — accept (transition to canonical).
- `POST /{id}/reject` — reject with rationale.
- `POST /{id}/supersede` — replace with a new claim id (creates the new claim
  via the appropriate ingestion path; this endpoint records the supersession).

### 12.6 Conflicts (`/api/v1/conflicts`) — MVP
- `GET /?state=&severity=&entity_type=` — list.
- `GET /{id}` — read.
- `POST /{id}/resolve` — body `{chosen_claim_id, rationale}`.
- `POST /{id}/escalate` — escalate.

### 12.7 Reviews (`/api/v1/reviews`) — MVP
- `GET /?state=&assignee=` — queue.
- `POST /` — create a review task (claim or conflict).
- `POST /{id}/complete` — body `{decision, rationale}`.

### 12.8 Entities (`/api/v1/entities`) — MVP
- `GET /?type=&lifecycle_state=&q=` — list with type filter and free-text q
  against `external_ids` and `legal_name`/`name`/`sku`.
- `GET /{id}` — read full canonical entity with attribute envelopes.
- `GET /{id}/history` — version history.
- `GET /{id}/evidence` — flat evidence list for the entity (all attributes).
- `GET /{id}/lineage` — the `DERIVED_FROM` lineage subgraph.
- `POST /{id}/merge` — merge target `{into_id, rationale}`.
- `POST /{id}/split` — reverse a merge.
- Cross-workspace read endpoints: `GET /suppliers` and `GET /customers`
  optionally omit workspace header to operate against the shared party
  directory; they are read-only and require explicit `cross_workspace` role.

### 12.9 Graph (`/api/v1/graph`) — MVP
- `GET /snapshot?workspace_id=&as_of=` — latest sealed snapshot metadata.
- `GET /nodes/{id}` — node + attributes + evidence preview.
- `GET /nodes/{id}/neighbors?types=&depth=&limit=` — paginated.
- `GET /edges/{id}` — edge + evidence + derivation.
- `GET /paths?source=&target=&types=` — paths.
- `GET /impact?node_id=&types=` — forward-reachable subgraph.
- `GET /history?node_id=&from=&to=` — versions.
- `GET /diff?from=&to=` — diff.
- `POST /snapshots` — request a build (`202 Accepted` + `Location`).
- All reads bind to a sealed snapshot id (returned as `X-Cortex-Snapshot`).

### 12.10 Snapshots (`/api/v1/snapshots`) — MVP
- `GET /?workspace_id=` — list.
- `GET /{id}` — metadata.
- `GET /{id}/health` — readiness score + blocking objects.

### 12.16 Admin (`/api/v1/admin`) — MVP subset
- `GET /jobs/{id}` — job status (used by 202 responses).
- `GET /policies` — list published policy versions.
- `POST /policies` — publish a new policy version (admin only; emits
  `policy.published`).
- `GET /schema-registry` — event/contract schema versions.
- `GET /audit?workspace_id=&event_type=&from=&to=` — audit log read (admin/auditor role)

---

## 13. Later-phase group shapes (contract, not exhaustive)

These follow the same shapes and headers as above. Phase 1 fixes the group URLs
and the action vocabulary so the frontend can plan navigation without rework.

### 13.1 Signals (`/api/v1/signals`)
- CRUD uniform + `POST /{id}/acknowledge`, `POST /{id}/dismiss`, `POST /{id}/promote_event`.

### 13.2 Scenarios (`/api/v1/scenarios`)
- CRUD uniform + `POST /{id}/run` (build branch snapshot), `POST /{id}/compare`
  (against another snapshot/scenario).

### 13.3 Recommendations (`/api/v1/recommendations`)
- CRUD uniform + `POST /{id}/review`, `POST /{id}/approve`, `POST /{id}/reject`,
  `POST /{id}/implement` (creates a DecisionRecord).

### 13.4 Decisions (`/api/v1/decisions`)
- CRUD uniform + `POST /{id}/revert`, `POST /{id}/observe`, `GET /{id}/outcomes`.

### 13.5 Models (`/api/v1/models`)
- `GET /` registry, `GET /{id}` artifact metadata, `POST /{id}/promote`
  (shadow→primary, admin only; emits `ml.model.promoted`),
  `POST /{id}/shadow-start`, `POST /{id}/shadow-stop`,
  `POST /{id}/calibrate`. Read-only for non-admin roles.

---

## 14. Rate limiting and quotas

- Authenticated user rate limits per tenant and per workspace, enforced with a
  token bucket in Redis. 429 returns `Retry-After` and an
  `X-RateLimit-*` set.
- Workspace ingestion quotas (uploads per hour, total claim volume) are
  configurable per tenant. Exceeding quota ⇒ `429 rate_limited` with code
  `quota_exceeded`.

---

## 15. Cross-cutting behaviors

### 15.1 Asynchronous endpoints
- Long-running operations return `202 Accepted` with `Location: /api/v1/admin/jobs/{id}`.
- The job resource exposes `{state, progress(0..1), started_at, completed_at,
  error?, result_ref?}`. State transitions are audited.
- The client polls job status or subscribes via the internal notifications
  channel (Phase 2 may add WebSocket/SSE; Phase 1 leaves a stable polling
  contract).

### 15.2 File safety on import
- Multipart uploads are restricted to a frozen content-type allowlist and a
  per-tenant max size (`09-security.md`). Filename fields are sanitized; the
  server-generated key is the only path stored.

### 15.3 Caching and freshness
- Read endpoints may set short `Cache-Control: private, max-age=5` and respect
  `If-None-Match` for entity reads. They never cache across workspace contexts
  — `Vary: X-Cortex-Workspace, Authorization` is set on all cacheable reads.
- Snapshot-bound reads may use a strong `ETag` derived from the snapshot id.

### 15.4 Concurrency
- Optimistic concurrency on entity/edge PATCH via `If-Match: <version>`; a
  stale `version` returns `409 conflict` with `version_conflict`.

---

## 16. Frozen decisions summary

- HTTPS JSON API with URL major version `/api/v1`.
- Single error shape and frozen code↔status map.
- Cursor pagination with opaque signed cursors.
- Mandatory `X-Cortex-Workspace` header on workspace endpoints.
- Idempotency-Key support on all state-changing calls.
- Evidence/provenance always present on canonical/graph resource responses.
- Endpoint groups map 1:1 to backend modules with uniform CRUD + action shapes.
- Async work returns `202 Accepted` + `Location` to a job resource.
- OpenAPI is the single source; the frontend client is generated from it.

Phase 1 proceeds to `06-database-strategy.md` on this basis.
