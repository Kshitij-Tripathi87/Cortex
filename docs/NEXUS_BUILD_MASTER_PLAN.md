# Cortex Nexus — Production Build Master Plan

## Mission

Build Cortex Nexus as a production-grade, multi-tenant **multi-agent orchestration and decision platform** for supply-chain management, logistics, sales operations, and adjacent business workflows.

The first launchable wedge is supply-chain decision intelligence, but the platform abstraction is broader: a user gives Nexus a task, Nexus understands it, discovers the knowledge/tools/systems available to the workspace, plans and delegates work to specialized agents, uses the operational graph as contextual memory, runs alternative scenarios, and returns a grounded outcome.

The product is autonomous in investigation, planning, analysis, simulation, and proposal generation. Consequential actions remain governed by policy and authorization unless a customer explicitly enables bounded automation for an approved action class.

## 1. Product contract

```text
user task
  -> task understanding
  -> knowledge / tool / system discovery
  -> task decomposition and planning
  -> multi-agent orchestration
  -> graph + World State context
  -> tool execution
  -> evidence collection
  -> scenario generation
  -> simulation and parameter variation
  -> comparison
  -> recommendation
  -> policy / authorization
  -> human approval where required
  -> governed execution
  -> outcome
  -> NexusTrace
```

The platform must work on fresh customer data and authorized customer systems. No demo singleton, hardcoded operational facts, synthetic evidence, or hidden client-side authority may enter the canonical task path.

## 2. System architecture

```text
                           Browser
                              |
                         HTTPS / CDN
                              |
                       Load Balancer
                              |
                 +------------+-------------+
                 |                          |
              Next.js                  FastAPI x N
                                            |
                  +-------------------------+----------------------+
                  |                         |                      |
             PostgreSQL                  Redis              Object Storage
          authoritative state          transport/cache       datasets/artifacts
                  |                         |
                  +-------------+-----------+
                                |
                   Workers / Outbox Relay
                                |
              +-----------------+------------------+
              |                                    |
       Orchestration Runtime                 Simulation / ML
              |
       Agent Framework adapter
              |
    +---------+----------+----------+----------+
    |                    |          |          |
Procurement          Logistics   Booking   Compliance
Agent                Agent       Agent     Agent
    |
    +---------------- Critic / Synthesis ----------------+
                                                         |
                                                  Governed Proposal
                                                         |
                                             Policy -> Approval -> Execute
```

### Authority model

- PostgreSQL is the only authoritative operational state store.
- Redis is never an authority.
- Object storage contains immutable/large artifacts referenced by persistent records.
- Realtime events are derived after commit through the transactional outbox.
- Digital Twin / scenarios are derived isolated branches and cannot mutate production World State.
- The orchestration framework is not the source of business truth.

## 3. Multi-agent orchestration architecture

The orchestration layer is a first-class Nexus subsystem.

```text
USER TASK
   |
   v
UNDERSTAND
   |
   v
DISCOVER CAPABILITIES
   |
   +--> native Nexus tools
   +--> MCP / connected services
   +--> documents / knowledge
   +--> graph / World State
   +--> scenario / simulation
   |
   v
PLAN
   |
   +--> dependency graph
   +--> specialist assignment
   +--> required evidence
   +--> budgets / deadlines
   +--> policy requirements
   |
   v
EXECUTE
   |
   +--> parallel specialist work where safe
   +--> delegation / handoff
   +--> bounded tool calls
   +--> evidence capture
   |
   v
GRAPH + KNOWLEDGE CONTEXT
   |
   v
SCENARIOS / SIMULATION
   |
   v
CRITIQUE + SYNTHESIS
   |
   v
RECOMMENDATION
   |
   v
POLICY / AUTHORIZATION
   |
   v
EXECUTION / OUTCOME
   |
   v
NEXUSTRACE
```

### Framework choice

Use **Microsoft Agent Framework for Python** as the primary orchestration engine behind a Nexus-owned orchestration interface.

The current framework line is GA for Python and provides workflow/executor primitives plus Sequential, Concurrent, Group Chat, Handoff, and Magentic orchestration patterns. The current Python release is 1.18.0 as of September 10, 2026. citeturn512315search6turn512315search0

Its core supports agent invocation, tools, workflows, streaming, checkpoint-related workflow behavior, and reusable context mechanisms. citeturn703011search0turn703011search1turn703011search2

AutoGen and CrewAI remain potential alternate adapters behind the same Nexus orchestration contract. The application must not become dependent on framework-specific state models or permission semantics.

## 4. Nexus orchestration boundary

```python
class NexusOrchestrator:
    async def plan(self, context: TaskContext) -> TaskPlan: ...
    async def run_task(self, context: TaskContext) -> TaskResult: ...
```

The framework implementation may use Agent Framework internally, but the following remain owned by Nexus:

- task contracts;
- tenant/workspace identity;
- World State binding;
- capability discovery;
- tool gateway;
- evidence/provenance;
- graph context;
- scenario boundary;
- policy;
- persistence;
- authorization;
- execution adapters;
- NexusTrace.

## 5. Agent context

Every specialist receives a bounded immutable context for its reasoning turn:

```text
workspace_id
tenant_id
task_id
trace_id
actor_id
world_state_version
entity scope
graph context
evidence scope
allowed capabilities
policy context
scenario context
budget
deadline
```

An agent cannot silently continue against a newer World State version. A version change triggers explicit invalidation/replanning.

## 6. Capability discovery

Nexus discovers capabilities before asking agents to execute a task.

Sources:

```text
native Nexus tools
MCP tool servers
ERP / WMS / TMS / CRM / commerce adapters
document / knowledge systems
World State / graph tools
scenario / simulation tools
governed execution adapters
```

Every capability descriptor includes:

```text
capability_id
name
version
description
input schema
output schema
side-effect class
authorization requirements
workspace availability
timeout
budget
provenance requirements
```

Side-effect classes:

```text
READ
ANALYZE
SIMULATE
PROPOSE
WRITE_REVERSIBLE
WRITE_CONSEQUENTIAL
```

`WRITE_CONSEQUENTIAL` cannot bypass Nexus policy and authorization.

## 7. Tool gateway

Every agent tool call passes through a Nexus-owned gateway:

```text
Agent Framework agent
        |
        v
   Nexus Tool Gateway
        |
        +--> actor identity
        +--> tenant/workspace authorization
        +--> capability authorization
        +--> input validation
        +--> policy classification
        +--> budget / timeout
        +--> invocation
        +--> evidence capture
        +--> audit / trace
```

No agent gets direct database credentials or direct authority over production business tables.

## 8. Graph memory

The operational graph is the shared contextual memory layer for the agents, derived from authoritative World State.

```text
World State vN
      |
      v
Canonical operational graph
      |
      +--> entity relationships
      +--> dependency neighborhoods
      +--> supplier / customer / product links
      +--> inventory / order / shipment relationships
      +--> active signals
      +--> prior decisions
      +--> evidence / outcomes
```

The graph is queried to build task context and improve reasoning continuity. It is not a second operational authority.

Agents cannot create arbitrary operational truth in graph memory. Changes to business truth pass through World State services.

## 9. Knowledge and system discovery

A task may require information outside the operational graph.

The planner creates a source plan:

```text
Task
 |
 +--> World State
 +--> graph
 +--> connected business systems
 +--> workspace documents
 +--> approved knowledge/search systems
 +--> domain tools
```

The task result records which sources were actually consulted. Missing authorization or missing data becomes an explicit blocker, not a reason to invent an answer.

## 10. Scenario Studio

Scenario simulation is a first-class product capability separate from the dashboard.

```text
                    World State vN
                         |
             +-----------+-----------+
             |           |           |
         Scenario A  Scenario B  Scenario C
             |           |           |
          simulate    simulate    simulate
             +-----------+-----------+
                         |
                     compare
```

Scenario state is isolated from production World State.

Users and agents may vary:

- demand assumptions;
- lead times;
- supplier availability;
- inventory allocations;
- route/capacity assumptions;
- pricing/cost assumptions;
- policy parameters where explicitly allowed.

Every simulation result records assumptions, base World State version, model versions, parameter changes, resulting state deltas, and outcome metrics.

## 11. Decision synthesis

Agent output is structured before narrative generation.

```text
decision_id
task_id
world_state_version
scenario_id
recommended_action
alternatives
expected_impact
confidence
assumptions
tradeoffs
policy_result
evidence_refs
agent_contributions
trace_id
```

The recommendation must be reproducible from recorded inputs.

## 12. Autonomy model

### Autonomous

- task understanding;
- capability discovery;
- task planning;
- information gathering;
- graph investigation;
- specialist delegation;
- analysis;
- scenario generation;
- simulation;
- recommendation.

### Governed

- consequential writes;
- financial commitments;
- external communications;
- irreversible state changes;
- execution against customer systems.

Default lifecycle:

```text
OBSERVE
 -> REASON
 -> PROPOSE
 -> CRITIQUE
 -> SIMULATE
 -> POLICY
 -> HUMAN APPROVAL
 -> EXECUTE
 -> OUTCOME
```

## 13. Production phases

### Phase 1 — Canonical application UI

Merge/reconcile B3/B6, remove legacy demo paths from canonical application routes, and establish the operational task experience.

### Phase 2 — Ingestion / World State

Detach the launch path from Olist/demo fixtures. Implement reliable CSV ingestion for orders, products, inventory, suppliers, shipments, and related entities.

Required path:

```text
upload
-> schema discovery
-> validation
-> profiling
-> entity resolution
-> canonicalization
-> World State version
-> provenance
```

### Phase 3 — Operational intelligence

Ground graph, signals, propagation, probabilistic forecasting, and risk scoring in persisted World State.

