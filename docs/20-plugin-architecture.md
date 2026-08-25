# 20 — Plugin / Connector Architecture

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `09-security.md` (sandbox), `15-bounded-contexts.md` (Integration context), `16-event-taxonomy.md` (T4) |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

Cortex will integrate with many external systems: SAP, Oracle, Microsoft
Dynamics, NetSuite, generic CSV/Excel, Snowflake, Kafka, S3. Without an explicit
plugin contract, these integrations become one-off adapters whose private
assumptions leak into the canonical model. Phase 1.5 freezes a **plugin /
connector contract** so each integration is built against the same boundary,
the same security model, and the same audit path.

In scope: the connector contract, lifecycle, sandboxing, schema mapping, and
the closed MVP connector catalog.
Out of scope: the implementation details of any specific connector (Phase 2
onwards, one connector at a time).

## 2. Definitions

- **Source connector** — pulls supply-chain data *into* Cortex (ingestion).
- **Sink connector** — pushes Cortex outputs *out* (exports; later phases).
- **Plugin** — the signed, versioned, registry-bound unit of code that
  implements one connector.
- **Adapter** — the in-process support library that translates a connector's
  raw artifacts into the Cortex source-object shape (BC1 native language).
- **Source-object** — the immutable Layer-A representation produced by a
  connector (the input to evidence extraction, `03` §2).

## 3. The plugin contract (frozen)

Every plugin implements a **fixed, frozen interface** so that Cortex can
install, run, sandbox, and audit it without per-plugin special handling.

### 3.1 Plugin manifest (registry record)

Stored in the plugin registry (`schema_registry.plugins`):

| Field | Notes |
|---|---|
| `plugin_id` | stable id (e.g. `sap-s4-connector`) |
| `plugin_version` | semver `MAJOR.MINOR.PATCH` |
| `connector_kind` | `source` \| `sink` |
| `target_system` | one of the catalog (§8) |
| `schema_version` | the manifest schema version |
| `signature` | signed manifest + artifact hash |
| `extractor_version` | the extractor contract version (`03` §7.1) |
| `min_runtime_version`, `max_runtime_version` | runtime compatibility |
| `owner_role` | accountable team |
| `documentation_link` | doc path |
| `installed_at`, `installed_by_ref` | audited install |
| `status` | `draft`, `registered`, `enabled`, `disabled`, `revoked` |
| `permissions` | list of capability permissions requested (§5) |

### 3.2 Plugin runtime interface (frozen)

A source connector implements:

```python
class SourceConnector(Protocol):
    plugin_id: str
    plugin_version: str

    def discover(self, ctx: ConnectorContext) -> DiscoveryResult: ...
    def fetch(self, ctx: ConnectorContext, plan: FetchPlan) -> Iterator[RawRecord]: ...
    def close(self, ctx: ConnectorContext) -> None: ...
```

- `ConnectorContext` — credentials (resolved from CF4 secrets only), tenant_id,
  workspace_id, trace context, `correlation_id`, deadlines, budgets.
- `DiscoveryResult` — the table/file/stream layout the connector can fetch.
- `FetchPlan` — what to fetch (object_refs + time window + filters + cursor).
- `RawRecord` — a normalized record batch with declared `raw_schema_ref`
  to be matched by the schema-mapping module.

A sink connector (later) implements the reverse: `discover`, `prepare`,
`dispatch`, `confirm`. The contract is symmetric for auditability.

The interface is **deliberately minimal**: connectors do not write canonical
data, do not call graph APIs, do not emit decisions, and do not call ML. They
produce/consume `RawRecord`s through the contract. The ingestion layer (BC1)
takes `RawRecord`s and runs the pipeline (`04` Part I → C1 Evidence Management).

## 4. Connector lifecycle (frozen)

```
draft → registered → enabled → disabled → revoked
```

- A connector is `registered` after manifest schema validation and signature
  verification (`09` §4).
- It is `enabled` per tenant by an admin with the `cross_workspace` /
  `tenant_admin` role; that action is a T5 audit event and is step-up gated.
- A connector that misbehaves is `disabled` first (preserves audit trail);
  `revoked` is terminal and requires security review.
- A connector cannot be silently upgraded; new `plugin_version` is a separate
  registry row bound to its own `installed_at` record and replay-eval
  expectations.

