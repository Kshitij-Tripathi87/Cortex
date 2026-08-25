# 19 — Operational Policy Framework

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Product Architect |
| Depends on | `02-ontology.md`, `04-graph-and-events.md`, `18-configuration-strategy.md` (CF3) |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

The Chief Architect's review made this blunt: *Policies should not live inside
Python code.* Today, determinism is preserved by recording `policy_version` and
`input_hash` (`04` Parts III–VI), but that only proves a Python function is
deterministic — it does not externalize the *content* of policy. Phase 1.5
freezes an **Operational Policy Framework**: policies are versioned, registered,
publishable, replay-evaluated, and bound to the Constitution's determinism
rule (`13` Principle 4).

In scope: the framework, registry contract, the closed MVP policy set,
lifecycle, evaluation model, and the no-Python-literals guardrail.
Out of scope: concrete policy values for each tenant (tenant-onboarding
activity).

## 2. What a policy is (frozen definition)

A **policy** is a named, versioned, machine-readable specification of a
deterministic rule that Cortex evaluates over the graph state. Two types are
frozen:

- **Detection policies** — produce signals (`04` Part III).
- **Decision policies** — produce recommendations or readiness decisions
  (`04` Parts V, VI).

Conflict resolution, evidence trust, and scenario execution are also modeled
as policies (§5).

A policy is **not**:
- a recommendation (recommendations are *outputs* of a policy).
- a configuration knob (`18` distinguishes them: a feature flag may select a
  policy version but cannot itself be a policy input).
- a model (ML is a candidate input, never a policy).

## 3. Policy registry contract (frozen)

Every policy is published into the **policy registry**, not authored in Python.
The registry record (`schema_registry.policy_versions`):

| Field | Notes |
|---|---|
| `policy_id` | stable id (e.g. `reroute_to_lower_risk`) |
| `policy_version` | semver-like string `YYYY.MM.<seq>` |
| `policy_kind` | `detection` \| `decision` \| `conflict_resolution` \| `evidence_trust` \| `scenario_execution` \|
| `schema_version` | the policy DSL schema version |
| `definition` | the machine-readable policy DSL (§6) |
| `definition_hash` | sha256 over the canonical `definition` |
| `published_by_ref` | user (admin) |
| `published_at` | timestamp |
| `replaces_version`? | the version this supersedes |
| `replay_eval_summary` | {snapshot_count, golden_matches, drift_count} |
| `status` | `draft`, `published`, `active`, `superseded`, `revoked` |
| `documentation_link` | URL/path into docs |
| `change_rationale` | mandatory text |

Frozen invariants:
- A policy version is **immutable** once `published`. Corrections are new
  versions; the old version remains `published` forever for replay.
- A policy becomes `active` when bound to a workspace or tenant; binding is
  an audited action.
- The deterministic contract: an evaluation reads `(snapshot_id,
  policy_version, inputs)` and produces outputs whose `input_hash` is
  reproducible (Constitution Principle 4).

## 4. Policy lifecycle (frozen)

```
draft
  → published      (admin publishes; replay eval goldens committed)
  → active         (bound to ≥1 tenant/workspace)
  → superseded     (a newer active version replaced it)
  OR revoked       (forbidden forever; replayable forever)
```

- `published` ↔ `active`: a published policy is a *candidate*; binding by an
  admin chooses which version is active where. This separation preserves the
  ability to A/B replay new policies against historical snapshots quietly.
- A `revoked` policy is retained for replay but cannot be bound.
- Reverting `active` to a prior version is allowed within 14 days and emits a
  `policy.rollback` audit event. Beyond 14 days it is treated as a new bind.

## 5. The closed MVP policy set

The closed set of named policies Phase 1.5 freezes. Adding a policy name is
an ACR; concrete parameter values are tenant-onboarding activity.