### Phase 4 — First-class orchestration runtime

Introduce Nexus orchestration contracts and Agent Framework adapter.

Tasks:

- TaskContext / TaskPlan / TaskResult contracts;
- workspace-scoped capability registry;
- source planning;
- specialist registration;
- framework-backed workflow;
- bounded tool gateway;
- evidence capture;
- failure/timeout handling;
- persistent task state.

### Phase 5 — Grounded specialist agents

Migrate the existing `multi_agent/` specialist implementations behind the new orchestration contract.

Production specialist families:

- Procurement / Sourcing;
- Logistics / Route / Load Optimization;
- Booking / Carrier Negotiation;
- Compliance / Documentation / Finance;
- Critic / Synthesis.

The legacy `agents/domain_agents/` and Olist-specific pipelines are not the production orchestration foundation.

### Phase 6 — Graph context and knowledge discovery

Build a bounded context provider and source planner for World State, graph, documents, and connected systems.

### Phase 7 — Scenario Studio

Integrate simulation as an explicit task capability and expose parameterized comparison UI.

### Phase 8 — Decision Room

Build the primary operational task surface:

```text
Task
 -> Understanding
 -> Sources / Tools
 -> Plan
 -> Agent execution
 -> Evidence / Graph
 -> Scenarios
 -> Comparison
 -> Recommendation
 -> Policy
 -> Approval
 -> Outcome
```

### Phase 9 — Realtime

Stream task and decision progress through the existing outbox/event fabric.

### Phase 10 — Cloud staging

Deploy:

- Next.js web service;
- 2+ stateless API replicas;
- orchestration/async worker processes;
- dedicated outbox relay;
- managed PostgreSQL;
- managed Redis;
- managed object storage;
- HTTPS/load balancing;
- external secrets;
- centralized logs/metrics/traces.

No Kafka dependency is required for this launch.

### Phase 11 — Reliability/security

Exercise API/worker/relay restart, Redis loss, DB interruption, realtime reconnect, task recovery, duplicate/gap events, stale World State, authorization boundaries, and failure recovery.

### Phase 12 — DR / RC / SaaS

Prove backup/restore, migration rehearsal, load, rollback, customer rehearsal, then add backend-enforced entitlements, admin/support, and transactional email.

## 14. Agent evaluation

Measure the orchestration system independently from model quality:

```text
task_success_rate
task_completion_rate
grounded_claim_rate
unsupported_claim_rate
capability_selection_accuracy
tool_argument_error_rate
unnecessary_tool_call_rate
average_tool_calls
agent_turn_count
latency
model_cost
policy_block_rate
human_override_rate
simulation_recommendation_quality
outcome_accuracy
```

Every evaluation record identifies the task, World State version, model/provider versions, tool set, and trace.

## 15. Production-grade quality bar

### Data

- idempotent ingestion;
- immutable dataset/version identifiers;
- atomic World State updates;
- no partial canonical state;
- durable provenance.

### API

- request/correlation IDs;
- structured errors;
- consistent 401/403/404/409 semantics;
- optimistic concurrency where needed;
- bounded timeouts;
- retry-safe mutations;
- object-level authorization.

### Agents

- bounded context;
- bounded tools;
- bounded iterations;
- deterministic policy checks;
- explicit evidence requirements;
- no hidden side effects;
- persistent task state.

### ML

- immutable model versions;
- promotion gates;
- prediction provenance;
- champion/rollback;
- Truth Loop monitoring;
- no autonomous production retraining at launch.

### Realtime

- transactional outbox;
- ordered per-workspace sequence;
- durable replay;
- idempotent consumption;
- gap detection;
- reconnect catch-up.

## 16. Repository delivery model

Work from feature branches from the current `main` baseline. Each phase requires:

1. implementation;
2. targeted tests;
3. integration tests;
4. CI validation;
5. mergeable PR;
6. staging verification;
7. release evidence.

Never merge deployment configuration that references a non-existent entrypoint or embeds production secrets.

## 17. Definition of done for v0.8.5

```text
[ ] canonical application UI is live
[ ] task console is live
[ ] fresh CSV ingestion works
[ ] World State version is persisted
[ ] graph context is derived from World State
[ ] capabilities are discovered from authorized registries
[ ] tools are evidence-backed
[ ] multi-agent orchestration runs on a real task
[ ] specialist agents are grounded in real workspace data
[ ] scenario simulation is isolated and parameterized
[ ] comparison produces derived outcomes
[ ] recommendation is traceable
[ ] policy / authorization is enforced
[ ] execution/outcome are persisted
[ ] NexusTrace is complete
[ ] realtime task/decision progress works
[ ] tenant/workspace isolation passes
[ ] cloud staging is deployed
[ ] backup/restore is proven
[ ] failure drills pass
[ ] load tests pass
[ ] observability and alerts work
[ ] entitlements enforce server-side limits
[ ] transactional auth/support email works
[ ] fresh customer rehearsal passes
```
