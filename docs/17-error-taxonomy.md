# 17 — Error Taxonomy

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `05-api-standards.md` (error shape + code↔status map), `15-bounded-contexts.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

The error shape in `05-api-standards.md` §6 is frozen, but a single shape is
not enough: errors must be raised consistently, map to a fixed internal
hierarchy, carry semantics that downstream handlers (UI, retries, alerts) can
act on, and never leak internals. This document freezes a **closed error
taxonomy** that any module may raise. Every API error is an instance of exactly
one class; every class has a fixed mapping to the `error.code` and HTTP status
from `05-standards.md` §6.1.

## 2. The closed error hierarchy

Errors form a rooted tree. The namespace is `CortexError`; subclasses are
the ones AR-001 listed plus the Ses a separation-required additions. There are
nine leaf classes (the exposed taxonomy) and two superclasses for grouping.

```
CortexError (root, abstract)
├─ OperationalError     (abstract)         → 5xx family normally (per subclass)
└─ ClientError          (abstract)         → 4xx family (per subclass)
   ├─ ValidationError
   │  ├─ SchemaValidationError
   │  └─ SemanticsValidationError
   ├─ ConflictError
   │  ├─ StateConflictError
   │  ├─ VersionConflictError
   │  ├─ IdempotencyConflictError
   │  └─ DuplicateConflictError
   ├─ EvidenceError
   ├─ GraphError
   ├─ ScenarioError
   ├─ SecurityError
   │  └─ PermissionError
   ├─ SystemError
   └─ InfrastructureError
