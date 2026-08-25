# Multi-Agent Runtime (Draft)

**Status**: Draft
**Scope**: Post-MVP (Phase 5)
**Not active implementation guidance**

---

## 1. Four-Layer Hierarchy

The original blueprint proposed Supervisor → Workers. That is
insufficient for enterprise scale. The platform uses **four** layers:

```
Mission Layer
  → Planner
    → Supervisor
      → Worker Agents
```

---

## 2. Mission Layer

**Receives**: a high-level goal, e.g., *"Handle Supplier X disruption."*

**Produces**: a **Mission object**:

```json
{
  "mission_id": "uuid",
  "goal": "handle_supplier_disruption",
  "workspace_id": "uuid",
  "supplier_id": "uuid",
  "severity": "critical",
  "deadline_hours": 24,
  "created_at": "iso-8601"
}
```

The Mission Layer is the entry point. It does not plan. It does not
execute. It frames.

---

## 3. Planner

**Receives**: a Mission.

**Produces**: a **Task Plan** — an ordered list of typed tasks.

Example for a supplier disruption mission:

```
Task 1  collect_evidence (supplier_id)
Task 2  update_graph (workspace_id)
Task 3  propagate_impact (supplier_id, snapshot)
Task 4  generate_recommendations (impact_report)
Task 5  evaluate_policy (recommendations)
Task 6  prepare_brief (impact, trust, recs, evidence)
```

The Planner owns decomposition. It does not run tasks. It produces the
contract the Supervisor enforces.

---

## 4. Supervisor

**Receives**: a Task Plan.

**Responsibilities**:
- Schedule tasks (respecting declared dependencies).
- Retry failed tasks (bounded by task's `retry_policy`).
- Coordinate across workers.
- Monitor heartbeats and health.
- Escalate on repeated failure or policy violation.

The Supervisor never performs domain work. It is pure orchestration.

---

## 5. Worker Agents

Specialized, typed workers. Each declares a contract:

| Field | Example |
| --- | --- |
| `supported_verbs` | `["generate_brief", "backtest"]` |
| `subscribed_events` | `["disruption.detected"]` |
| `input_schema` | Pydantic model |
| `output_schema` | Pydantic model |
| `retry_behavior` | `{"max_retries": 3, "backoff": "exponential"}` |
| `failure_behavior` | `{"on_failure": "escalate", "notify": "supervisor"}` |
| `health_behavior` | `{"heartbeat_interval_s": 30}` |

### Workers

| Agent | Domain | Phase |
| --- | --- | --- |
| Evidence Agent | ingestion, validation | Phase 5 |
| Graph Agent | structure, traversal | Phase 5 |
| Signal Agent | anomaly, bottleneck | Phase 5 |
| Simulation Agent | world model, counterfactual | Phase 5 |
| Recommendation Agent | ranking, scoring | Phase 5 |
| Memory Agent | decision log, exports | Phase 5 |
| Monitoring Agent | drift, health | Phase 5 |
| Execution Agent | writebacks, connectors | Phase 6 |

---

## 6. Safety Rules

- All actions are policy-gated.
- All messages are typed (no free-form dicts between agents).
- All work is auditable (every task records input, output, duration).
- All outputs are attributable (agent_id stamped on every artifact).
- No peer-to-peer autonomy unless explicitly routed by the Supervisor.

---

## 7. MVP Status

None of this exists today. The wedge computes the brief synchronously in
a single API call. The runtime is a Phase 5 build.