| Policy id | Kind | What it decides | MVP? |
|---|---|---|---|
| `readiness` | decision | Whether a workspace graph is ready for intelligence (`03` §11) | yes |
| `single_source_dependency` | detection | Signal when a Product has a single Supplier for a Facility | yes |
| `inventory_below_safety_stock` | detection | Signal when on-hand − reserved < safety stock | yes |
| `shipment_delay_predicted` | detection | Signal when ETA exceeds promised window | yes |
| `supplier_concentration` | detection | Signal on top-1 supplier spend ≥ X% | later |
| `lead_time_drift` | detection | Signal on observed-vs-declared lead time drift | later |
| `stock_out_imminent` | detection | Projected depletion before replenishment | later |
| `route_disruption` | detection | Route risk index crossing threshold | later |
| `quality_trend` | detection | Supplier quality-issue density crossing threshold | later |
| `cost_anomaly` | detection | Unit cost beyond historical band | later |
| `graph_inconsistency` | detection | Internal graph health violations | yes (system) |
| `inventory_transfer_policy` | decision | Recommendation for inventory transfer between facilities | later |
| `supplier_approval_policy` | decision | Recommendation for split-source or supplier escalation | later |
| `reroute_to_lower_risk` | decision | Recommendation for rerouting against route risk | later |
| `buffer_stock` | decision | Recommendation for buffer stock adjustment | later |
| `expedite` | decision | Recommendation to expedite shipment | later |
| `escalate_to_review` | decision | Recommendation to escalate a signal for human review | later |
| `conflict_resolution` | conflict_resolution | Default arbitration between competing claims (priority by source_system, evidence weight, temporal recency) | yes |
| `evidence_trust` | evidence_trust | Per-source-system trust weights and the confidence combining function (`02` §12) | yes |
| `scenario_execution` | scenario_execution | Default typed overrides allowed in scenarios; replay-by-default | later |

This set is closed. The `recommendation_type` enum in `02-ontology.md` §5 E14
is unchanged; the policies above are the *producers* of those recommendation types.

## 6. Policy DSL (frozen shape)

Policies are authored in a frozen declarative DSL stored as JSON in the
registry. The DSL is intentionally limited: arithmetic comparisons, thresholds,
set membership, window aggregates, ref traversal, and explicit evidence
requirements. It is *not* Turing-complete; a Forbid list (§7) enforces this.

```jsonc
{
  "policy_id": "single_source_dependency",
  "policy_version": "2026.01.1",
  "policy_kind": "detection",
  "schema_version": "policy.v1",
  "definition": {
    "match": { "node_type": "Product", "through": "SUPPLIES", "via": "reverse" },
    "where": { "Facility": "STORES", "cardinality": "==", "value": 1 },
    "window": { "as_of": "snapshot_valid_from" },
    "produce_signal": {
      "signal_type": "single_source_dependency",
      "severity": "warning",
      "evidence_refs_from": ["SUPPLIES.evidence_refs", "STORES.evidence_refs"],
      "explanation_template": "Product {{ product_ref }} is sourced from a single supplier for facility {{ facility_ref }}"
    }
  }
}
```

The DSL is parsed by a deterministic **policy evaluator** in
`intelligence/policy_evaluator.py` — the only code that reads policy
definitions. All other Python code consumes the evaluator's outputs (signals,
recommendations, readiness decisions, conflict resolutions).

The evaluator is covered by **property-based + golden tests** (`10` §3, §7):
every DSL operator has exhaustive unit tests, and every published policy
version has a golden-replay against the regression snapshot corpus.

## 7. What the DSL forbids (frozen)

To keep determinism and the Constitution enforceable:
- No arbitrary scripting, eval, dynamic imports, network access, or random.
- No floating-point comparisons; Decimal with 6 dp only.
- No reading from outside the sealed snapshot's bound (`as_of`).
- No thresholds drawn from the runtime environment — all thresholds live in
  the policy `definition`.
- No reference to user identity inside the rule body (authz is enforced before
  the evaluator runs; policies operate on facts only).
- No ML outputs referenced except via the named `ml_candidate` evidence-ref
  stream, which is always subject to `confidence ≤ 0.5`.
