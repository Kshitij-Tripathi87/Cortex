# Decision Memory (Draft)

**Status**: Draft
**Scope**: Post-MVP (Phase 3)
**Not active implementation guidance**

---

## 1. Why This Exists

Decision memory is the start of the learning moat. Without it, the
Intelligence Plane trains on guessed labels. With it, every decision
becomes a complete training example.

---

## 2. The Full Snapshot

The original blueprint stored `Decision → Outcome → Lesson`. That loses
most of the signal. The platform stores a **full decision context**:

```
Decision Context
  ↓
  Evidence Snapshot        (raw data at decision time)
  Graph Snapshot           (structure at decision time)
  Feature Snapshot         (derived features)
  Signal Snapshot          (active signals)
  Propagation Snapshot     (BFS result)
  Scenario Snapshot        (world model fork)
  Recommendation Snapshot  (ranked actions + scores)
  Human Decision            (what the operator chose)
  Execution Result          (what happened when they acted)
  Observed Outcome         (what actually happened later)
  Retrospective            (operator's own notes)
  Lessons                  (generalized rules)
  Counterfactual           (what would have happened under alt action)
  Confidence Error         (predicted confidence vs realized outcome)
```

Every decision is now a complete training example, not just a label.

---

## 3. Schema Rules

- Append-only. No overwrite. No delete.
- Every record carries `workspace_id`, `decision_id`, `created_at`.
- Snapshots are immutable — point-in-time copies.
- Counterfactuals are clearly tagged as hypothetical, not observed.
- Failed decisions are kept. Hiding failures destroys the training set.

---

## 4. Replayability

Given a `decision_id`, the system can reconstruct:

1. The exact world state at decision time.
2. The exact recommendation set the operator saw.
3. The exact action chosen.
4. The observed outcome.
5. The counterfactual outcome under any other action.

This is what the Intelligence Plane needs: replayable, ground-truth
examples, not guessed labels.

---

## 5. Export Format

The Memory Plane exports training examples as a versioned JSONL stream
with the above structure. The Intelligence Plane consumes it. The
contract is frozen per decision-memory schema ADR (future).

---

## 6. MVP Status

The wedge does not persist decisions. Every API request recomputes
from the snapshot. The Memory Plane is a Phase 3 build, gated on the
pilot producing real operator decisions to log.