```

`SecurityError` is a subclass of `ClientError` because most security failures
are 4xx (`401`/`403`); a `SecurityError` that turned out to be evidence/audit
tampering is actually a 5xx with an **anomaly alert**, raised separately (see
§10) — the user-visible response is still 403 or 422, plus a TamperAnomaly row.

## 3. Per-class definition (frozen)

Each row fixes: when it is raised, the `error.code` value, the HTTP status, the
`details[*].issue` enum it consistently uses, and what the UI should do.

### 3.1 ValidationError — `400 invalid_request`
- **Cause**: request body failed schema or value validation, including missing
  required fields, malformed units or currencies, wrong enum values.
- **Subclasses**:
  - `SchemaValidationError` (`issue` ∈ {`schema_validation_error`,
    `missing_required`, `type_mismatch`}).
  - `SemanticsValidationError` (`issue` ∈ {`out_of_range`,
    `negative_quantity`, `future_timestamp`, `invalid_country`,
    `invalid_currency`, `invalid_format`, `unit_not_in_registry`,
    `eta_before_etd`}). For 422-class semantic-violation cases that fail a
    Contract (`02` §13 / `03` §8), the wire status is `422 validation_error`
    and the code becomes `validation_error` (`05` §6.1). The Python class
    stays `SemanticsValidationError`; the serializer chooses HTTP 400 vs 422
    by `severity` on the field.
- **UI**: inline form errors by `field`; unknown fields rendered at form top.

### 3.2 ConflictError — `409 conflict` (subclass-dependent variants)
- **Cause**: an impotent action — the request would double-execute or
  contradict committed state.
- **Subclasses**:
  - `StateConflictError` (`issue` ∈ {`invalid_state_transition`,
    `resource_append_only`}).
  - `VersionConflictError` (`issue = version_conflict`), caused by stale
    `If-Match`; UI invalidates and prompts.
  - `IdempotencyConflictError` (`issue = idempotency_in_flight`), caused by
    concurrent key reuse; UI surfaces "operation in progress".
  - `DuplicateConflictError` (`issue = duplicate_external_id`,
    `duplicate_identity`), caused by uniqueness collision; UI directs to the
    existing resource or the conflict triage page.
- **UI**: deterministic per subclass; never a generic "Try again".

### 3.3 EvidenceError — `422 validation_error` (governance)
- **Cause**: a candidate claim, evidence, or derivation violates the evidence
  contract (e.g. orphan evidence, missing provenance, ML candidate above
  `0.5`, lineage cycle, depth beyond the ≤3-hop rule).
- **Issue enum**: `evidence_missing`, `provenance_incomplete`,
  `ml_confidence_overflow`, `derived_cycle`,
  `lineage_depth_exceeded`, `unresolved_evidence_ref`.
- **UI**: the offending write surfaces in the evidence panel; the user is
  never allowed to bypass. The audit log records the rejection.

### 3.4 GraphError — `422 validation_error`
- **Cause**: graph-level contract violations (`02` §9.2):
  type-mismatched endpoints, self-loops, orphan refs, recursive query depth
  beyond `CORTEX_GRAPH_MAX_LIVE_DEPTH`, validation failures during snapshot
  sealing, `DERIVED_FROM` cycle.
- **Issue enum**: `edge_type_mismatch`, `self_loop`,
  `graph_orphan_ref`, `query_too_deep`, `edge_no_evidence`,
  `derived_cycle`, `snapshot_seal_invalid`, `target_context_forbidden`.
- **UI**: deterministic; deep-query errors prompt "Refine filter / Load more".

### 3.5 ScenarioError — `409 conflict` / `422 validation_error`
- **Cause**: a scenario tried to mutate mainline, an assumption carried no
  evidence, an override used vocabulary outside the published language, a
  branch snapshot is unusable.
- **Issue enum**: `mainline_mutation_forbidden`, `assumption_no_evidence`,
  `override_outside_vocabulary`, `branch_snapshot_unusable`.
- **UI**: blocks scenario run with an actionable message.

### 3.6 SecurityError — `401 unauthenticated` / `403 forbidden` / `429 rate_limited`
- **Cause**: authn failure, authz failure, step-up required, rate limit,
  quota exceeded, invalid workspace id, unsafe-upload attempt at the security
  gate.
- **Issue enum**: `unauthenticated`, `step_up_required`,
  `forbidden`, `workspace_access_denied`, `rate_limited`, `quota_exceeded`,
  `sensitive_action_not_allowed`.
- **PermissionError** (subclass): specifically the `403 forbidden` cases
  above; it is the only error raised inside the permission matrix and is
  never retried silently by the client.
- **UI**: 401 triggers refresh; 403 surfaces reason + workspace switcher;
  429 with `Retry-After` shows a transient banner.

### 3.7 SystemError — `500 internal_error`
- **Cause**: a code-level invariant violation; an unhandled exception; a
  serialization failure. The user sees no internals — only a `request_id` to
  copy and `internal_error`.
- **Constraint**: SystemError MUST be rare in production. Its count is an SLO
  input (`22-observability-model.md`); spikes trigger paging.
- **Leak guard**: the serializer never includes stack traces, internal ids
  beyond correlation, or row contents.
- **UI**: a deterministic error page with the `request_id` and a copy button.

### 3.8 InfrastructureError — `503 unavailable`
- **Cause**: a dependency is unavailable (DB pool saturated, Redis
  unreachable, object storage 5xx). The backend still answers — it does not
  hang the request beyond the `CORTEX_QUERY_TIMEOUT_MS`.
- **Constraint**: emits a structured health signal; the load balancer's
  readiness gate pulls `/readyz` based on this; envoy-level circuit breakers
  back off.
- **UI**: a "Platform temporarily unavailable" page with a retry countdown;
  retry honors `Retry-After` when present.

## 4. `details[*]` structure (frozen expansion)

`05-api-standards.md` §6 fixed the envelope. Phase 1.5 fixes what `details[]`
contains so every UI is implementable without guessing:

```jsonc
"details": [
  {
    "field": "request.body.shipments[0].eta",   // dotted JSON path
    "issue": "eta_before_etd",                   // closed enum per class
    "constraint": "eta >= etd",                    // human-readable predicate
    "min": null, "max": null, "allowed": null,     // as applicable
    "evidence_ref": null,                          // for EvidenceError only
    "snapshot_id": null,                           // for GraphError context
    "policy_version": null,                        // for determinism errors
    "remediation": "Provide eta >= etd at the same path"
  }
]
```

- `issue` and its closed-enum membership are validated in tests (`10` §5).
- `remediation` is mandatory for ValidationError, EvidenceError, GraphError,
  ScenarioError; optional otherwise.
- `field` uses the JSON Pointer / dotted path of the offending field; for
  errors that are not field-specific, `field` is null and `issue` is the
  subject (e.g. `ml_confidence_overflow` references `claim_id` in `evidence_ref`).

## 5. Mapping of internal class → wire

| Class | `error.code` (`05` §6.1) | HTTP |
|---|---|---|
| SchemaValidationError / SemanticsValidationError (≤) | `validation_error` | 422 |
| SchemaValidationError / SemanticsValidationError (>) | `invalid_request` | 400 |
| ValidationIssue in `details` w/ `severity=major`/`critical` | `validation_error` | 422 |
| StateConflictError / VersionConflictError / IdempotencyConflictError / DuplicateConflictError | `conflict` | 409 |
| EvidenceError | `validation_error` | 422 |
| GraphError | `validation_error` | 422 |
| ScenarioError (state variants) | `conflict` | 409 |
| ScenarioError (validation variants) | `validation_error` | 422 |
| SecurityError (authn) | `unauthenticated` | 401 |
| SecurityError (authz) | `forbidden` | 403 |
| SecurityError (rate) | `rate_limited` | 429 |
| SystemError | `internal_error` | 500 |
| InfrastructureError | `unavailable` | 503 |

`error.code` is a frozen facet of the API; it cannot be subclassed without an
ACR. The mapping above is the only legal mapping; clients must not branch on
`error.message`.

## 6. Discipline for raisers

1. **Raise the most specific class.** A module raising `CortexError` directly
   fails the type-check / lint gate (`10`).
2. **Always pass `details` when structurally available.** A ValidationError
   without `details[]` is treated as missing required data.
3. **Never raise a ValidationError for a ConflictError situation.** If the
   state is legal but contradicts committed state, raise ConflictError.
4. **Never swallow SecurityError.** Raising and returning a 200 in lieu of a
   SecurityError is a release-blocking test failure.
5. **Distinguish client vs. platform.** A `SystemError` raised where the user
   could have done something is misclassified; a `ValidationError` raised
   where the platform crashed is misclassified. The severity is the
   reviewer's first read.
6. **Carry the request id.** The error envelope's `request_id` is filled by
   the central handler from the request context, never by raisers.

## 7. Central error handler (placement)

A single FastAPI exception handler in `api/errors.py` (thin orchestration layer)
translates any `CortexError` subclass to the wire envelope, emits an audit T5
event where the underlying state changed, attaches the request id, and logs the
structured error. Other modules raise; only the central handler responds. This
is the wire boundary for the `13` Principle 1 (no silent failure) etc.

## 8. Frontend treatment

The frontend's `lib/errors/` map implements the deterministic UI behavior
listed in §3. It is generated alongside the OpenAPI client where plausible
(error `code` is a closed enum in OpenAPI); for `issue` enums, the generator
emits TypeScript union types per class so unknown issues are a compile error.

## 9. Cross-language consistency

Contract tests (`10` §5) assert:
- every endpoint's documented error responses exist as examples in OpenAPI;
- contract test runs hit each documented error code path on each endpoint that
  may raise it (failure to test an error path fails closure of the contract);
- `details[*].issue` values are drawn from the frozen enums only; new `issue`
  values are added by ACR via the schema registry.

## 10. Anomaly and security escalation

Two error situations are **not** classified as the above and follow a separate
path:

- **TamperAnomaly** — audit chain mismatch, evidence content-hash mismatch,
  RLS violation. The user-facing response is the closest legal class
  (typically `SecurityError` 403 or `EvidenceError` 422). The backend *also*
  emits a `T2 system` anomaly event (`audit.chain_broken`,
  `audit.storage_checksum_broken`, `cortex_rls_violation_total > 0`), raises
  the security on-call alert, and refuses to proceed with the affected record
  until verified.
- **DeterminismAnomaly** — replay drift (`input_hash` mismatch on a sealed
  snapshot/signal/recommendation). Not surfaced to the user beyond a
  `SystemError` 500; the platform side effect is a release-blocking alert
  and a freeze on the affected policy version.

Anomaly handling is non-negotiable per Constitution Principle 8 (Security by
default) and Principle 4 (Determinism over hidden heuristics).

## 11. Frozen decisions summary

- Closed tree with nine leaf classes; raisers must raise the most specific.
- Each class has a fixed → `error.code` and → HTTP mapping; `error.code`
  stays the closed enum from `05` §6.1.
- `details[*]` structure frozen, with `remediation` mandatory for the
  operational classes.
- Only the central error handler responds; raisers raise and never format the
  envelope.
- Anomalies (Tamper, Determinism) follow a separate path: closest legal user
  class + paging alert + freeze.
- Frontend error behavior is code-generated from the OpenAPI enum facets.