- No side effects; productions are pure outputs (signals/recommendations).
- No policy may emit a `DecisionRecord` directly; decisions are recorded by
  the decision module from human approvals, never auto-generated.

A DSL author lint fails the publish path on any of these (`10` §5 contract).

## 8. Evaluation model (frozen contract)

For any sealed snapshot `S` and any active policy version `P`:

1. Evaluator loads `S` and `P.definition`.
2. Evaluator computes a typed input set `I` from `(S, P.match, P.where,
   P.window)`. `I` is content-hashed.
3. Evaluator applies `P.produce_*` to `I`, producing outputs whose
   `evidence_refs` are non-empty (taken from the matched graph edges).
4. Each output records `policy_version = P.policy_version` and
   `input_hash = hash(I)`.
5. Every output is signed by the evaluator (`code_commit`,
   `policy_evaluator_version`).

Replay invariant: re-evaluating `(S, P, evaluator_version)` must produce a
byte-identical output set with identical `input_hash`. Drift is a release-
blocking regression (`10` §7.1).

## 9. Cross-context policy use (frozen assignment)

Per `15-bounded-contexts.md`, policies are published from BC8 and consumed by:
- BC4 (Decision context): all detection and decision policies.
- BC1 (Evidence context): `conflict_resolution`, `evidence_trust`.
- BC3 (Simulation context): `scenario_execution`.
- BC2 (Operational Graph context): `readiness` is a decision policy but its
  evaluation is *initiated* by the graph snapshot-seal step's readiness
  determination; the actual evaluation still runs through the BC4
  evaluator. The Graph context's only extra responsibility is to record the
  `readiness.determined` decision as the first entry in decision memory
  (`04` Part VI).
- BC7 (ML context): **never consumes a policy directly**. ML is a candidate
  input, never a policy consumer; ML submissions go through the BC7→BC1 ACL
  and never short-circuit BC4's evaluation.

This assignment is closed; a new consumer of a policy requires an ACR.

## 10. Change governance

- New policy_id: ACR + DC + DSL schema registry entry.
- New policy_version of an existing id: replay-eval goldens committed; admin
  publishes; tenant/workspace binding is audited; *no production effect*
  until binding.
- New DSL schema_version (`policy.v1` → `policy.v2`): an ACR + a translator
  that supports replaying `v1` policies on `v2` semantics (or a published
  `v1` runtime preserved alongside).
- Revocation: ACR + security review; `revoked` policy retained forever for
  replay; bindings removed by audited action.

## 11. Audit and explanation alignment

Each policy execution emits T5 audit events (e.g. `signal.detected` with
`policy_version` and `input_hash`). The `explanation` object in signals and
recommendations (`04` Parts III/V) references the `policy_id`, the
`policy_version`, and the matched `evidence_refs` from the snapshot. This is
the machine-readable side of Constitution Principle 3 (Explainability over
accuracy).

## 12. MVP vs. later

| Concern | MVP | Later |
|---|---|---|
| Registry, lifecycle, evaluator, replay | yes | — |
| Polices published, active | `readiness`, `single_source_dependency`, `inventory_below_safety_stock`, `shipment_delay_predicted`, `conflict_resolution`, `evidence_trust`, `graph_inconsistency` | full catalog |
| DSL operators | match, where, cardinality, window, threshold, evidence-ref assembly, severity | window aggregates, set difference, projection overrides |
| Replay goldens | committed for the MVP policy set on the synthetic regression corpus | full catalog per snapshot |

## 13. Frozen decisions summary

- Policies are external DSL documents in the registry; Python holds only the
  evaluator and the loader.
- Closed MVP policy set with named ids; adding a name is an ACR.
- Published policy versions are immutable and replay-equivalent; binding is
  audited.
- The DSL is deliberately not Turing-complete; a frozen forbid list enforces
  determinism and prevents Python-literal drift.
- Policy roles per context are frozen; ML never consumes policies; BC2 only
  initiates the readiness eval (the evaluator lives in BC4).
- New DSL schema versions require a replay translator.
