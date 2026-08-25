# World Model (Draft)

**Status**: Draft
**Scope**: Post-MVP
**Not active implementation guidance**

---

## 1. The Distinction

Cortex has two representations of the enterprise:

| Representation | Changes | Represents |
| --- | --- | --- |
| Operational Graph | Slowly (BOM revisions, new suppliers) | Structure |
| World Model | Constantly (inventory, utilization, delay, demand) | State |

A graph without state cannot drive simulation or RL. A state without
structure cannot propagate impact. The platform needs both.

---

## 2. Graph (Structure)

```
Supplier
  → Component
    → Product
      → Order
        → Customer

Warehouse
  → Component (inventory)
```

Edges are explicit, typed, and stored in the edges table. The graph is
the skeleton; it does not carry velocity.

---

## 3. World Model (State)

The World Model is a timestamped snapshot of every operational variable
the enterprise cares about. It is the **state** the engines read from
and the **state** the simulation mutates.

### 3.1 Entities in the world state

```
Supplier
  delay_days: int            (current delay, 0 if nominal)
  reliability_score: float
  capacity_utilization: float

Component
  on_hand: int               (sum across warehouses)
  safety_stock: int
  daily_usage: int
  coverage_days: float
  in_transit: int

Warehouse
  capacity_utilization: float
  labor_availability: float

Product
  build_rate: int             (units/day)
  demand_rate: int            (orders/day)

Order
  status: enum
  days_until_due: int
  at_risk: bool

Factory
  utilization: float
  downtime_hours: int
```

### 3.2 Time semantics

The World Model has three time modes:

| Mode | Use | Mutated by |
| --- | --- | --- |
| **Now** | Live operational state | Ingestion / ingestion refresh |
| **Replay** | Historical point-in-time | Memory Plane |
| **Hypothetical** | Simulation / counterfactual | Simulation Engine |

A disruption event forks the World Model into a **Hypothetical** branch.
The engines run against the branch. The branch is discarded after the
brief is produced, unless the decision is logged — then the branch
becomes part of the Memory Plane.

---

## 4. Why This Matters for Learning

GNNs trained on the graph alone learn structure. RL policies trained on
the World Model learn **dynamics**: what happens to coverage when
demand spikes, what happens to downstream products when a supplier
delays. Without the World Model, the Intelligence Plane is learning
from a static picture.

---

## 5. MVP Status

The MVP wedge implicitly carries a minimal world state inside the
`SupplyChainSnapshot` dataclass (inventory, orders, suppliers). It is
not surfaced as a first-class concept. Graduating the World Model to
first-class is a Phase 4 task.
