# 23 — AI Governance

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer + Security Reviewer |
| Depends on | `01-architecture.md`, `08-ml-platform-strategy.md`, `13-constitution.md`, `15-bounded-contexts.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

Cortex is an evidence-first platform. AI — including any future large-language
model use — is a **bounded, reviewable support layer**, never the source of
truth. Phase 1 already freezes the ML boundary (`01` §5.9, `08`). Phase 1.5
freezes an explicit **AI governance** document so future engineers cannot drift
under the banner of "we added an LLM for convenience."

This document is the final decisional word on AI in Cortex. Where another Phase
1 or Phase 1.5 document treats AI mechanics, this one treats AI *posture and
controls*. If they appear to conflict, this document governs the *what*; the
mechanical document governs the *how*.

## 2. The eight rules (frozen; cannot be relaxed without Constitution §1 review)

The eight rules AR-001 requested are restated as enforceable invariants. None
of them is a guideline; a violation blocks the PR.

### Rule 1 — ML never overrides evidence
- An ML output is at most an evidence candidate.
- It cannot replace, supersede, or rebut an accepted claim absent human
  review.
- Enforcement: the BC7→BC1 candidate ACL (`15` §5.1) refuses candidates with
  `confidence > 0.5`; the BC1 candidate state machine refuses auto-promotion
  of ml_candidate claims; a test asserts an ML candidate can never cause a
  canonical attribute write without a human-reviewed claim transition.

### Rule 2 — LLM never becomes the source of truth
- A large language model (or any foundation model) is never the producer of
  canonical facts, graph edges, signals, recommendations, or decisions. Its
  output is treated as commentary that may, at most, surface evidence
  candidates through the same ACL as other ML.
- LLM calls, when used, are read-only with respect to Cortex data and run on
  sealed snapshots only; the LLM has no DB grants and no audit-write path.
- A "chatbot" surface, if present, returns only references to evidence and
  canonical reads; it never produces a fact that the system persists as
  canonical without human review.
- No LLM fine-tuning in Phase 1 or Phase 2 (`08` §1).
- Enforcement: architectural rule — LLMs are accessed only through the ML
  context's candidate submission API; no other module imports an LLM client.

### Rule 3 — Every AI output references evidence
- Every ML candidate is a claim with at least one `evidence_id`. The evidence
  may be a feature computed from a sealed snapshot's edges/evidence; it is
  never the model's internal state. A truly "groundless" output (no
  resolvable evidence ref) is rejected at the ACL.
- For LLM commentary: any LLM-generated text surfaced to a user MUST include
  resolvable evidence references that the UI renders as clickable links into
  the evidence right rail. LLM text without evidence links is hidden from
  the UI by the serializer.
- Enforcement: serializer tests require `evidence_refs` non-empty on every
  AI-originated surface. Empty `evidence_refs` on `ml_candidate` claims is a
  rejection at ingest.

### Rule 4 — Every AI output has confidence
- Each ML candidate carries a `confidence` in `[0, 0.5]`. Calibration can
  only *lower* or *preserve* confidence, never raise above the cap
  (`08` §11).
- An LLM commentary object carries a `confidence` field that reflects the
  groundedness of the cited evidence (low evidence ⇒ low confidence).
- Enforcement: a write-time assertion rejects any candidate above 0.5; the
  `cortex_ml_candidate_confidence_overflow_total` counter is a continuous
  anomaly alert (`22` A-S4).

### Rule 5 — Every AI output is reproducible
- Inputs to any AI run are recorded as `(snapshot_id, input_hash,
  model_version, code_commit, policy_version)`.
- Replay reproduces the exact outputs byte-for-byte from those inputs and that
  model version.
- For LLM commentary: the full prompt template id + version, the cited
  evidence ids, and the model id+version are recorded; a deterministic
  decoding configuration (temperature 0, fixed seed) is mandatory when
  commentary is persisted. Non-deterministic LLM runs may be *displayed* to
  a reviewer transiently but never recorded as the basis for any persisted
  claim.
- Enforcement: Phase 2 ships the replay test that re-runs every persisted
  candidate's `input_hash`; drift blocks release.

### Rule 6 — Every AI model version is stored
- A model registry entry (`08` §8) is mandatory. No inference may load an
  unsigned or unregistered artifact.
- An LLM used anywhere in Cortex has a registry entry recording:
  `model_id`, `provider`, `model_version`, `runtime_kind`, `schema_version`,
  `signature`, `policy_version` that sanctions its use, `introduced_at`,
  `owner_role`.
- Enforcement: signature-check on every load; failure refuses the model and
  emits `ml.signature_failed` (`22` A-S3). A "shadow" or "primary" model
  cannot serve without a registered artifact.

### Rule 7 — Every AI recommendation is reviewable
- An AI output that influences a recommendation must be surfaced in the
  recommendation's `explanation.ml_candidate_ref` together with the
  deterministic `rule_id`, `policy_version`, and non-ML `evidence_refs`.
- An AI output never produces a `DecisionRecord`; only human approval does.
- The frontend must render the AI contribution visibly and auditable
  (`07-frontend-architecture.md` §4.8); a recommendation without an
  `ml_candidate_ref` is just deterministic, and the UI says so explicitly.
- Enforcement: a recommendation serializer test requires non-empty
  non-ML `evidence_refs` even when `ml_candidate_ref` is present; mixing ML
  and deterministic evidence must be visible, never presumed.

### Rule 8 — AI cannot change these rules
- This document is the governance. An AI model cannot publish, modify, or
  revoke any rule here. Only a Constitution §1 full review may do so.
- An LLM may not edit the policy registry, the schema registry, or the model
  registry; these require the corresponding human admin + step-up.
- Enforcement: ACRs for this document carry the highest review tier; no
  automated process may submit them.

## 3. Per-AI-mode posture matrix

| Mode | Allowed in Phase 1–2? | Source of truth? | Evidence needed? | Confidence cap | Reviewable? | Reproducible? |
|---|---|---|---|---|---|---|
| Deterministic policy evaluation | yes (only source of recommendations) | yes (the policy itself) | yes | n/a | yes (`04` Parts V–VI) | yes |
| Bounded ML candidate (numeric scoring) | scaffolding only (`08` §13) | no | yes (feature-derived) | ≤ 0.5 | yes | yes |
| LLM commentary (read-only explanation aid) | later (not Phase 2) | no | yes (must cite evidence) | calibrated ≤ 0.5 | yes | yes (deterministic decoding) |
| LLM-driven actions / agentic calls | **forbidden** | n/a | n/a | n/a | n/a | n/a |
| LLM fine-tuning | **forbidden** (Phase 1–2) | n/a | n/a | n/a | n/a | n/a |
| LLM as a graph/canonical writer | **forbidden** | n/a | n/a | n/a | n/a | n/a |
| Autonomous agent | **forbidden** (positions Cortex as an operational intelligence platform, not an autonomous system) | n/a | n/a | n/a | n/a | n/a |

The matrix is closed. New modes require a Constitution §1 review plus an ACR.

## 4. Reviewable pipeline for any AI use

Any AI use in Cortex follows the same eight-stage pipeline, frozen here:

1. **Registration**: registry entry, signature, runtime compatibility.
2. **Inputs**: sealed snapshot + named features; an `input_hash` recorded.
3. **Inference**: sandboxed, no DB; outputs are candidate claims only.
4. **ACL**: BC7→BC1 candidate ACL (`15` §5.1); rejects caps/provenance/oversize.
5. **Review queue**: candidate sits as `pending_review`; visible to reviewers
   with full reproducibility metadata.
6. **Acceptance**: only human review promotes to canonical; explanation
   records the contributing `ml_candidate_ref` plus the deterministic
   policy's rule id.
7. **Decision**: a `DecisionRecord` records the human choice; the AI's
   contribution is preserved in its `input_snapshot_id` and references.
8. **Outcome audit**: the decision's observed outcome is later recorded;
   mismatches with the AI's expected impact feed calibration evidence.

Skipping a stage is forbidden; in particular, step 5 cannot be omitted.

## 5. Provenance and audit for AI

- Every candidate claim's provenance tuple (`01` Cross-cutting identifiers)
  is extended with `ai_metadata = {model_id, model_version, runtime_kind,
  code_commit, input_hash, prompt_template_id?, prompt_template_version?}`.
- Every audit event that references an `ml_candidate_ref` writes the AI
  metadata into `payload.metadata.ai`. The audit log is the legal record of
  AI use in Cortex; the metric `cortex_ml_candidates_submitted_total`
  reconciles with `ml.candidate.proposed` T5 rows nightly
  (`22` A-O1 reconciliation).
- LLM prompts are versioned and registered (`schema_registry.prompts`) with
  `prompt_template_id`, `prompt_template_version`, and a `schema_version`;
  a single registered prompt cannot be silently edited; revisions are new
  versions.

## 6. Failure modes and incident handling

- **Confidence overflow** (Rule 4 violation): the candidate is rejected; the
  event is reported as A-S4 (`22`) and the offending model is auto-disabled
  pending review.
- **Signature failure** (Rule 6): the artifact refuses to load; A-S3 fires;
  shadow/primary status is downgraded to `revoked` after three failures.
- **Replay drift** (Rule 5): A-D1 fires; model is moved to `revoked` until
  reproduced; release captain halts any pending promotion.
- **LLM text without evidence** (Rule 3): the serializer hides it; the
  reviewer sees an empty-`evidence_refs` note and may downgrade the LLM model
  version to `revoked` for that tenant.
- **Auto-promotion bug** (Rule 1): treated as a tampering anomaly
  (`17` §10 TamperAnomaly) and a Constitution violation; all affected
  canonical attributes are reverted to `pending_review` and the originating
  model version is revoked across the tenant.

## 7. User-facing posture

- Any UI surface that displays an AI-derived number, label, or commentary
  must show: the confidence, the evidence ref(s), the model name + version,
  and a "Why" affordance linking to the explanation chain. No AI element is
  unlabeled.
- An AI element is visually distinguishable from a deterministic result
  (different affordance); a user can never confuse an ML candidate with an
  audited fact.
- An AI recommendation can be hidden per tenant by the tenant admin via
  CF2 feature flags. The deterministic pipeline never depends on it.

## 8. Compliance and external reporting

- A tenant auditor can export, from BC8 admin, a complete "AI Usage Report"
  for their tenant over a window: model ids, versions, candidates submitted
  per workspace, acceptances, rejections, calibration metadata, signature
  chains. This is the standard artifact an enterprise auditor expects.
- Periodic attestation (out of Phase 1.5 scope) is enabled by the ready
  availability of this report.

## 9. Frozen decisions summary

- Eight rules binding all AI in Cortex; PR-blocking violations.
- No agentic LLM use, no LLM fine-tuning in Phase 1–2, no LLM as canonical
  source; LLM commentary allowed only as evidence-cited UI aid (later
  phase).
- A single reviewable pipeline (8 stages) governs any AI use; review queue
  is non-skippable.
- Every AI output carries provenance + confidence ≤0.5 + evidence refs +
  model registry reference; every output is reproducible.
- The audit log is the legal record of AI use; metrics reconcile with audit
  events nightly.
- Any AI element in the UI shows confidence + evidence + model id/version;
  AI can be hidden per tenant without degrading the deterministic pipeline.
- AI cannot modify any of these rules; only a Constitution §1 review can.
