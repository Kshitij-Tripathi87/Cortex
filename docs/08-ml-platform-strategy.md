# 08 — ML Platform Strategy

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md`, `03-canonical-data-model.md`, `04-graph-and-events.md` |
| Frozen | Phase 1 |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose and posture

ML in Cortex is a **bounded, optional support layer** — never the source of
truth, never the decision-maker, never able to write canonical facts, graph
edges, audit events, or decisions directly. Phase 1 freezes the strategy so
later implementations cannot drift into ML-becomes-the-product.

Two categorical prohibitions carry through every section below (repeated from
`01-architecture.md` §5.9 and `04-graph-and-events.md`):

1. **No LLM fine-tuning is introduced in Phase 1.** No foundation-model
   fine-tuning is part of Phase 1 or Phase 2.
2. **ML outputs never bypass the deterministic evidence layer.** Every ML
   output is a *candidate claim* (`confidence ≤ 0.5`) which must pass the same
   validation, conflict detection, evidence-linking, and human-review gates as
   any other claim.

ML is for **later bounded assistance**, not Phase 2 core intelligence.

---

## 2. What ML may do (closed enumeration)

Phase 1 freezes the closed set of functions the ML platform is permitted to
perform. Anything outside this set requires an ACR.

1. **Synthetic dataset generation** — generate labeled supply-chain datasets for
   testing policies and models without using customer data.
2. **Feature computation** — deterministic feature derivations from canonical
   entities/edges (e.g. lead-time volatility, supplier concentration index).
3. **Experiment tracking** — record runs, parameters, metrics, artifacts,
   lineage to datasets and code versions.
4. **Model registry** — version, sign, and gate model artifacts.
5. **Training and evaluation** — supervised/unsupervised training under
   configured compute + data budgets; offline evaluation and replay against
   sealed snapshots.
6. **Shadow inference** — run models in parallel with the deterministic
   pipeline; outputs become candidate claims in **review-only** mode.
7. **Calibration** — measure and correct predicted-score-vs-observed-outcome
   reliability; never auto-apply to canonical facts.
8. **Promotion** — move a model version from shadow to recommended use; admin
   approval only; never auto-promote.

Everything below defines the per-function contract.

---

## 3. ML data and isolation

- ML writes only to `ml_*` tables (`06-database-strategy.md` §6.8). It has no
  grants to `canonical`, `graph`, `audit`, or `decisions`.
- ML reads canonical/graph via the same snapshot-bound read paths as the
  deterministic pipeline (`04-graph-and-events.md` §5): **never from live
  canonical state**. This is what keeps shadow inference reproducible.
- Training data lives in object storage under
  `tenants/{tenant_id}/workspaces/{workspace_id}/ml/{dataset_id}/...` for
  workspace-scoped data, and `ml/synthetic/{dataset_id}/...` for synthetic data.
- No training is allowed on raw uploads directly; data must first have reached
  the canonical layer (or be synthetic). This is the ML analog of
  *evidence first*.

---

## 4. Synthetic dataset generation

### 4.1 Purpose
Generate labeled datasets to test policies, evaluate models, and seed scenarios
without exposing real customer data. Synthetic datasets also enable open
demonstrations and benchmark regressions.

### 4.2 Generation contract
- Generators are deterministic, parameterized by a **seed**, a **scenario
  template**, and a **policy_version**. Replay of `(seed, template,
  policy_version)` produces byte-identical datasets (asserted in tests).
- Each generated dataset is registered as an `ml.datasets` row with:
  `dataset_id`, `seed`, `template`, `policy_version`, `generator_version`,
  `content_hash`, `object_ref`, `row_count`, `schema_version`, `created_at`,
  `created_by_ref`, `purpose`, `contains_pii=false` (synthetic).
- A dataset never overwrites an existing dataset id; corrected datasets get new
  ids and the prior is superseded by lineage (`DERIVED_FROM`).

### 4.3 Quality guardrails
- Statistical validity is asserted (distributions match the template within
  configured tolerances) before the dataset is usable.
- Privacy leakage tests assert that no generated row matches a real customer
  record in the same tenant beyond configured similarity bounds.
- PII is forbidden in synthetic datasets by construction (generator templates
  use only artificial names, codes, and locations).

### 4.4 MVP scope
Phase 2 ships one synthetic generator covering the MVP entity set (Supplier,
Warehouse, Plant, Product, InventoryItem, PurchaseOrder, Shipment, Route,
Customer, SalesOrder) plus a deterministic delay-and-stockout injecting
mechanism for labeling signals. Full generator coverage is later.

---

## 5. Dataset versioning

- `ml.datasets` rows are immutable once published; corrections are new datasets
  with `supersedes_dataset_id`.
- A dataset carries a linear version chain (by `DERIVED_FROM`) and a
  *content_hash* for tamper-evidence.
- Consumers reference datasets by id at training/inference time; a dataset id
  is unique forever.
- Dataset purges happen under tenant retention policy, audited by
  `ml.dataset.reclaimed` events.

---

## 6. Feature store

### 6.1 Concept
A feature is a deterministic function `(snapshot_id, entity_ref) → feature
vector`. Features are computed offline on sealed snapshots so they are
reproducible and auditable; there is no online real-time feature aggregator in
Phase 1.

### 6.2 Storage and registration
- `ml.features` records `(feature_id, name, version, definition_hash,
  output_schema_version, created_at, created_by_ref)`. Changing the
  computation bumps the feature version; the old version remains available so
  prior runs remain reproducible.
- `ml.feature_values` records computed feature values keyed by
  `(feature_id, snapshot_id, entity_id)`; immutable once written; overwritten
  only by recomputation under a new feature_version (the old rows are kept for
  replay).
- Feature definitions are code under version control; the definition hash binds
  the code to the stored values.

### 6.3 What features never are
- They never feed back into canonical facts. A feature value is an analysis
  product, not a claim. The only path for an ML-derived number to influence the
  graph is as an **ml_candidate claim** through the review queue.

---

## 7. Experiment tracking

- `ml.experiments` records `(experiment_id, dataset_id, feature_version_ids,
  model_kind, hyperparameters, code_commit, run_label, created_at)`.
- `ml.metrics` records `(experiment_id, metric_name, metric_version, split,
  value, direction)` for offline evaluation; metrics are stored as strings to
  avoid float-incoherence at scale; deterministic parsing defined in
  `domain.metrics`.
- `ml.artifacts` records `(artifact_id, object_ref, content_hash, schema_version)`
  including the trained model binary, the feature snapshot, and the
  evaluation report.
- Linkeage: experiments reference datasets and feature versions by id; model
  registry entries reference experiment ids; the entire chain is reproducible.

### 7.1 Tracked non-goals
- No experiment is allowed to assert "this won the bake-off"; promotion is a
  human-recorded decision (`§9`).
- No accidental leaking of training metadata (hyperparameters, dataset ids) into
  production inference logs beyond what is auditable and tenant-scoped.

---

## 8. Model registry

### 8.1 Concept
A model registry entry is a versioned, signed, policy-gated pointer to a trained
artifact and its metadata. The registry is the single legal source for inference.

### 8.2 Registry record
- `ml.models` records `(model_id, name, current_version, owner_role,
  created_at, created_by_ref, last_promoted_at?)`.
- `ml.model_versions` records `(model_version_id, model_id, version,
  experiment_id, artifact_id, signature, schema_version, status, created_at,
  promoted_by_ref?, promoted_at?, evaluation_summary)`.
- `status` enum: `draft`, `shadow`, `candidate`, `primary`, `retired`, `revoked`.
  Promotion is shadow→candidate→primary; a primary can be retired or revoked,
  never silently replaced.

### 8.3 Signatures
- Model artifacts are signed with a tenant-scoped key managed separately from
  the application (`09-security.md`). Inference loads only verified artifacts;
  signature mismatch refuses to load and emits `ml.model.signature_failed`.

### 8.4 Promotion gating
- A model version promotion request must include a successful replay evaluation
  against a minimum of two sealed snapshots (one of which is the most recent
  pilot snapshot at request time). Phase 1 freezes the requirement; Phase 2
  freezes the eval protocols.
- Promotion is admin-only and emits `ml.model.promoted`.

---

## 9. Training and evaluation concept

### 9.1 Training
- Training is **sandboxed**: isolated process/container, no direct DB access,
  read-only access to datasets and features via signed URLs + a read-only
  snapshot view. It writes only to `ml.experiments`, `ml.artifacts`, and
  `ml.metrics` (and to object storage under `ml/runs/...`).
- Compute budgets per experiment (CPU-minutes, GB-hours) are configured and
  enforced; exhaustion ⇒ `ml.experiment.budget_exhausted`, job stops cleanly.
- Code and config versions are recorded: `code_commit`, `config_hash`,
  `feature_version_ids`, `dataset_id`. Replay reproduces artifacts byte-for-byte
  under the same conditions (asserted in tests).

### 9.2 Evaluation
- Offline evaluation runs on configured sealed snapshots and writes metrics.
- The **eval protocol** includes: a frozen test split per snapshot; a
  no-data-leakage check (training and evaluation dataset ids are disjoint);
  a deterministic order of evaluation to avoid ordering artifacts; a
  sensational but bounded variety of splits to surface variance.
- Evaluation reports are stored as artifacts and surfaced in the model center
  read-only UI (`07-frontend-architecture.md` §4.9).

---

## 10. Shadow inference concept

### 10.1 Concept
A shadow model runs in parallel with the deterministic pipeline. It receives
the **same sealed-snapshot-bound inputs** and produces candidate outputs, but
its outputs **never affect canonical state or recommendations**. They are
written to `ml.shadow_inferences` and to the review queue as `ml_candidate`
claims.

### 10.2 Contract
- Inputs are recorded as `(snapshot_id, input_hash)` to allow deterministic
  replay and comparison with the deterministic pipeline's output.
- Outputs are converted to **candidate claims** with `source_system =
  ml_candidate`, `confidence ≤ 0.5`, and `claim_state = pending_review`. They go
  through conflict detection like any claim.
- Comparison reports (`ml.shadow_comparison`) compare shadow candidates with the
  deterministic output and the eventual human decision; this is what feeds
  promotion evidence.

### 10.3 What shadow inference must not do
- It cannot write to canonical, graph, audit, or decisions tables.
- It cannot call any API outside the registered ML inference interface.
- It cannot produce a public recommendation; the UI shows it only to
  reviewers/auditors with explicit disclosure of provenance.

---

## 11. Calibration concept

### 11.1 Concept
Calibration measures how predicted confidence compares with observed outcome
frequency, and applies a transformation **only to scores used as candidate
claims**, not to canonical facts. It never turns an ML candidate into a fact.

### 11.2 Contract
- Per-model calibration state is stored as `ml.calibration` records including
  `(model_version_id, calibration_method_version, fitted_params, eval_snapshot_id,
  content_hash, created_at, created_by_ref)`.
- Calibration transformations are versioned and signed; the original (uncalibrated)
  score and the calibrated score are both retained in candidate claims.
- Calibration cannot raise a candidate's score above `0.5`; that ceiling is
  enforcement of `01-architecture.md` §5.9 and is asserted on every candidate
  write.

---

## 12. Promotion concept

### 12.1 Promotion path (frozen)
```
draft → shadow → candidate → primary
```
- A primary is the only model status eligible to contribute candidates to the
  review queue by default. Shadow produces candidate claims but is gated to a
  separate review lane (used to gather comparison data).
- `revoked` is terminal; a revoked version can never be primary again.
- Every transition emits an audit event and records `promoted_by_ref` and a
  rationale that references the experiment id, replay evaluation artifacts, and
  the calibration record.

### 12.2 Rollback
- Promoting a new primary automatically demotes the prior primary to
  `candidate` (not retired), and a one-step rollback is available within 7 days.
- Rollback is an admin action that emits `ml.model.rollback` and reverifies the
  prior primary's signature.

---

## 13. MVP vs. later scope (frozen)

| Concern | MVP (Phase 2) | Later phases |
|---|---|---|
| Synthetic data | One generator for the MVP entity set | Full catalog, scenario-specific templates |
| Features | Deterministic snapshots of lead-time, supplier concentration | richer feature library |
| Experiments | Run/param/metric/artifact tracking for one model kind | broader kinds, automated bake-off dashboards |
| Registry | version+signature+promotion | staged environments, canary rules |
| Training | sandboxed, budgeted, on synthetic or canonical (snapshot-bound) data | multi-tenant pooling disabled by default for tenant isolation; opt-in later |
| Shadow inference | none in MVP; deterministic pipeline only | shadow for one bounded model (e.g. delay-risk scoring) |
| Calibration | none in MVP | per-model calibration with promotion evidence |
| Promotion | none in MVP (no models are primary) | admin-gated promotion with replay evidence |

This means **Phase 2 ships the deterministic pipeline and the platform contracts
for ML, but no model is primary, no shadow inference affects outputs.** ML
exists as scaffolding only; it cannot influence the product in Phase 2.

---

## 14. Auditability and explainability of ML

- All ML artifacts, runs, scores, candidate claims, and calibration records are
  part of audit and lineage.
- A reviewer inspecting an `ml_candidate` claim can navigate to the model
  version, the experiment, the dataset, the feature versions, the calibration
  record, and the snapshot used — that is the mandatory ML explainability chain.
- The recommendation page (`07-frontend-architecture.md` §4.8) discloses
  `ml_candidate_ref` together with the deterministic `rule_id`/`policy_version`
  and the human reviewed/approved action.

---

## 15. What ML never does (one place, for emphasis)

- Never writes canonical facts, graph edges, audit events, or decisions.
- Never writes a claim with `confidence > 0.5`.
- Never auto-promotes; never auto-deploys; never bypasses review.
- Never trains on raw uploads.
- Never merges with the deterministic pipeline; never serves as the
  deterministic decision contract.
- Never calls LLM fine-tuning in Phase 1.
- Never reads from a workspace it is not scoped to; tenant/workspace isolation
  applies identically to ML code.

---

## 16. Frozen decisions summary

- ML is optional, bounded, and review-gated.
- The determinism contract from `04-graph-and-events.md` extends to ML: every
  artifact, feature, and candidate is reproducible from recorded ids.
- Two categorical prohibitions hold for Phase 1 and Phase 2: no LLM
  fine-tuning; no ML bypassing the evidence layer.
- MVP ships the scaffolding only; no primary model affects product output in
  Phase 2.
- All ML activity is audited and explainable in one navigation chain.

Phase 1 proceeds to `09-security.md` on this basis.