## 5. Permissions and the principle of least authority

A plugin declares a **frozen permission set** in its manifest. The runtime
checks the requested permissions against an allowlist and refuses anything else.

| Permission | What it allows | Default for source/sink? |
|---|---|---|
| `read_object_store_inbound` | read from a tenant-scoped inbound storage prefix (e.g. S3 drop bucket) | source |
| `write_object_store_inbound` | write raw records to a tenant-scoped inbound storage prefix | source |
| `external_call.<host>` | call one specific external hostname per permission entry | source per host |
| `read_secrets.<secret_id>` | read one named secret from the secrets manager | per-connector |
| `write_export_bucket` | write to a tenant-scoped outbound bucket | sink only |
| `read_workspace_scoped_records` | read BC1/BC2 records scoped by `workspace_id` for sync/reverse flows | sink only, listed under audit |
| `propose_ml_candidate` | submit ML candidates (only ML-class plugins) | ML plugins only |

Forbidden for all connectors regardless of permission:
- Direct DB grants (no `app` DB connection; reads/writes via the BC1 service
  layer only).
- Writing canonical facts, edges, audit events, decisions, or recommendations.
- Cross-tenant access — the runtime injects the principal's tenant_id and
  enforces it.
- Reading outside the bound budget (`CORTEX_CONNECTOR_*` budgets in CF1).

## 6. Sandboxing and isolation (frozen)

Per `09-security.md` §11, connectors and downstream parsers (xlsx, xml,
custom) execute in a **sandboxed runtime**:
- separate process/container per connector invocation,
- no direct DB driver,
- no network egress except entries declared in the manifest's
  `external_call.<host>` permissions; all other egress denied at the network
  policy layer,
- read-only filesystem except a per-job scratch with no execution rights,
- CPU / memory / wall-time / output size budgets enforced; exhaustion stops
  cleanly and emits `connector.budget_exhausted`,
- signed plugin artifacts loaded only after signature verification
  (`09` §4, ML's pattern adopted for all plugins).

A connector that fails validation (file type, schema, size) writes its raw
records to a tenant-scoped quarantine prefix; the records are never submitted
to evidence extraction until the tenant admin explicitly approves them.

## 7. Schema mapping (the ingestion ACL pattern)

Connectors **do not** know the canonical ontology. They declare raw schemas.
The schema-mapping module (within BC1) maps raw schema → canonical fields:

1. The connector's `DiscoveryResult` describes `raw_schema_ref` (a registered
   raw schema id).
2. The mapping module computes a default mapping from raw schema to the
   canonical alias registry (`02-ontology.md` §10).
3. An admin may publish a **mapping override** (audited, versioned) for
   tenant-supplied quirks (e.g. mapping a custom column to `legal_name`).
4. The extractor (versioned) then materializes source-objects, evidence, and
   claims per `03` §2-4. The mapping audit links the run's events to the
   raw schema id, the mapping version, and the extractor version.

This is the **Anti-Corruption Layer** for source systems: the canonical model
is defended from connector-specific quirks by the schema-mapping step, not by
per-connector workaround code.

## 8. The connector catalog (closed MVP + planned)

MVP (Phase 2 ships the contract + a generic connector first; concrete source
systems are added incrementally under the same contract).

| Target system | Connector kind | MVP? | Notes |
|---|---|---|---|
| `csv` | source | yes | Generic CSV; the canonical generic connector that proves the contract. |
| `xlsx` (no macros) | source | yes | Macro-disabled per `09` §7. |
| `json` | source | yes | NDJSON and single-doc. |
| `parquet` | source | yes | For analytical exports from stores like Snowflake. |
| `s3` | source (and later sink) | yes | Object-storage both as drop-point and as primary ingestion; first-version is source only with bounded key listing. |
| `snowflake` | source | later | Snowflake-fetch connector via the same contract; read-only SQL. |
| `kafka` | source | later | Stream connector with offsets recorded in `integration.connector_state`; at-least-once with idempotent ingestion by `idempotency`. |
| `sap` (S/4HANA / ECC) | source | later | ERP integration via OData / RFC, mapped to canonical models; phase-3 priority per enterprise demand. |
| `oracle` (E-Business / Fusion) | source | later | Same contract; XML/JSON mappings. |
| `microsoft-dynamics` (D365 F&O) | source | later | Via OData; mappings. |
| `netsuite` | source | later | SuiteTalk/REST; mappings. |
| `cortex-outbound-sink` | sink | later | Reversible export of decisions/outcomes to a partner-provided bucket. |

