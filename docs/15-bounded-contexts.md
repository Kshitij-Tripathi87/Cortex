# 15 — Bounded Context Map

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `14-business-capabilities.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

Domain-Driven Design (DDD) prevents the coupling that destroys large platforms.
This document freezes the bounded contexts, their ownership, inputs, outputs,
dependencies, and the anti-corruption layers (ACLs) between them. Phase 2
implements against these contracts; any module that needs another context's data
goes through the published contract, never through private tables.

A bounded context is closer to a *language boundary* than to a capability: it is
the region in which a term has exactly one meaning. Capabilities
(`14-business-capabilities.md`) own product value; bounded contexts own
language. A capability may span one or more contexts; here, the mapping is
intentionally close (with the ML Platform capability split across the ML
Context and the Developer Platform's plugin contract surface).

## 2. The eight contexts (frozen set)

| Id | Context | Owning capability | Native aggregates |
|---|---|---|---|
| BC1 | Evidence Context | C1 | Upload, SourceObject, Evidence, Claim, Conflict, Review |
| BC2 | Operational Graph Context | C2 + C3 | CanonicalEntity, CanonicalAttribute, Node, Edge, Snapshot, Diff |
| BC3 | Simulation Context | C4 | Scenario, Assumption, BranchSnapshot, Comparative |
| BC4 | Decision Context | C5 + C6 | Signal, Recommendation, DecisionRecord, Outcome |
| BC5 | Identity Context | C9 | Tenant, User, Membership, Role, ApiKey, RefreshToken |
| BC6 | Workspace Context | C8 + C9 | Workspace, WorkspaceMember, WorkspaceIsolation |
| BC7 | ML Context | C7 | Dataset, Feature, Experiment, Model, ModelVersion, Candidate |
| BC8 | Administration Context | C8 | PolicyVersion, SchemaRegistry, Job, AuditEvent (admin read) |

Notes:
- The `Event` operational entity from `02-ontology.md` lives in **BC4** (it is
  first-class in decisions/signals), not in BC1's audit event log.
- `AuditEvent` is cross-cutting; it is *written* by every context but *defined*
  in BC8 for admin reads; the canonical append-only shape from
  `04-graph-and-events.md` Part II is the contract all contexts emit into.
- The assuming of "workspace context" inside every request is the BC6 read
  path; every context owns a workspace predicate but does not own workspace
  definition.

## 3. Context relationship map (DDD inter-context patterns)

The relationship patterns are the standard DDD set, fixed for each pair:

- **U/D** — Upstream/Downstream (the upstream publishes a contract; downstream
  consumes it without negotiation).
- **OHS** — Open Host Service (a published, versioned API).
- **PL** — Published Language (a stable, versioned DTO schema).
- **CF** — Conformist (downstream conforms to upstream's model fully).
- **ACL** — Anti-Corruption Layer (downstream translates upstream models into
  its own language; **mandatory** where strangers meet).
- **CS** — Customer/Supplier (downstream has a voice in the upstream contract;
  used only for tight internal pairs).

Frozen pairwise map (only non-trivial pairs listed):

```
BC1 Evidence ──OHS/PL──> BC2 Operational Graph         (conformist to ontology + canonical model)
BC2 Operational Graph ──OHS/PL──> BC3 Simulation        (Simulation is conformist; ACL prevents model drift)
BC2 Operational Graph ──OHS/PL──> BC4 Decision          (ACL; Decision only consumes snapshots)
BC3 Simulation ──OHS/PL──> BC4 Decision                  (ACL; recommendations reference scenarios)
BC4 Decision ──ACL──> BC7 ML                              (one-way; ML candidates cross ACL only via defined candidate API)
BC1 Evidence ──OHS/PL──> BC4 Decision                    (Decision may use evidence refs read-only)
BC5 Identity ──OHS/PL──> every other context              (each context consumes identity + workspace read-only; no back-flow)
BC6 Workspace ──OHS/PL──> every stateful context          (workspace scope predicate; isolation enforced by RLS)
BC7 ML ──ACL──> BC1 Evidence                              (ML candidates enter evidence context only as claims via the ingestion ACL)
BC8 Administration ──CS──> BC1..BC7                       (Admin contracts are co-designed with the owning context; ACL on audit reads)
```

Visually, BC2 Operational Graph is the gravitational center; BC1 is its
upstream; BC4 is its primary downstream; BC7 connects only to BC1 (downstream
ACL) and BC4 (upstream one-way candidate). The audit log (BC8 admin view) is
written by all, read through BC8.

## 4. Context definitions (ownership, inputs, outputs, dependencies)

### BC1 — Evidence Context
- **Ownership**: C1 Evidence Management.
- **Native language**: upload, source_object, evidence, claim, conflict, review,
  validation_issue, schema_mapping.
- **Inputs**: external files (uploads), schema-mapping overrides, review decisions.
- **Outputs**: accepted claims promoted to BC2 via the canonicalizer; audit
  events; ML candidates submitted from BC7 via the ACL.
- **Dependencies upstream**: BC5 (authn/z on uploader/reviewer), BC8 (schema
  registry for extractor/normalizer version lookups), BC6 (workspace scope).
- **Published**: `POST /uploads`, `GET /evidence`, `GET /claims`, `/conflicts`,
  `/reviews` (OHS); Claim/Evidence DTOs (PL).
- **ACL obligations**: refuses to accept ML candidates except in
  `pending_review` with `confidence ≤ 0.5` and source_system `ml_candidate`.

### BC2 — Operational Graph Context
- **Ownership**: C2 Operational Modeling + C3 Graph Intelligence.
- **Native language**: canonical entity, attribute envelope, edge, node,
  snapshot, diff, lineage.
- **Inputs**: accepted claims from BC1; admin-promoted policy versions from BC8.
- **Outputs**: sealed snapshots to BC3/BC4; canonical reads to BC8 audit; the
  `graph.readiness.determined` decision (the first decision in BC4).
- **Dependencies upstream**: BC1 (claims), BC8 (policy versions), BC5, BC6.
- **Published**: `GET /entities`, `/graph`, `/snapshots` (OHS); CanonicalEntity,
  Edge, Snapshot DTOs (PL).
- **ACL obligations**: canonical ids are the only identity crossing to BC3/BC4;
  raw claims or evidence are **not** hand-shared (BC3/BC4 fetch evidence via BC1
  read APIs when needed for explanations, with provenance preserved).

### BC3 — Simulation Context
- **Ownership**: C4 Operational Simulation.
- **Native language**: scenario, assumption, branch snapshot, override, comparative.
- **Inputs**: a sealed base snapshot id from BC2; typed param_overrides; admin
  policy version.
- **Outputs**: sealed branch snapshots; diff records to BC4.
- **Dependencies**: BC2 (read-only snapshots), BC6, BC5.
- **Published**: `POST /scenarios`, `/{id}/run`, `/compare` (OHS).
- **ACL obligations**: a scenario never mutates mainline; `param_overrides` and
  `assumptions` are translated through an ACL from BC2's canonical attribute
  vocabulary to BC3's override vocabulary (typed mirrors; no shared mutable state).

### BC4 — Decision Context
- **Ownership**: C5 Decision Support + C6 Decision Memory.
- **Native language**: signal, recommendation, decision_record, outcome,
  operational event, revert.
- **Inputs**: sealed snapshots from BC2; scenarios from BC3 (optional); ML
  candidates from BC7 via the ACL; user approvals/rejections.
- **Outputs**: signals/recommendations to users; decisions/outcomes to BC2
  (via `decisions.reverted`/`decisions.observed` only — Decision never writes
  free-form canonical state).
- **Dependencies**: BC2, BC3, BC7 (ACL one-way), BC5, BC6, BC8 (policy version).
- **Published**: `GET/POST /signals`, `/recommendations`, `/decisions` (OHS).
- **ACL obligations**: the ML candidate ACL is the most critical
  (`13-constitution.md` Principle 1). Candidates enter the explanation with a
  capped confidence and a fixed provenance shape; an ML candidate can never be
  the deciding input alone, and the explanation must record
  `ml_candidate_ref`.

### BC5 — Identity Context
- **Ownership**: C9 Identity & Security.
- **Native language**: tenant, user, membership, role, api_key, refresh_token,
  workload_identity.
- **Inputs**: credentials/refresh/@integration tokens; admin provisioning.
- **Outputs**: a resolved principal at every API/authz decision; workspace
  scoping data to BC6.
- **Dependencies**: foundation only; no upstream business contexts.
- **Published**: `POST /auth/token`, `/auth/me`, `/workspaces/{id}/switch` (OHS).
- **ACL obligations**: Identity is upstream to everyone, conformist
  consumption only; identity data never reflows into business contexts except
  via the principal resolver and audit `actor_id` reference.

### BC6 — Workspace Context
- **Ownership**: C8 Platform Administration + C9 for isolation enforcement.
- **Native language**: workspace, workspace_member, scope_predicate,
  isolation_guarantee.
- **Inputs**: admin provisioning; the active `X-Cortex-Workspace` header per
  request.
- **Outputs**: resolved `workspace_id` to every stateful context's DB session.
- **Dependencies upstream**: BC5 (principal).
- **Published**: `/workspaces*` admin endpoints; the `X-Cortex-Workspace`
  header contract.
- **ACL obligations**: every context adopts the workspace predicate as a
  conformist contract; no context keeps a private workspace mapping.

### BC7 — ML Context
- **Ownership**: C7 ML Platform.
- **Native language**: dataset, feature, experiment, model_version,
  shadow_inference, candidate.
- **Inputs**: read-only snapshots from BC2; admin policy version from BC8;
  training compute and data budgets.
- **Outputs**: **candidates** only, submitted through the BC1 ACL as
  `pending_review` claims; signed artifacts to the registry; calibration records.
- **Dependencies upstream**: BC2 (read-only), BC8 (policy + admin), BC5, BC6.
- **Published**: `/models*` (admin); the candidate submission API consumed only
  by BC1 (ACL).
- **ACL obligations**: candidates are constrained to `confidence ≤ 0.5`, signed
  provenance, and the BC1 ingestion ACL. No direct BC7→BC4/BC2 write path
  exists.

### BC8 — Administration Context
- **Ownership**: C8 Platform Administration; cross-context audit log admin
  view owned jointly with C9.
- **Native language**: policy_version, schema_registry, job, audit_log (admin
  read view).
- **Inputs**: admin actions (policy publish, schema publish, job management).
- **Outputs**: published policy versions to BC1/BC2/BC3/BC4/BC7; job lifecycle
  signals; audit read access.
- **Dependencies upstream**: BC5 (authn/z + admin roles); every context publishes
  its schema versions into BC8.
- **Published**: `/admin/policies`, `/admin/schema-registry`, `/admin/audit`,
  `/admin/jobs/{id}` (CS where applicable; ACL on audit reads).
- **ACL obligations**: audit log reads are workspace-scoped; cross-workspace
  audit reads require the tenant auditor role and are themselves recorded as
  `audit.read` events.

## 5. Anti-corruption layer contracts (frozen)

Where the map mandates an ACL, the ACL contract is fixed as a *translation only*
boundary. Phase 1.5 freezes the shape; concrete translators are implemented in
Phase 2 once per interface.

### 5.1 BC7 → BC1 ML candidate ACL
- Surface: `POST /internal/ml/candidates` (internal, mTLS-only, not public).
- Translator: enforces `source_system = ml_candidate`, `claim_state =
  pending_review`, `confidence ≤ 0.5`, signs provenance with the model version
  key, and rejects anything claiming an existing canonical id by value.
- Tests: any candidate violating the constraints is rejected; any second
  candidate on the same attribute does not auto-supersede a human-accepted
  claim; the ACL must record the rejection in BC7.

### 5.2 BC2/BC3 Simulation ACL
- Surface: BC3 reads `GET /graph/snapshots/{id}` and `GET /entities/{id}` (OHS)
  only; mainline write paths are not available to BC3.
- Translator: converts BC2 canonical attribute names into BC3 override
  vocabulary using the schema registry; rejects overrides outside the published
  vocabulary.

### 5.3 BC1 → BC2 canonical promotion ACL
- Surface: BC1 calls `promote_to_canonical(claim_id)` (internal service layer).
- Translator: enforces identity, uniqueness, evidence, and validation
  constraints from `02-ontology.md` §13 and `03` §8/§11; rejected promotions
  stay `pending_review` with an attached issue; accepted promotions append a
  versioned canonical record and emit `entity.created`/`entity.version_added`.

### 5.4 BC4 → BC7 candidate authorization ACL (one-way)
- Surface: BC4 may *read* candidate metadata via `GET /ml/candidates/{id}` for
  explanation, never write; BC7 never reads BC4 policy code.
- Translator: refuses any path that would let an ML candidate produce a
  recommendation without a deterministic rule and at least one non-ML evidence
  ref.

### 5.5 BC8 audit read ACL
- Surface: `GET /admin/audit?workspace_id=&...`.
- Translator: enforces the tenant auditor role, scopes rows to the workspace
  unless tenant auditor role is present, and emits the `audit.read` event
  itself.

## 6. Shared language (intentionally limited)

Only a tiny set of terms crosses all contexts unchanged. These are the frozen
*ubiquitous language* every context conforms to; all other terms are private to
their context.

- `tenant_id`, `workspace_id`, `user_id` — identity scoping (`05` §5).
- `entity_id`, `claim_id`, `evidence_id`, `snapshot_id`,
  `recommendation_id`, `decision_id` — system identities.
- `policy_version` — the version of a deterministic contract (BC8 publishes;
  every context records).
- `provenance` — the immutable tuple shape from `01-architecture.md`
  (Cross-cutting identifiers).
- `confidence` — the `[0,1]` measure and its combining functions
  (`02-ontology.md` §12).

Anything else (e.g. `delay`, `lane`, `route` in the supply-chain sense) belongs
to one context only and may not appear in another context's DTO without a
translator. This is the structural prevention of "model sprawl."

## 7. Module placement within contexts

Each module from `01-architecture.md` §7 is placed in exactly one context. The
mapping unifies Phase 1's modules with Phase 1.5's contexts.

| Module | Context | Capability |
|---|---|---|
| foundation | cross-cutting | C10 + shared |
| domain | BC2 (+ shared by consumers of canonical DTOs) | C2 |
| persistence | BC2 | C2 |
| ingestion | BC1 | C1 |
| resolution | BC1 (entity resolution + conflict state) | C1 |
| graph | BC2 (sub-context: graph read/write) | C3 |
| intelligence.signals | BC4 | C5 |
| intelligence.recommendations | BC4 | C5 |
| intelligence.scenarios | BC3 | C4 |
| decisions | BC4 | C6 |
| audit | BC8 (admin read) / cross-cutting writes | C10 |
| auth | BC5 | C9 |
| workspace | BC6 | C8/C9 |
| ml | BC7 | C7 |
| admin | BC8 | C8 |
| jobs | BC8 | C8 |
| api (routers) | thin orchestration across contexts | cross-cutting |

This guarantees the import-rule contracts (`01` §7.1) are a subset of the
context contracts: a context cannot import another context's private models,
only its published DTOs/services, and where marked mandatory, only through the
listed ACL.

## 8. Evolution rules

- A new context requires an ACR plus a Constitution review (it changes the
  platform's language boundary).
- A new inter-context dependency requires an ACR; a growing coupling through
  shared tables is forbidden regardless of rationale.
- Conformist relationships (CF) are limited to the pairs listed in §3; any
  additional CF must justify why an ACL was not adopted.

## 9. Frozen decisions summary

- Eight bounded contexts; every module and every domain term belongs to
  exactly one.
- Inter-context integration patterns (OHS/PL/ACL/CF/CS) are fixed per pair.
- Mandatory ACLs article the boundaries where strangers meet: BC7→BC1
  candidate, BC2→BC3 simulation, BC1→BC2 promotion, BC4→BC7 one-way, BC8 audit.
- A frozen ubiquitous language of seven terms crosses all contexts; all else
  is private.
- Module-to-context placement is closed for Phase 2.
