# V2.4 Evidence & Outcome Integrity — Exit Gate / Freeze Record

**Date:** 2026-08-22
**Status:** ✅ FROZEN — PASS (no new baseline debt introduced)
**Predecessor:** V2.3 Governed Execution (`V2_3_EXIT_GATE.md`, FROZEN)
**Specification:** `V2_4_PLAN.md`

> V2.3 proved execution was **authorized**. V2.4 proves it is
> **traceable**: after execution, Cortex can show exactly why the action
> happened and what changed because of it — with a tamper-evident chain.

---

## 1. What V2.4 Establishes

### 1.1 The evidence chain

Every governed decision now produces a deterministic, verifiable chain:

```text
SOURCE → CANONICAL_ENTITY → GRAPH → WORLD_STATE → SIGNAL → ROOT_CAUSE →
AGENT_OBSERVATION → PROPOSAL → SIMULATION → POLICY → APPROVAL →
AUTHORIZATION → EXECUTION → OUTCOME → WORLD_STATE_NEW
```

### 1.2 The provenance contract

Every node carries the frozen 11-field edge contract:

```text
event_id · parent_id · organization_id · workspace_id ·
world_state_version · correlation_id · causation_id · timestamp ·
actor · input_hash · output_hash        (+ semantic node_type)
```

`node_hash = SHA-256(canonical_json(11 fields + node_type))`
`chain_root = SHA-256(header{org, ws, correlation, decision, count} + ordered node_hashes)`

### 1.3 Architecture rule honored

The evidence graph is **proof, not truth**. World State remains
authoritative; evidence records what happened and proves lineage.
(`app/modules/nexus_spine/evidence_chain.py` module docstring locks this.)

---

## 2. Implementation

| Component | Location | Notes |
|---|---|---|
| Evidence contract | `app/modules/nexus_spine/evidence_chain.py` | `EvidenceNode`, `EvidenceChain`, hash functions, verify/replay/lineage |
| Spine wiring | `app/modules/nexus_spine/spine_orchestrator.py` | `_emit_v24()` helper; one V2.4 node per stage; header finalized at SwarmTask creation via `finalize_correlation()` |
| Result surface | `app/modules/nexus_spine/models.py` | `SpineResult.evidence_chain_v24` (serialized), `.evidence_chain_node_count`, `.evidence_chain_verification`; `evidence_chain_hash` now carries the V2.4 root (V2.3 contract preserved: 64-char SHA-256 hex) |
| Acceptance suite | `backend/tests/test_v2_4_evidence_chain.py` | 57 tests mapped to gates E1–E18 |

Key mechanics:

- **Fail-closed construction:** `EvidenceChain.add()` raises on unknown
  node types, unresolvable parents/causation, or a second root — malformed
  chains can never enter the ledger.
- **Self-verification at close:** the orchestrator raises if the finished
  chain fails its own verification — a spine run cannot complete with an
  unverifiable ledger.
- **Tamper-evidence:** any field mutation without resealing breaks
  `verify()` (`NODE_HASH_MISMATCH`, `CROSS_ORG_NODE`,
  `CROSS_WORKSPACE_NODE`, `CORRELATION_DRIFT`, `PARENT_*`, `CAUSATION_*`,
  `CHAIN_ROOT_MISMATCH`). Fully resealed tampering is provable against any
  externally recorded root (root changes).
- **Replay:** `serialize() / from_serialized()` round-trip preserves the
  root byte-for-byte for intact chains.
- **Cycle-safe lineage:** `lineage()` walks parent links with a visited-set,
  so even a tampered chain cannot hang an audit query.

---

## 3. Exit Gate Results — E1–E18

All 18 acceptance gates from `V2_4_PLAN.md` §4 verified:

