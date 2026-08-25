# 13 — Cortex Constitution

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md` (core principles) |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Status of this document

The Constitution is the **philosophical foundation of the codebase**. The ten
principles below bind every engineer, every module, and every later Phase
document. They are not guidelines; they are rules. A pull request that
violates a principle must be rejected, regardless of any short-term convenience.

The Constitution is **harder to change than any other document**. A change
requires a full architecture review, the sign-off of the engineering owner and
a security reviewer, and a written rationale that the change preserves Cortex's
identity as an *evidence-first operational intelligence platform for supply
chains*. The nine core principles in `01-architecture.md` §5 are operational
expressions of this Constitution; where the two appear to overlap, the
Constitution states the intent and `01-architecture.md` states the
enforcement.

## 2. Words Cortex uses precisely

To prevent semantic drift, three words in this Constitution have one fixed
meaning:

- **Decision** — a recorded, human-approved action that affects the operational
  graph or the supply chain, captured as a `DecisionRecord`
  (`04-graph-and-events.md` Part VI). An ML output, a signal, or a
  recommendation is **not** a decision until a human approves it.
- **Recommendation** — a deterministic, evidence-backed proposal produced by
  Cortex (`04` Part V). It is never an action and never an autonomic act.
- **Evidence** — an immutable, machine-readable support record pointing to a
  source object (`03-canonical-data-model.md` §7). A model output or a human
  opinion is **not** evidence until it is materialized as such.
- **Prediction** — any ML output whose value lies in forecasting the future or
  scoring likelihood. Predictions are inputs to human decision-making, never
  facts.

## 3. The ten principles

### Principle 1 — Evidence over prediction
A prediction may inform; it may never become a fact without evidence. Every
canonical fact, every graph edge, every signal, every recommendation, and every
decision explanation must reach evidence within a bounded lineage depth
(`03` §10.2). Predictions are evidence candidates at most.

**Prohibits**: storing an ML output as a canonical attribute; emitting a
recommendation whose explanation lacks evidence refs; treating a forecast as a
fact in any UI surface.

### Principle 2 — Human decisions over automation
Cortex never acts on the operational supply chain without a recorded human
decision. Automation may prepare, sort, and propose; it does not execute. The
system may automate internal bookkeeping (snapshot seals, readiness evaluation,
audit emission) but never an outbound operational action.

**Prohibits**: any code path that places an order, reroutes a shipment, or
externally notifies a counterparty without a `DecisionRecord` with a non-null
`decided_by_ref`.

### Principle 3 — Explainability over accuracy
A more accurate model that cannot explain itself is rejected. A recommendation
or decision explanation is a first-class artifact composed only of evidence
references and a deterministic rule id; `policy_version` and `input_hash`
make it reproducible.

**Prohibits**: any recommendation whose `explanation.evidence_refs` is empty;
any decision record without `policy_version` + `input_hash`; any ML candidate
that cannot trace back to a registered model version.

### Principle 4 — Determinism over hidden heuristics
The decision layer is a deterministic function of (graph state, evidence,
policy version). Same inputs ⇒ identical outputs, proven by replay. Hidden
heuristics, learned thresholds baked into code, or "obvious" special cases
that bypass the policy registry are forbidden.

**Prohibits**: hard-coded thresholds outside the policy registry; non-replayable
recommendations; any "fallback" path that produces a recommendation without a
recorded policy version.

### Principle 5 — Version everything
Entities, edges, evidence, claims, snapshots, events, policies, models, API
contracts, and schemas are all versioned. History is never destroyed; superseded
records are retained and linked via `DERIVED_FROM`. The present is a point in
the version chain, never the whole truth.

**Prohibits**: in-place mutation of versioned values; deletion of audit events;
silent re-derivation of a sealed snapshot.

### Principle 6 — Every decision is traceable
A decision is reproducible from its recorded inputs, and a complete lineage DAG
reaches the underlying evidence. Traceability is not a feature; it is a
verification obligation, exercised by the regression suite (`10` §7).

**Prohibits**: a decision whose `input_snapshot_id` is missing; lineage paths
that exceed the bounded depth without a recorded data-quality alert.

### Principle 7 — No silent data mutation
Cortex never modifies data in place where the change is not versioned and
audited. New evidence replaces old via append-and-close, never via overwrite.
A user never observes a value change that the system did not also record.

**Prohibits**: raw `UPDATE` on canonical attribute values; "auto-correct"
paths that rewrite evidence without producing a supersession event; any UI
optimistic update that hides an audited state transition from the user.

### Principle 8 — Security by default
A workspace is isolated by default; access is denied by default; uploads are
hostile by default; audit is tamper-evident by default; secrets are external
by default. Security is never "added later." Every new endpoint begins with the
deny posture and adds grants explicitly.

**Prohibits**: cross-tenant or cross-workspace reach without an explicit
allowlisted path; an unauthenticated state-changing endpoint; secrets in
images, env files, or frontend bundles.

### Principle 9 — Enterprise before convenience
When a fast, convenient path conflicts with auditability, isolation, or
reproducibility, the enterprise path wins. Convenience is a UX concern inside
the workspace shell; it is never an architectural shortcut. Demo-grade shortcuts
(dropping evidence for speed, faking determinism, bypassing review) are out of
scope by definition.

**Prohibits**: skipping the readiness gate for "just this once"; bypassing
human review when analysis is "obvious"; adding a feature that another tenant
cannot disable.

### Principle 10 — Every recommendation must be reversible
No recommendation may propose an action that cannot be undone within a known
window. A decision to act must carry a documented revert path; an irreversible
action is forbidden by design. This is what makes Cortex an operational
intelligence platform rather than an autonomous agent.

**Prohibits**: recommending an action with no revert workflow; recording a
`DecisionRecord` of an action whose revert path is not implemented and
documented; suppressing revert via long-running side effects.

## 4. How engineers use the Constitution

- **Code review**: every PR description includes the principles it touches and
  confirms compliance. A reviewer blocks on any principle violation; the
  block is not overridden by seniority.
- **Architecture decisions**: every ACR cites the principles it satisfies or
  amends. An ACR that contradicts a principle is rejected unless it explicitly
  amends the Constitution under §1.
- **Onboarding**: every new engineer signs the Constitution as part of
  onboarding. The signature is auditable (out of Phase 1 scope; tracked in the
  admin UI in later phases).

## 5. Priorities when principles appear to conflict

When two principles pull in different directions, the **precedence order** is
fixed:

1. Evidence over prediction (P1) and Security by default (P8) outrank all
   others in any conflict.
2. Human decisions (P2), Traceability (P6), and Reversibility (P10) outrank
   performance and convenience.
3. Determinism (P4) and Explainability (P3) outrank accuracy and convenience.
4. Version everything (P5) and No silent mutation (P7) are process hygiene
   applied to every change.
5. Enterprise before convenience (P9) is the tiebreaker for any remaining
   ambiguity.

No principle is silent. If a situation is not resolvable here, it is an open
architecture question and must be added to `12-phase-1-acceptance.md` §4 with
a recorded resolution.

## 6. Negative tests

The Constitution is enforced by tests, not by trust. Each principle has at
least one negative test that must fail-fast when violated:

| Principle | Representative negative test |
|---|---|
| P1 | A canonical write with no evidence id is rejected at the repository layer. |
| P2 | An outbound operational action endpoint without a `DecisionRecord` returns `403`. |
| P3 | A recommendation serializer with empty `explanation.evidence_refs` raises. |
| P4 | A replay of stored inputs reproduces the exact recommendation; drift fails release. |
| P5 | Any UPDATE to a versioned attribute value fails at the column-grant level. |
| P6 | A decision without `input_snapshot_id` is rejected by the persistence layer. |
| P7 | An "auto-correct" path that rewrites evidence without a supersession event fails audit verification. |
| P8 | A tenant A session cannot SELECT a tenant B row (RLS regression). |
| P9 | A code path that bypasses the readiness gate triggers `gate.skipped` alert. |
| P10 | A recommendation for an action without a registered revert path is rejected at propose time. |

## 7. Frozen decisions summary

- This Constitution is the highest-authority document in the package.
- It binds engineers and code; violations are PR-blocking.
- The ten principles are non-negotiable in Phase 2 onward.
- Change requires full review plus a written rationale preserving Cortex's identity.