Adding a connector id to the catalog is an ACR plus a public plugin SDK
document; a private one-off adapter is forbidden — every adapter is a plugin
under this contract.

## 9. Plugin SDK

The Developer Platform (C11) provides a public **Plugin SDK** so external teams
can author connectors without reaching into Cortex internals:
- `cortex-plugin-sdk` library pinned to the runtime contract (§3.2).
- A local harness that mimics the sandbox (so plugin authors can develop and
  test fully offline).
- A test harness expecting every published plugin to ship connector contract
  tests (golden outputs, idempotency, budget enforcement, signature checks)
  that run in CI before registration (`10` §5).
- A connector replay harness: given a recorded connector input fixture and a
  plugin version, the same outputs are reproduced.

The SDK is the **only** sanctioned way to build a plugin; an integration built
without it cannot be registered. This is the structural enforcement of "no
private one-offs."

## 10. Operational concerns

### 10.1 Idempotency and integration events
- Each connector invocation carries a `correlation_id` and an idempotency key
  derived from `(plugin_id, plan_id, fetch_attempt)`.
- Successful ingestion writes a T4 `integration.upload.received` event; replays
  produce no duplicate canonical records (the `idempotency_records` table
  dedupes the underlying claims, `06` §11).
- Outbound `integration.outbound.dispatched` rows are written to the
  `integration.outbox` table and committed in the same transaction as the
  producing state change; the connector dispatches them post-commit and marks
  each `dispatched` after the partner's `ack`. This gives exactly-once *effect*
  semantics with at-least-once delivery.

### 10.2 Backpressure and failure
- Per-connector concurrency is bounded (CF1 + CF5 if relevant); exceeding the
  bound queues (Redis) and surfaces a `quota_exceeded` alert.
- A connector whose external call fails repeatedly transitions to a soft
  failure state (`degraded`), stops accepting new fetch plans, and alerts; an
  admin re-enables with step-up auth.
- A connector that hits a budget repeatedly is throttled and surfaced in the
  admin UI for remediation.

### 10.3 State and cursors
- Connector state (e.g. Kafka offsets, S3 last-seen keys, last-sync time) is
  stored in `integration.connector_state` keyed by `(tenant_id, plugin_id,
  workspace_id, state_key)`, encrypted with the per-tenant DEK, and updated
  atomically with the integration event. Replay can recover from the cursor up
  to the last sealed snapshot.

## 11. Audit alignment

Each connector run emits (`16-event-taxonomy.md` §6):
- T2 system events: `connector.discovery.completed`, `connector.fetch.started`,
  `connector.fetch.completed`, `connector.budget_exhausted`,
  `connector.signature_failed`.
- T4 integration events: `integration.upload.received`,
  `integration.outbound.dispatched`, `integration.delivery.confirmed`,
  `integration.partner.error`.
- The corresponding T5 audit row covers the admin action of enabling/disabling
  and any state mutation.

No connector ever writes a T1 business event directly; that emission is the
responsibility of BC1 after extraction (`16` §3.3).

## 12. Phase boundaries

- Phase 2 ships the plugin contract, the SDK, the sandbox, and the CSV/JSON/
  XLSX/Parquet/S3 source connectors. ERP/streaming connectors are added in
  later phases under the same contract.
- A Phase-2 declaration: a connector outside the closed catalog is forbidden;
  a private adapter used "while we wait for the SDK" is a release-blocking
  violation.

## 13. Frozen decisions summary

- All integrations are plugins under a frozen contract; no private adapters.
- Source connectors produce `RawRecord`s only; they never write canonical
  facts, decisions, audit events, or ML.
- Plugins are signed, sandboxed, least-authority, budget-bound; declared
  permissions checked at runtime.
- The schema-mapping module (BC1) is the ACL between raw schemas and the
  canonical ontology.
- The connector catalog is closed; adding a connector id is an ACR.
- Connector state is recoverable; outbound dispatch uses the transactional
  outbox for exactly-once-effect semantics.