| Gate | Requirement | Test evidence |
|---|---|---|
| E1 | Every decision has an evidence root | `TestSpineIntegration::test_chain_root_is_64_char_sha256`, `test_spinal_emits_full_chain` |
| E2 | Every node has deterministic hash | `TestEvidenceNodeContract::test_node_hash_determinism` |
| E3 | Every edge has 11-field contract | `TestEvidenceNodeContract::test_node_has_all_11_fields` (+ all nodes carry full contract) |
| E4 | Source rows trace to canonical entities | `TestSourceToWorldState::test_source_node_carries_dataset_metadata`, `test_chain_source_to_world_state` |
| E5 | Entities trace to World State | `TestSourceToWorldState::test_chain_source_to_world_state` (lineage walk SOURCE→…→WORLD_STATE) |
| E6 | Signals trace to graph/world evidence | `TestIntelligenceProvenance::test_signal_node_carries_world_state_version`, `test_root_cause_references_signals` |
| E7 | Agent proposals trace to evidence | `TestIntelligenceProvenance::test_lineage_proposal_to_source` (PROPOSAL→SOURCE walk through SIGNAL/RCA/WORLD_STATE) |
| E8 | Twin simulation traces to proposal | `TestTwinGovernanceProvenance::test_simulation_traces_to_proposal` |
| E9 | Policy traces to simulation | `TestTwinGovernanceProvenance::test_policy_traces_to_simulation` |
| E10 | Approval traces to policy | `TestTwinGovernanceProvenance::test_approval_traces_to_policy` |
| E11 | Authorization traces to approval | `TestTwinGovernanceProvenance::test_authorization_traces_to_approval` |
| E12 | Execution traces to authorization | `TestOutcomeProvenance::test_execution_traces_to_authorization` |
| E13 | Outcome traces to execution | `TestOutcomeProvenance::test_outcome_traces_to_execution` |
| E14 | Outcome creates new World State event | `TestOutcomeProvenance::test_outcome_creates_new_world_state` |
| E15 | Full chain has deterministic root | `TestChainRoot::test_chain_root_determinism_with_fixed_timestamps` |
| E16 | Any tampering invalidates chain | `TestTamperEvidence` (6 tests: node payload, edge re-parenting, workspace change, world-state version change, proposal substitution, root corruption) |
| E17 | Cross-workspace evidence cannot resolve | `TestCrossWorkspaceIsolation` (cross-org, cross-workspace, correlation drift) |
| E18 | Replayed chain produces same root | `TestReplayDeterminism` (round-trip root equality; tampered replay fails; header rewrite fails) |

---

## 4. Verified Test Evidence (2026-08-22, this machine)

| Suite | File | Result |
|---|---|---:|
| V2.4 Evidence & Outcome Integrity | `test_v2_4_evidence_chain.py` | **57/57** ✅ |
| V1 Real Data Spine | `test_real_data_vertical_slice.py` | **62/62** ✅ |
| V2.1 Persistent World State | `test_v2_world_state_persistence.py` | **11/11** ✅ |
| V2.2 Proposal→Twin→Policy | `test_v2_proposal_twin_policy.py` | **42/42** ✅ |
| V2.3 Governed Execution | `test_v2_3_governed_execution.py` | **53/53** ✅ |
| **Combined relevant suites** | | **225/225** ✅ |
| Full regression (`pytest tests/`) | | **1271 passed / 3 failed / 17 skipped** ⚠️ |

The 3 failures are exactly the pre-registered debt items D-1/D-2/D-3 in
`DEBT_REGISTER.md`. **No new debt was introduced by V2.4; no test was
weakened; frozen J.3.x/Twin semantics were untouched.**

Quality checks on new/changed code:

```text
ruff check app/modules/nexus_spine/ tests/test_v2_4_evidence_chain.py
  → clean except 1 pre-existing style nit inside FROZEN V2.3 file
    (governed_execution_models.py:203 SIM102 — left untouched by rule)
mypy app/modules/nexus_spine/evidence_chain.py app/modules/nexus_spine/models.py
  → 0 errors in nexus_spine sources (remaining errors are legacy modules)
```

---

## 5. Design Notes Recorded at Freeze

1. **Timestamps are inside the hash.** Tampering with recorded time
   invalidates a node. Cross-run reproducibility of the *hash function* is
   proven by injecting fixed timestamps/event_ids in tests (E15/E18); live
   runs are unique by construction.
2. **Unkeyed hashes detect accidental/local tampering; deliberate
   fully-resealed forgery is excluded only against an externally recorded
   root.** Cryptographic signatures/keyed hashes are explicitly deferred to
   V2.7 Adversarial Security — noted so nobody mistakes this for signing.
3. **`uuid7()[:12]` truncation bug class:** truncated uuid7 slices collide
   because the monotonic counter lives beyond char 12. Evidence event_ids
   use the FULL `uuid7()`. Other call sites still truncate — flagged as a
   codebase-wide hazard worth a sweep before V2.5 (agents will create many
   IDs in tight loops).
4. **Header finalization:** nodes emitted before the decision id exists are
   stamped with a placeholder and rehashed once via
   `EvidenceChain.finalize_correlation()` at SwarmTask creation; after that
   the chain is sealed and immutable-by-verification.

---

## 6. Freeze Point

```text
V2.3    Governed Execution       FROZEN
V2.4    Evidence → Outcome       FROZEN  ← this document
        │
        ▼
V2.5    Real Specialist Agents   NEXT
        │
        ▼
V2.6    Agent Tooling + Memory
        │
        ▼
V2.7    Adversarial Security     (signatures over evidence roots land here)
        │
        ▼
V2.8    Production Deployment
```

Frontend expansion remains frozen: the operator UI may render the evidence
chain read-only (observation surface), but builds no parallel truth.
