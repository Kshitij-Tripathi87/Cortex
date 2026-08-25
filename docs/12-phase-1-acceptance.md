# 12 — Phase 1 Acceptance Criteria

| Field | Value |
|---|---|
| Version | 2.0.0 (extended by AR-001 / Phase 1.5) |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01`–`11` (Phase 1), `13`–`23` (Phase 1.5) |
| Frozen | Phase 1 + Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze; 2.0.0 — extended by AR-001 with Phase 1.5 acceptance (§4) |

---

## 1. Purpose

This document is the **checklist that declares Phase 1 / Phase 1.5 done**.
Phase 1 is complete only when every item in §3 is satisfied **and** the Phase
1.5 items in §4 are satisfied **and** no major open architecture question
remains (§5). Each item is observable: either it points to a frozen section of
a Phase 1 / Phase 1.5 document, or it requires an explicit artifact (a schema,
an enum, a contract).

This checklist is also the **release gate for the blueprint**: future phases
begin against the version of the package that has passed this acceptance.

---

## 2. How to run the acceptance

1. The engineering owner and a security reviewer sign each item.
   - `Pass` — the item is demonstrably frozen and unambiguous.
   - `Pass with note` — the item passes and an explicit assumption is recorded
     in the document's "explicit assumptions" or change log.
   - `Fail` — the item is not yet frozen; an ACR or further work is required.
2. Any `Fail` blocks Phase 2 kickoff.
3. The complete signoff is recorded in the repo and stamped on the `README.md`
   Phase 1 header.

---

## 3. Acceptance checklist

### 3.1 Architecture frozen — `01-architecture.md`
- [ ] System style is set: modular monolith, FastAPI + Next.js + PostgreSQL +
      S3-compatible + Redis + workers + bounded ML.
- [ ] Backend / frontend / storage / worker / graph / ML / deterministic-decision
      boundaries are explicit and non-overlapping.
- [ ] The nine core principles each have a concrete enforcement rule.
- [ ] Repository structure and module boundaries are fixed; import-rule
      contracts are encoded.
- [ ] Non-functional targets (§10) are frozen and exported to the testing and
      deployment gates.
- [ ] Architectural enforcement mechanisms (import linter, contract tests,
      grant checks) are named and CI-bound.
- [ ] Explicit Phase 1 assumptions are listed.

### 3.2 Operational ontology frozen — `02-ontology.md`
- [ ] Closed set of 15 canonical entities (E1–E15) with required/optional
      properties, identity, uniqueness, lifecycle, confidence, provenance,
      allowed source systems, and validation constraints.
- [ ] `Facility` is an abstract supertype with subtypes via `facility_type`,
      not via new bare entity types.
- [ ] Lines are modeled as second-class attributes of orders/shipments, not as
      bare entities.
- [ ] Closed set of 14 relationships (R1–R14) with domain/range, properties,
      directional/evidence/inferred flags, and per-edge uniqueness.
- [ ] Universal edge rules enumerated (no self-loops, single current edge,
      acyclic `DERIVED_FROM`, evidence required).
- [ ] Alias registry is provided and append-only.
- [ ] Confidence model is frozen and ML candidates capped ≤0.5.
- [ ] Frozen enums are summarized.

### 3.3 Canonical data model frozen — `03-canonical-data-model.md`
- [ ] Three layers (Raw / Claim / Canonical) are separated.
- [ ] Claim object fields, states, and invariants are frozen.
- [ ] Normalization rules (column, string, date, unit, numeric, missing,
      reference, provenance) are explicit and implemented once in `domain`.
- [ ] Canonical attribute envelope shape is fixed (value + confidence +
      claim/evidence refs + valid window + state).
- [ ] Conflict types and detection rules are closed; conflict record fields
      frozen.
- [ ] Validation issue types are closed; gates on promotion are explicit.
- [ ] Entity resolution algorithm shape is frozen and deterministic.
- [ ] Provenance and lineage model is explicit; ≤3-hop evidence reach rule.
- [ ] The readiness contract is a deterministic decision and the seam between
      Foundation and Intelligence.

### 3.4 Graph model frozen — `04-graph-and-events.md` Part I
- [ ] Node and edge records are frozen; graph reads through sealed snapshots.
- [ ] Evidence-linked vs inferred edges are distinguished; inferred edges
      require a `DERIVED_FROM` derivation.
- [ ] Snapshot record fields, immutability, parent chain, content_hash, and
      construction contract are frozen.
- [ ] Replay, diff, history, temporal, and provenance behaviors are contracted.
- [ ] MVP scope of what the graph cannot do is explicit (§7).

### 3.5 Event model frozen — `04-graph-and-events.md` Part II
- [ ] Event record shape is frozen (event_id, type, version, timestamps,
      subject, causation/correlation, request/job, payload with schema version,
      policy_version and input_hash where deterministic, checksum, hash chain).
- [ ] EventType namespace is closed (foundation / intelligence / admin groups).
- [ ] Immutability, linkage, checksum/chain, versioning, and timestamping
      invariants are explicit.
- [ ] Emission discipline: audit module is the only writer; same transaction
      as the state change where possible.
- [ ] Operational `Event` vs audit event is disambiguated.

### 3.6 Signals frozen — `04-graph-and-events.md` Part III
- [ ] Signal record fields and the structured `explanation` are frozen.
- [ ] Signal types enum is closed; sub-types via ACR only.
- [ ] Determinism contract: same snapshot + policy_version ⇒ same signals and
      `input_hash`; ML only as evidence candidate ≤0.5.
- [ ] MVP scope explicit (3 deterministic types).

### 3.7 Scenarios frozen — `04-graph-and-events.md` Part IV
- [ ] Scenario record fields, scenario types, and creation semantics frozen.
- [ ] Branch snapshots are sealed and read-only; mainline never mutated by a
      scenario.
- [ ] Assumptions are first-class evidence candidates.

### 3.8 Recommendations frozen — `04-graph-and-events.md` Part V
- [ ] Recommendation record and the structured `explanation` are frozen.
- [ ] Determinism contract: same inputs + policy_version ⇒ identical
      recommendation and `input_hash`.
- [ ] ML candidate contribution is bounded (evidence candidate ≤0.5; cannot
      set recommendation confidence).

### 3.9 Decision memory frozen — `04-graph-and-events.md` Part VI
- [ ] DecisionRecord fields and lifecycle frozen.
- [ ] `decided_by_ref`, `policy_version`, `input_hash`, `input_snapshot_id`
      are non-null for `accept_recommendation`/`override`.
- [ ] Outcome recording loop closes deterministically; loops are tested by
      replay (in Phase 2+).
- [ ] The readiness `no_action` decision is the first entry in decision memory.

### 3.10 API conventions frozen — `05-api-standards.md`
- [ ] URL major-versioning `/api/v1`; backward-compatible within a major.
- [ ] Frozen request-id, correlation-id, idempotency-key behavior and storage.
- [ ] Frozen auth strategy (OIDC + JWT + workload identities + MFA step-up).
- [ ] Frozen error shape and code↔status map.
- [ ] Frozen pagination shape (cursor + page wrapper).
- [ ] Mandated `X-Cortex-Workspace` header on workspace endpoints; tenant from
      JWT only.
- [ ] Endpoint groups map 1:1 to backend modules with uniform CRUD+action
      shapes; group URLs frozen.
- [ ] OpenAPI is the single contract; frontend client generated from it.
- [ ] Async operations return `202 Accepted` + `Location` to a job resource.

### 3.11 Database strategy frozen — `06-database-strategy.md`
- [ ] One PostgreSQL cluster per env; one schema per backend module.
- [ ] Roles and grants frozen; INSERT-only on audit/immutable tables; state-
      column-only UPDATE on stateful tables; no UPDATE on values.
- [ ] Tenant isolation by partitioning + RLS; workspace isolation by RLS.
- [ ] Versioned append pattern for canonical entities and graph edges.
- [ ] Operational graph in PostgreSQL adjacency with materialized current views;
      bounded recursive CTE depth for live traversal.
- [ ] Snapshots sealed + hash-bound + parent-chained; read unit for intelligence.
- [ ] Migrations are forward+undo pairs; contractive changes gated by ACR.
- [ ] Idempotency storage and audit hash chain defined.

### 3.12 Frontend architecture frozen — `07-frontend-architecture.md`
- [ ] Next.js App Router + TypeScript + TanStack Query + Zustand + Tailwind +
      WebGL/SVG graph rendering.
- [ ] No business rules in the browser; OpenAPI-generated client is the only
      API path; evidence right rail is mandatory for canonical/graph objects.
- [ ] Feature folders map 1:1 to API groups; cross-feature imports forbidden.
- [ ] Frozen navigation order; workspace shell layout.
- [ ] State strategy: server cache (TanStack), UI-local (Zustand), URL state for
      sharable context; workspace-switch invalidation.
- [ ] Deterministic graph layout; rendering thresholds and refine-prompt fixed.
- [ ] Desktop-first; WCAG 2.1 AA gate; signed URLs only for object access.

### 3.13 ML platform strategy frozen — `08-ml-platform-strategy.md`
- [ ] Closed enumeration of permitted ML functions (§2).
- [ ] Two categorical prohibitions hold: no LLM fine-tuning; no ML bypassing
      the evidence layer.
- [ ] ML writes only to `ml_*`; no canonical/graph/audit/decision grants.
- [ ] Synthetic datasets are deterministic (seed + template + policy_version
      replay byte-identical).
- [ ] Feature store / experiment tracking / model registry / training & evalu /
      shadow inference / calibration / promotion concepts frozen.
- [ ] MVP scope explicit: scaffolding only; no primary model affects product
      output in Phase 2.

### 3.14 Security baseline frozen — `09-security.md`
- [ ] Authn (OIDC/JWT/workload/MFA), authorization (RBAC + RLS, deny by
      default, defense in depth across 3 layers) are explicit.
- [ ] Tenant isolation physical; workspace isolation logical; cross-tenant
      tests are a release gate.
- [ ] Encryption at rest / in transit / secrets handling frozen; algorithms
      pinned.
- [ ] Immutable uploads (object-lock + INSERT-only grant + retention role).
- [ ] Audit immutability + hash chain + nightly verification.
- [ ] Upload validation 8-step pipeline; parser sandbox; path traversal /
      decompression bomb guards.
- [ ] Threat model enumerates threats with controls and named owners.
- [ ] Incident handling stub is frozen with detection/containment/recovery steps.

### 3.15 Testing strategy frozen — `10-testing-and-ci-cd.md`
- [ ] Eight test types frozen (unit/integration/contract/e2e/regression/perf/
      security/acceptance).
- [ ] Replay-determinism test is first-class for snapshots, signals, recs,
      decisions.
- [ ] Three quality gates frozen (merge / release / pilot).
- [ ] Contract tests (OpenAPI + client drift + event schemas + DB grants).
- [ ] CI pipeline shape frozen, ordered, with reproducible builds and SBOM.
- [ ] Synthetic data default; flaky-test detection + quarantine window.

### 3.16 Deployment strategy frozen — `11-deployment.md`
- [ ] Four environments (dev/staging/pilot/prod); strict separation; prod is
      a superset of pilot.
- [ ] One signed, reproducible image per service; portable IaC;
      vendor-specifics isolated.
- [ ] Env-var-driven config validated at startup; forbidden configs listed.
- [ ] Rolling deploy with readiness gate; one-click rollback for 7 days; data
      rollback cautious and audit-recorded.
- [ ] OpenTelemetry-native logs/metrics/traces with frozen core metrics;
      nightly redaction asserts.
- [ ] PITR + logical backups + immutable-lock on uploads; monthly restore drills.
- [ ] Capacity reviewed monthly; ACR-driven changes to frozen artifacts.

---

## 4. Phase 1.5 acceptance (AR-001 deliverables)

Phase 1.5 is complete only when every item below passes. Each item references
the Phase 1.5 document that freezes it.

### 4.1 Constitution frozen — `13-constitution.md`
- [ ] Ten principles bound engineers and code; PR-blocking enforcement via
      negative tests (§6).
- [ ] Words "Decision / Recommendation / Evidence / Prediction" are pinned (§2).
- [ ] Precedence order resolves principle conflicts (§5).
- [ ] Higher change bar than any other document (Constitution §1 review).

### 4.2 Business Capability Map frozen — `14-business-capabilities.md`
- [ ] Eleven closed capabilities; every backend module maps to exactly one.
- [ ] Capability → Domain → Module → Code is the only decomposition chain.
- [ ] Capability dependency DAG fixed; C7→C5/C6 is one-way candidates only.
- [ ] Each capability has an owning team accountable for tests + SLOs.
- [ ] Frontend features align 1:1 to capabilities; orphan features rejected.

### 4.3 Bounded Context Map frozen — `15-bounded-contexts.md`
- [ ] Eight bounded contexts; every module and every domain term belongs to
      exactly one.
- [ ] Inter-context integration patterns (OHS/PL/ACL/CF/CS) fixed per pair.
- [ ] Mandatory ACLs (BC7→BC1 candidate, BC2→BC3 simulation, BC1→BC2
      promotion, BC4→BC7 one-way, BC8 audit) defined.
- [ ] Frozen ubiquitous language of seven terms; all else private to a
      context.
- [ ] Module-to-context placement closed for Phase 2.

### 4.4 Event Taxonomy frozen — `16-event-taxonomy.md`
- [ ] Five categories (T1 business / T2 system / T3 domain / T4 integration /
      T5 audit) classify every event; exactly one category per row.
- [ ] Universal record shape from `04` Part II preserved; only classification
      added.
- [ ] Audit (T5) is the only category in the hash chain and the governance
      record of every mutation.
- [ ] T3 events route to declared target contexts; T4 idempotent via outbox.
- [ ] ML never emits any category; ML candidates arrive as T4 via the
      BC7→BC1 ACL.
- [ ] Frozen classification table (§6) is the authoritative label source.

### 4.5 Error Taxonomy frozen — `17-error-taxonomy.md`
- [ ] Closed tree with nine leaf classes; raisers raise most specific.
- [ ] Each class maps to `error.code` and HTTP per `05` §6.1.
- [ ] `details[*]` structure frozen; `remediation` mandatory for operational
      classes.
- [ ] Only the central error handler responds; raisers raise and never
      format the envelope.
- [ ] Anomalies (Tamper, Determinism) follow a separate path: closest legal
      user class + paging alert + freeze.
- [ ] Frontend error behavior code-generated from OpenAPI enum facets.

### 4.6 Configuration Strategy frozen — `18-configuration-strategy.md`
- [ ] Six exclusive classes (CF1–CF6) with fixed storage/change/validation/
      audit/reactivity.
- [ ] Each knob has exactly one home, recorded in a tested catalog.
- [ ] Fixed override precedence: CF4 > CF5 > CF3 > CF2 > CF1 > CF6.
- [ ] No policy as Python literals; no security primitives per tenant; no
      flags as policy inputs; no hot env reload.
- [ ] Every CF2–CF5 change audited with old/new values, actor, rationale
      (mandatory for CF3/CF4).

### 4.7 Operational Policy Framework frozen — `19-operational-policies.md`
- [ ] Policies externalized as DSL documents in the registry; Python holds
      only the evaluator and loader.
- [ ] Closed MVP policy set with named ids; new id requires ACR.
- [ ] Published policy versions immutable and replay-equivalent; binding
      audited.
- [ ] DSL not Turing-complete; frozen forbid list enforces determinism and
      prevents Python-literal drift.
- [ ] Policy roles per context fixed; ML never consumes policies; BC2 only
      initiates readiness eval (evaluator lives in BC4).
- [ ] New DSL schema versions require a replay translator.

### 4.8 Plugin Architecture frozen — `20-plugin-architecture.md`
- [ ] All integrations are plugins under a frozen contract; no private
      adapters.
- [ ] Source connectors produce `RawRecord`s only; never write canonical
      facts, decisions, audit events, or ML.
- [ ] Plugins signed, sandboxed, least-authority, budget-bound; declared
      permissions checked at runtime.
- [ ] Schema-mapping module (BC1) is the ACL between raw schemas and the
      canonical ontology.
- [ ] Connector catalog closed; adding a connector id is an ACR.
- [ ] Outbound dispatch uses the transactional outbox for exactly-once-effect
      semantics.

### 4.9 Performance Budgets frozen — `21-performance-budgets.md`
- [ ] Per-subsystem budgets with `target/alert/breach` thresholds.
- [ ] CI perf suite asserts `target`; crossing blocks release.
- [ ] Per-tenant quotas via CF4; 429s with `Retry-After`.
- [ ] Snapshot time budget breach leaves result unsealed; unsealed artifacts
      never enter the read path.
- [ ] Frontend, edge API, audit, and storage budgets are first-class.
- [ ] Slow-query log threshold 200 ms with a follow-up issue discipline.

### 4.10 Observability Model frozen — `22-observability-model.md`
- [ ] Seven pillars (metrics, logs, traces, audit, health, SLI/SLO, alerts);
      audit authoritative over metrics on disagreement.
- [ ] Closed metric catalog; closed SLI/SLO table; zero-tolerance alerts for
      security and determinism anomalies (A-S*, A-D* tree).
- [ ] High-cardinality labels quantized; no PII/entity ids as labels; nightly
      redaction asserts.
- [ ] Health endpoints reveal only status; `/status` projects per-tenant
      health scoped by RLS.
- [ ] Trace attributes and span coverage frozen; W3C propagation across the
      async worker boundary mandatory.
- [ ] Alert catalog closed; paging outside the catalog forbidden.

### 4.11 AI Governance frozen — `23-ai-governance.md`
- [ ] Eight rules binding all AI in Cortex; PR-blocking violations.
- [ ] No agentic LLM use, no LLM fine-tuning (Phase 1–2), no LLM as canonical
      source; LLM commentary only as evidence-cited UI aid (later phase).
- [ ] Eight-stage reviewable pipeline governs any AI use; review queue
      non-skippable.
- [ ] Every AI output carries provenance + confidence ≤ 0.5 + evidence refs +
      model registry reference; every output reproducible.
- [ ] Audit log is the legal record of AI use; metrics reconcile with audit
      events nightly.
- [ ] UI shows confidence + evidence + model id/version for any AI element;
      AI hideable per tenant without degrading deterministic pipeline.
- [ ] AI cannot modify any of these rules; only a Constitution §1 review can.

---

## 5. Open architecture questions

Phase 1 is complete only when no **major** open architecture question remains.
The following were considered and resolved in the package; they are listed
here so a reviewer can confirm they are not open:

1. Monolith vs. microservices → modular monolith; split triggers defined
   (`01` §3.3).
2. Separate graph database vs. PostgreSQL → PostgreSQL for Phase 1/2
   (`04` Part I §7.4, `06` §7.4).
3. Where ML begins and ends → bounded, review-gated, confidence-capped
   (`08` §2, §15).
4. How determinism is enforced → policy_version + input_hash + replay tests
   (`04` Parts III–VI, `10` §7).
5. How workspace isolation is enforced → header + RLS + cross-tenant tests
   (`05` §5, `06` §5, `09` §3).
6. The seam between foundation and intelligence → deterministic readiness
   decision (`03` §11, `04` Part VI).
7. How the frontend avoids business rules → generated client + no rules +
   evidence right rail (`07` §2.1, §4.7).
8. How audit is tamper-evident → INSERT-only + hash chain + nightly verify
   (`04` §12.3, `06` §12, `09` §6).
9. How schema drift is prevented → OpenAPI contract tests + client regeneration
   diff (`05` §3, `10` §5).
10. How breaking changes are managed → major-version URL versioning + ACR
    gating of frozen artifacts (`05` §3, `README.md`).
11. How capabilities organize the platform → eleven closed capabilities
    binding every module (`14`).
12. How contexts prevent coupling → eight bounded contexts with frozen ACLs
    (`15`).
13. How event categories stay separate → five-way taxonomy with T5 as the
    governance spine (`16`).
14. How errors stay consistent → closed error hierarchy with fixed wire
    mapping and central handler (`17`).
15. How configuration avoids chaos → six classes with fixed override
    precedence and tested catalog (`18`).
16. How policies stay external → registry-published DSL with evaluator-only
    access (`19`).
17. How integrations stay uniform → frozen plugin contract, sandboxed and
    least-authority (`20`).
18. How performance stays bounded → per-subsystem target/alert/breach with
    CI enforcement (`21`).
19. How the platform is observable → seven pillars with closed metrics, SLIs,
    SLOs, alerts, audit authoritative (`22`).
20. How AI is contained → eight governance rules, eight-stage reviewable
    pipeline, no agentic use, no LLM fine-tuning in Phase 1–2 (`23`).

Any new major question raised in review must be added here with a resolution
or accepted as a tracked open item. A tracked open item blocks Phase 2 kickoff
for the concern it relates to.

---

## 6. Phase boundaries (re-stated)

This acceptance covers Phase 1 and Phase 1.5. Implementation phases that follow
must not:

- introduce entities/edge types/event types outside the frozen closed sets
  without an ACR;
- mutate immutable tables; update values of versioned attributes by raw
  UPDATE; delete audit events;
- expose raw uploads via the frontend; let the browser call DB or storage
  directly; let ML write canonical/graph/audit/decision state;
- skip the readiness gate before running intelligence;
- run live-transaction graph queries against canonical state (use sealed
  snapshots);
- relax any of the AI governance rules (`23` §2);
- raise or document an error outside the closed taxonomy (`17`);
- introduce configuration outside the six classes (`18`);
- author a policy in Python literals (`19`);
- build a private one-off connector (`20`);
- page on an alert outside the closed alert catalog (`22`);
- ship to pilot with a `Fail` here, or without the §11.2/§11.3 gates passing.

---

## 7. Sign-off record

| Field | Value |
|---|---|
| Phase 1 package version | 1.0.0 |
| Phase 1.5 package version (AR-001) | 1.0.0 |
| Combined package version | 2.0.0 |
| Engineering owner | TBD |
| Security reviewer | TBD |
| Sign-off date | TBD |
| Open items carried forward | none |
| ACRs since last acceptance | AR-001 (Phase 1.5) |

When this table is filled and both checklists are green, Phase 2 may begin
against combined package version 2.0.0.
