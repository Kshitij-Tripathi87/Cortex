# 16 — Event Taxonomy

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `04-graph-and-events.md` (event record + event types), `15-bounded-contexts.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze; reclassifies the existing `04` event namespace |

---

## 1. Purpose

`04-graph-and-events.md` Part II freezes the **record shape** and the **closed
namespace** of event types. That is necessary but not sufficient: a single
flat log conflates very different concerns. Phase 1.5 introduces a five-way
**taxonomy** that classifies every event type, governs how each category is
produced and consumed, and what guarantees each carries. Each event belongs to
exactly one category; the `audit_events.category` column records it.

This document does **not** redefine event types or schemas (those stay frozen
in `04`). It classifies them and binds them to category rules.

## 2. The five categories (frozen)

| Id | Category | Meaning | Storage | Who writes | Who reads |
|---|---|---|---|---|---|
| T1 | Business Events | Something happened in the supply chain, observed and recorded as a canonical operational entity or fact | canonical + audit_events.category=`business` | Deterministic detection rules; admins creating operational `Event` nodes | Decision context, UI surfaces, audit |
| T2 | System Events | Cortex itself did a meaningful internal action (a job ran, a snapshot sealed) | audit_events.category=`system` | The owning module / worker | Observability, audit |
| T3 | Domain Events | A domain object changed state across a bounded-context boundary in a way *other contexts* must react to | audit_events.category=`domain` | The owning context's service layer | Downstream context handlers (via in-process dispatcher; later a real bus if needed) |
| T4 | Integration Events | Cortex produced or consumed an event that crosses an external system boundary (a connector, a partner webhook) | audit_events.category=`integration` + an integration table | Connector plugins (BC8 + BC1) | Connector plugins, audit |
| T5 | Audit Events | Tamper-evident record of a human/system action, the *evidence* of governance (`13` Constitution) | audit_events.category=`audit` (the canonical chain) | The `audit` module, INSERT-only | Auditor role, BC8 admin, the verifier |

### 2.1 Why five and not one
A flat log makes provenance, throttling, retention, and alerting ambiguous:
- Business Events carry domain semantics and need different retention and SLO
  treatment than System Events.
- Domain Events must support fan-out/routing so other contexts react.
- Integration Events must be idempotent against external partner replays.
- Audit Events are tamper-evident and *never* flow over a bus that allows
  reordering — they are the chain itself.

Conflating them is exactly the drifting observed by AR-001.

### 2.2 Universal record shape remains
Every event of any category still uses the frozen record from `04` Part II §10
(event_id, event_type+event_version, occurred_at/recorded_at, actor, subject,
causation_id, correlation_id, request_id, job_id, payload, payload_schema_version,
policy_version, input_hash, checksum, prev_event_id, prev_event_hash). The
`category` field is added to `payload.metadata.category` (and to the
`audit_events` row's `category` column) so the taxonomy is queryable without
re-parsing payloads.

## 3. Category rules

### 3.1 T1 Business Events
- **Subject**: a canonical entity (`Event`, `Recommendation`, `DecisionRecord`,
  a supply-chain entity whose lifecycle transitioned).
- **Producers**: deterministic detection rules in BC4; admins promoting a
  signal into a confirmed operational `Event`; lifecycle transitions of
  canonical entities that constitute "something materially changed in the
  supply chain".
- **Consumers**: the UI surfaces (signals page, decisions timeline, evidence
  panel), the audit log, the BC4 handlers.
- **Guarantees**: always carries `evidence_refs`; `confidence` per `02` §12;
  `policy_version` if produced by a rule.
- **Mapping** (from `04` §11): `signal.detected`, `signal.superseded`,
  `scenario.created`, `decision.recorded`, `decision.reverted`,
  `decision.observed`, `outcome.recorded`, plus the lifecycle-changing
  `entity.*` events that materially signal supply-chain change
  (`entity.merged`, `entity.rewritten`).
- **Difference from T3**: A business event says *what happened in the supply
  chain*. The corresponding T3 domain event (if any) says *BC1 finished the
  state change so BC4 may react*. The operational `Event` entity (a node) is
  the supply-chain occurrence; the T1 row records its detection; the T3 row
  records the cross-context notification.

### 3.2 T2 System Events
- **Subject**: jobs, snapshots, readiness decisions, retention/quota, model
  signatures, chain verification.
- **Producers**: workers, the snapshot builder, the audit verifier, ML
  signature checker, retention quota enforcer.
- **Consumers**: observability stack, alerting, BC8 jobs UI.
- **Guarantees**: low cardinality; no PII; safe to aggregate for metrics.
- **Mapping**: `upload.received`, `upload.validated`, `upload.rejected`,
  `graph.snapshot.build.requested`, `graph.snapshot.sealed`,
  `graph.readiness.determined`, `ml.signature_failed`, `audit.chain_broken`,
  plus job lifecycle (`job.queued`, `job.running`, `job.completed`,
  `job.failed`).

### 3.3 T3 Domain Events
- **Subject**: a state change crossing a bounded-context boundary.
- **Producers**: the owning context's service layer, in the same DB transaction
  as the state change.
- **Consumers**: other contexts' handlers via an in-process dispatcher (Phase
  2). The dispatcher guarantees at-least-once delivery within a workspace,
  ordered by `occurred_at` within a subject id, with idempotent handlers
  enforced by `(handler_id, event_id)` dedup.
- **Guarantees**: the payload uses the *Published Language* (`15` §6) only;
  receivers must be conformist or use an ACL; handlers are idempotent.
- **Mapping**: `claim.accepted` (BC1→BC2), `entity.version_added`
  (BC2 fan-out → BC3 scenario staleness, → BC4 signal recompute),
  `graph.snapshot.sealed` is dual category (T2 system, T3 domain) — Phase 1.5
  **avoids** dual category; instead the T2 `graph.snapshot.sealed` is the
  system event and a T3 `snapshot.available` (BC2→BC3/BC4) is published when
  other contexts may react. They share a `causation_id`.
- **Routing contract**: each T3 event declares, in its payload, the set of
  target context ids. The dispatcher refuses delivery to contexts not in the
  set; this prevents implicit fan-out. A new target context requires an ACR.

### 3.4 T4 Integration Events
- **Subject**: external partner systems (ERP/WMS/TMS partners, customer SaaS,
  marketplaces, EDI gateways).
- **Producers**: connector plugins (`20-plugin-architecture.md`) on ingest;
  outbound dispatchers on export; webhooks received/returned.
- **Consumers**: connector plugins on the return path; BC8 audit.
- **Guarantees**: idempotent against partner replays via an
  `integration.outbox` table keyed by `(partner_id, external_request_id)`.
  Signed payloads; validated against the schema registry. Inbound processing
  must be isolated through `20-plugin-architecture.md` (sandbox/extraction
  ACL).
- **Mapping**: `integration.upload.received` (external), `integration.ack`,
  `integration.delivery.confirmed`, `integration.partner.error`, and the
  corresponding outbound events (`integration.outbound.dispatched`).
- **Difference from T1**: integration events are about *transport to/from a
  pattern*; the corresponding T1 Business Event is about *what happened in
  the supply chain because of that transport*. The integration event
  `causation_id`s through to the T1 business event it caused.

### 3.5 T5 Audit Events
- **Subject**: a human or system action whose record **is** governance
  evidence (`13` Principle 6).
- **Producers**: the `audit` module, INSERT-only, in the same DB transaction
  as the underlying state change (or after object-storage write for storage
  events, with content_hash binding).
- **Consumers**: auditor role; BC8 audit read (`15` §5.5); the hash chain
  verifier.
- **Guarantees**: append-only, hashed-chained, INSERT-only at the grant level,
  retained ≥ tenant policy; deletion only by the `retention` role with its
  own signed audit event.
- **Mapping**: this category overlaps with many T2/T3/T4 events because *every*
  state change is audited. The distinction is **structural**: each row's
  `category=audit` slice **is** the audit copy; the same logical event also
  appears under its operational category. The audit verifier only considers
  rows with `category=audit`.
- **Rule**: every state-changing operation writes **exactly one** T5 row in the
  same DB transaction. It MAY also publish the corresponding T2/T3/T4 row;
  the T5 row causation-chains back to none and is referenced by the others via
  `causation_id`. The chain is built over T5 rows only.

## 4. Cross-category rules

1. **One audit row, optionally one operational row.** A mutation must emit a
   T5. It may emit a parallel T1/T2/T3/T4 row for the same logical action; the
   parallel row sets `causation_id = <audit event_id>` and inherits
   `correlation_id`.
2. **The chain is over T5 only.** Ordering over T1/T2/T3/T4 is not guaranteed
   by the chain; the dispatcher guarantees in-process order for T3 only.
3. **Routing is explicit.** T3 events declare their target contexts; T4 events
   declare their partner id; neither may broadcast.
4. **Idempotency** (T3 dispatcher, T4 integration): handlers deduplicate by
   `(handler_id, event_id)` and `(partner_id, external_request_id)`
   respectively.
5. **No dual category.** An event has exactly one `category`. Where a state
   change has both an operational meaning and an audit meaning, two rows are
   emitted, chained by `causation_id`.
6. **No ML writes any event.** ML never emits any event of any category
   (`13` Principle 1, `08` §15).

## 5. Classification correctness

A classification is correct if it satisfies:

- A Business Event (T1) has a canonical subject that exists after the event.
- A System Event (T2) does not carry a domain subject that becomes a
  canonical entity.
- A Domain Event (T3) crosses a context boundary and is targeted to specific
  consuming contexts.
- An Integration Event (T4) crosses an external boundary.
- An Audit Event (T5) has an actor and is the audit record of a mutation.

A linter checks classification at the producer code level by asserting each
`emit_*` call passes the correct category constant. Misclassification fails CI
(`10` §5).

## 6. Re-mapping the `04` namespace (frozen lookup)

The frozen re-mapping of `04-graph-and-events.md` §11 types into categories.
This table is the authoritative labeling; mismatches elsewhere in the package
resolve to this table.

| Event type (from `04` §11) | Category | Notes |
|---|---|---|
| `upload.received` | T2 system | |
| `upload.validated`, `upload.rejected` | T2 system | |
| `schema_mapping.applied` | T5 audit (+ T2 system row optional) | governance-recorded |
| `evidence.extracted` | T2 system | |
| `claim.created` | T2 system | |
| `claim.validation_issue` | T5 audit | |
| `conflict.detected` | T5 audit (+ T1 optional when material) | |
| `conflict.resolved` | T5 audit | human action |
| `claim.review.requested`, `claim.review.completed` | T5 audit | human action |
| `claim.accepted`, `claim.rejected`, `claim.superseded` | T5 audit + T3 domain (BC1→BC2) | audit + fan-out |
| `entity.created`, `entity.version_added`, `entity.lifecycle_changed` | T1 business + T5 audit + T3 domain (BC2 fan-out) | material supply-chain change + audit + downstream notify |
| `entity.merged`, `entity.rewritten` | T1 business + T5 audit + T3 domain | |
| `edge.created`, `edge.version_added`, `edge.superseded` | T1 business + T5 audit | material graph changes; T3 to consumers if any |
| `graph.snapshot.build.requested` | T2 system | |
| `graph.snapshot.sealed` | T2 system (+ T3 `snapshot.available` for BC3/BC4) | system + fan-out |
| `graph.readiness.determined` | T2 system + T5 audit (decision of `no_action`) | first entry in BC4 |
| `signal.detected`, `signal.superseded` | T1 business + T5 audit | supply-chain occurrence |
| `scenario.created`, `scenario.updated`, `scenario.archived` | T5 audit | human action; T1 if material |
| `recommendation.proposed` | T5 audit + T1 business | proposal recorded |
| `recommendation.review.requested` | T5 audit | |
| `recommendation.approved`, `recommendation.rejected` | T5 audit + T1 business | human decision |
| `recommendation.superseded` | T5 audit + T1 business | |
| `recommendation.implemented` | T5 audit + T1 business | creates BC4 DecisionRecord |
| `decision.recorded`, `decision.reverted`, `decision.observed` | T5 audit + T1 business | the audit arc + the operational arc |
| `outcome.recorded` | T1 business + T5 audit | loop closure |
| `workspace.created`, `workspace.updated`, `workspace.archived` | T5 audit (+ T1 only if material operational intent) | |
| `user.invited`, `user.role_changed`, `user.deactivated` | T5 audit | always governance |
| `policy.published` | T5 audit + T3 domain (BC8→BC1..BC7) | governance + downstream policy update |
| `ml.model.promoted`, `ml.model.rollback`, `shadow_started`, `shadow_stopped` | T5 audit + T2 system | |
| `ml.candidate.proposed` | T4 integration (ML is an external subsystem per `15` §3 source) + T5 audit | the candidate ACL is an integration boundary |
| `integration.*` | T4 integration | new types added by connectors |
| `job.*` (queued/running/completed/failed) | T2 system | |
| `audit.read` | T5 audit | reading audit is itself audited |
| `audit.chain_broken`, `audit.storage_checksum_broken` | T2 system (anomaly) | anomalies system-but-governance-critical |

Chapter 6 above is the single label source. Each row counts as exactly one
`category` value, even if multiple rows are emitted for the same logical
action — they are *distinct rows*, linked by `causation_id`.

## 7. Retention and routing by category (frozen defaults)

| Category | Default retention | Routing |
|---|---|---|
| T1 business | tenant policy (≥7y) | BC8 audit read; BC4 handlers |
| T2 system | 90d operational, ≥7y for `*.failed`, `chain_broken` | observability; alerting |
| T3 domain | n/a (transient) + audit copy ≥7y | in-process dispatcher per workspace |
| T4 integration | ≥7y (partner contracts) | connector plugins; outbox |
| T5 audit | ≥7y (tenant policy) | auditor; chain verifier |

Retention cross-cuts the partition scheme (`06` §12): partitions are by month
per category; the `retention` role drops old partitions per the policy, after a
`retention_run` audit event is signed by the separate retention key.

## 8. Observability hooks

Each category carries a metric (`22-observability-model.md`):
- `cortex_business_events_total{event_type, workspace_id}`
- `cortex_system_events_total{event_type}`
- `cortex_domain_events_total{event_type, target_context_id}`
- `cortex_integration_events_total{event_type, partner_id}`
- `cortex_audit_events_total{event_type, workspace_id}`

Cardinality is bounded per `11-deployment.md` §7.2.

## 9. Frozen decisions summary

- Five categories (T1–T5) classify every event; each event has exactly one
  category recorded on the row.
- The universal record shape from `04` Part II is preserved; only the
  classification is added.
- Audit (T5) is the only category that participates in the hash chain and is
  the governance record of every mutation.
- T3 domain events route to declared target contexts only; the dispatcher is
  at-least-once with idempotent handlers.
- T4 integration events are idempotent against partner replays via the outbox.
- ML never emits any event category; ML candidates arrive as T4 integration
  candidates through the BC7→BC1 ACL.
- The frozen classification table in §6 is the authoritative label source.
