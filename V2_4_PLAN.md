# V2.4 — Evidence & Outcome Integrity (Milestone Plan)

**Date:** 2026-08-22
**Status:** ✅ **IMPLEMENTED & FROZEN** — see `V2_4_EXIT_GATE.md` for the
verified freeze record (E1–E18 all pass, 57/57 V2.4 tests, 225/225 combined
milestone suites). The plan text below is retained as the original spec.
**Predecessor:** V2.3 Governed Execution (`V2_3_EXIT_GATE.md`, FROZEN)

---

## 1. The Question V2.4 Answers

> **Can Cortex prove, after execution, exactly why the action happened and
> what changed because of it?**

Not "more agent capabilities." The evidence chain must become a first-class,
deterministic, queryable artifact before specialist agents (V2.5) are allowed
to act through it.

---

## 2. Target Evidence Chain

```text
SOURCE ROW
    │
    ▼
CANONICAL ENTITY
    │
    ▼
WORLD STATE vN
    │
    ▼
SIGNAL
    │
    ▼
ROOT CAUSE
    │
    ▼
AGENT OBSERVATION
    │
    ▼
PROPOSAL
    │
    ▼
SIMULATION
    │
    ▼
POLICY
    │
    ▼
APPROVAL
    │
    ▼
AUTHORIZATION
    │
    ▼
EXECUTION
    │
    ▼
OUTCOME
    │
    ▼
WORLD STATE vN+1
```

Every edge in this graph carries:

```text
event_id
parent_id
organization_id
workspace_id
world_state_version
correlation_id
causation_id
timestamp
input_hash
output_hash
actor
```

The final **evidence root** deterministically represents the entire chain:
same inputs ⇒ same root; any tampering with any node or edge ⇒ different root.

---

## 3. Deliverables

| # | Deliverable | Notes |
|---|---|---|
| A | `EvidenceNode` model + canonical hashing | Extends the V2.3 `EvidenceChainCompletion` hash into a full per-node/edge structure |
| B | Chain builder wired into the spine orchestrator | One node per pipeline stage; parent links from source row to world state vN+1 |
| C | Correlation/causation ID propagation | `correlation_id` = one decision's whole chain; `causation_id` = the immediate parent cause of each event |
| D | Evidence replay/query API (backend) | Given `authorization_hash` / `outcome_hash` / `decision_id`, return the complete verifiable chain + recomputed root |
| E | Root verification endpoint | Server-side recompute of evidence root; mismatch = integrity alarm (fail-closed) |
| F | Outcome → world state linkage proof | Demonstrate world state vN→vN+1 transition is attributable to exactly one authorization |

## 4. Exit Gate Criteria (draft)

- [ ] Every stage of the spine emits an `EvidenceNode` with all 11 edge fields
- [ ] Chain is deterministic: two identical decision runs produce identical
      evidence roots (modulo wall-clock fields, which are excluded from hashes)
- [ ] Tamper test: modifying any historical node changes the recomputed root
- [ ] Replay API returns the full chain for a completed execution, verified server-side
- [ ] Multi-tenant isolation tests: no cross-organization/workspace chain leakage
- [ ] V2.4 suite green AND prior suites still green (V1, V2.1, V2.2, V2.3 = 168)
- [ ] Baseline debt D-1/D-2/D-3 either fixed by their owners or re-documented
      with updated status (never silently dropped)

## 5. Explicitly Out of Scope

- Real specialist agents (V2.5)
- Agent tooling/memory (V2.6)
- Adversarial security hardening beyond tamper-evidence (V2.7)
- Any frontend expansion beyond read-only observation of the evidence chain
