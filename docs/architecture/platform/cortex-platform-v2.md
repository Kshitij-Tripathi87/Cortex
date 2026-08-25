# Cortex Platform Architecture v2 (Draft)

**Status**: Draft
**Scope**: Post-MVP
**Not active implementation guidance**

> This document is the long-term North Star. It does **not** govern current
> engineering. The active wedge is documented in
> `docs/architecture/active/wedge-architecture-v1.md`. If this document
> conflicts with the active doc, the active doc wins until an ADR
> explicitly graduates a component.

---

## 1. Mission

Cortex is a layered enterprise decision system. The MVP activates only the
Operational Plane. The rest are architected now so the company can scale
without redesigning its core.

```
If Supplier X fails today,
what happens to my business,
when will it happen,
how much money is at risk,
and what should I do first?
```

---

## 2. Architectural Principles

1. Deterministic first.
2. Evidence first.
3. Explainability over hidden intelligence.
4. Human review before execution.
5. Append-only decision history.
6. Simple core before advanced learning.
7. No autonomous actions without policy gates.
8. No feature enters the MVP unless it improves the wedge.
9. Every output traceable to source data or derived state.
10. Future AI trains from validated decision memory, not guessed labels.

---

## 3. Two-Dimensional Organization

Cortex is organized along **two dimensions**:

### 3.1 Planes (technical layers)

```
Operational Plane
  → Memory Plane
    → Intelligence Plane
      → Multi-Agent Runtime
        → Execution Plane
```

### 3.2 Capability Domains (business capabilities)

```
Evidence
Graph
Decision
Simulation
Memory
Execution
Learning
```

Each capability spans multiple planes. Asking "which plane owns this?" is
the wrong question. The right question is "which capability owns this,
and which plane does it run on?"

---

## 4. Planes

### 4.1 Operational Plane (Active — see wedge-architecture-v1.md)

Ingest, validate, build canonical schema, compile graph, propagate
disruption, compute impact, rank actions, produce Morning Brief, run
backtests. The only active MVP path.

### 4.2 Memory Plane (Draft)

Records recommendations, operator decisions, outcomes, lessons,
backtest results, corrections, state snapshots. Builds the dataset for
future learning. See `decision-memory.md`.

### 4.3 Intelligence Plane (Draft)

Adds learned behavior: graph embeddings, GNNs, risk prediction, ranking
improvement, pattern detection, scenario learning. Consumes Memory as
training substrate. See `intelligence-plane.md`. Split into five
engines: Prediction, Optimization, Reasoning, Simulation, Evaluation.

### 4.4 Multi-Agent Runtime (Draft)

Coordinates specialized agents under supervision. Four-layer hierarchy:
Mission → Planner → Supervisor → Workers. See `multi-agent-runtime.md`.

### 4.5 Execution Plane (Draft)

Turns approved decisions into action: writebacks, task creation,
approvals, rollback, monitoring, exception handling. Policy-gated and
human-supervised. Includes a Connector Layer abstraction. See
`execution-plane.md`.

---

## 5. Capability Domains

### Evidence Capability

| Plane | Component |
| --- | --- |
| Operational | ingestion, validation, provenance |
| Memory | evidence snapshot at decision time |
| Intelligence | signal detection, anomaly scoring |
| Runtime | Evidence Agent |

### Graph Capability

| Plane | Component |
| --- | --- |
| Operational | graph models, traversal, snapshot |
| Memory | graph snapshot at decision time |
| Intelligence | graph embeddings, GNN |
| Runtime | Graph Agent |

### Decision Capability

| Plane | Component |
| --- | --- |
| Operational | impact engine, trust, recommendation |
| Memory | decision history, outcomes |
| Intelligence | ranking model, confidence calibration |
| Runtime | Recommendation Agent |
| Execution | approval workflow |

### Simulation Capability

| Plane | Component |
| --- | --- |
| Operational | timeline, backtest |
| Memory | counterfactual records |
| Intelligence | synthetic worlds, Monte Carlo, digital twin |
| Runtime | Simulation Agent |

### Memory Capability

| Plane | Component |
| --- | --- |
| Operational | (frozen brief artifacts) |
| Memory | append-only log, exports |
| Intelligence | training dataset builder |
| Runtime | Memory Agent |

### Execution Capability

| Plane | Component |
| --- | --- |
| Operational | (none) |
| Memory | execution audit trail |
| Intelligence | policy learning |
| Runtime | Execution Agent |
| Execution | connector layer, writebacks |

### Learning Capability

| Plane | Component |
| --- | --- |
| Operational | (none) |
| Memory | lessons, corrections |
| Intelligence | offline model training |
| Runtime | Monitoring Agent (drift detection) |

---

## 6. World Model

A foundational addition to the platform. The **Operational Graph** is
the structure (slow-changing). The **World Model** is the state
(high-velocity). See `world-model.md`.

```
Evidence
  → Operational Graph (structure)
    → World Model (state)
```

The graph changes slowly (BOM revisions, new suppliers). The world model
changes constantly (inventory, utilization, delay, demand). This
distinction is critical for simulation and RL.

---

## 7. Dependency Rules

### Allowed flow

```
Ingestion
→ Graph
→ Context
→ World Model
→ Propagation
→ Trust
→ Recommendation
→ Decision
→ Memory
→ Intelligence
→ Agents
→ Execution
```

### Forbidden flow

No layer reverses the chain:
- Recommendation cannot mutate raw ingest tables.
- Agent runtime cannot bypass decision memory.
- Intelligence cannot replace operational truth.
- Execution cannot happen without policy approval.

---

## 8. Phase Order

| Phase | Plane | Status |
| --- | --- | --- |
| 0 | Freeze | ✅ Done (ADR-0013) |
| 1 | Operational | ✅ Done (shipped wedge) |
| 2 | Pilot Hardening | 🟡 Active |
| 3 | Memory Plane | ⬜ Future |
| 4 | Intelligence Plane | ⬜ Future |
| 5 | Multi-Agent Runtime | ⬜ Future |
| 6 | Execution Plane | ⬜ Future |

See `docs/architecture/roadmap/` for phase details.

---

## 9. Relationship to the Active Wedge

Nothing in this document is active. The active wedge is governed by:

- `docs/architecture/active/wedge-architecture-v1.md`
- ADRs 0001–0013
- `PILOT_BOARD.md`
- `DECISIONS.md`

A platform component becomes active only via a new ADR that explicitly
graduates it. Until then, this document is a North Star, not a build
order.
