# Nexus Orchestration Adoption Plan

## Objective

Move Cortex Nexus from a custom/synthetic multi-agent coordination layer to a production orchestration layer that can execute real customer tasks across tools, systems, documents, graph context, and scenario simulation.

## Architecture decision

**Primary framework:** Microsoft Agent Framework for Python.

**Nexus-owned layer:** domain contracts, capability registry, context assembly, tool gateway, authorization, evidence, scenario boundaries, policy, persistence, and execution.

**Optional future adapters:** AutoGen and CrewAI behind the same `NexusOrchestrator` contract.

This avoids coupling the product to a framework while still using a mature orchestration engine for agent coordination.

## Runtime model

```text
                         USER TASK
                             |
                             v
                     Task Understanding
                             |
                             v
                    Capability Discovery
                 /          |           \
                /           |            \
           Tools         Documents     Systems
                \           |            /
                 \          |           /
                  +---------+----------+
                            |
                            v
                        Task Planner
                            |
                    +-------+-------+
                    |               |
                parallel        dependent
                agents          steps
                    |               |
                    +-------+-------+
                            |
                            v
                      Graph Context
                            |
                            v
                     Scenario Studio
                            |
                            v
                     Critique/Synthesis
                            |
                            v
                       Recommendation
                            |
                            v
                       Nexus Policy
                            |
                  +---------+---------+
                  |                   |
              approval             reject
                  |
                  v
              execution
                  |
                  v
               outcome
                  |
                  v
              NexusTrace
```

## Framework role

Use Agent Framework for:

- agent lifecycle/invocation;
- workflow execution;
- sequential and concurrent orchestration;
- handoffs/delegation;
- group deliberation where appropriate;
- streaming/intermediate workflow events;
- checkpoint-aware workflow behavior;
- framework-level tool invocation and middleware hooks.

Do not use it as the authority for:

- World State;
- tenant/workspace identity;
- business transactions;
- policy decisions;
- production execution authorization;
- evidence storage;
- billing/entitlements;
- audit truth.

## Agent roles

### Nexus Supervisor

Owns task decomposition, routing, scheduling, recovery, and synthesis orchestration.

### Procurement Agent

Searches approved suppliers, evaluates sourcing alternatives, and proposes procurement interventions using workspace data and authorized connected systems.

### Logistics Optimization Agent

Analyzes routes, capacities, inventory movement, and logistics alternatives from authoritative workspace context.

### Booking / Negotiation Agent

Evaluates carrier/booking options and prepares bounded commercial proposals.

### Compliance Agent

Checks policy, supplier restrictions, documentation, finance, and other governed constraints.

### Critic Agent

Challenges assumptions, checks evidence completeness, and identifies conflicting recommendations.

### Scenario Agent

Transforms proposals into scenario mutations and requests simulations; it does not mutate production state.

## Capability discovery

The supervisor receives only capabilities the current workspace is authorized to use.

Capability registry sources:

1. Nexus native tools.
2. MCP tool servers.
3. Connected ERP/WMS/TMS/CRM/commerce APIs.
4. Approved document/search systems.
5. Graph and World State query capabilities.
6. Scenario and simulation services.
7. Governed execution adapters.

Every capability has a schema and side-effect classification.

```text
READ
ANALYZE
SIMULATE
PROPOSE
WRITE_REVERSIBLE
WRITE_CONSEQUENTIAL
```

`WRITE_CONSEQUENTIAL` is never directly available to an agent without the Nexus approval path.

## Context assembly

For every task, Nexus creates a frozen task context:

```text
TaskContext
  task_id
  tenant_id
  workspace_id
  trace_id
  actor_id
  world_state_version
  selected_entities
  graph_context
  evidence_refs
  capabilities
  policy_context
  scenario_context
  budget
  deadline
```

The context is immutable for the duration of a reasoning turn. A new World State version causes explicit invalidation/replanning rather than silent mixing of states.

## Graph memory

Graph memory is assembled from the authoritative World State.

The graph layer provides:

- relevant entity neighborhoods;
- supplier/customer/product relationships;
- shipment and order dependencies;
- inventory relationships;
- existing signals;
- prior decisions;
- outcomes and evidence.

Agents do not write arbitrary “memory” directly into the graph. Operational changes use World State services; durable agent memory uses explicit task/memory records.

## Document/system grounding

The task planner should discover relevant sources before agent execution:

```text
Task
 |
 +--> connected systems
 +--> workspace documents
 +--> knowledge index
 +--> graph
 +--> World State
```

The planner produces a `SourcePlan` describing what was consulted and why.

An answer that depends on unavailable or unauthorized information must explicitly report the gap rather than fabricate an answer.

## Scenario simulation

Scenario Studio is an independent execution environment.

```text
base world state v42
   |
   +--- scenario A: expedite supplier
   |
   +--- scenario B: re-route shipment
   |
   +--- scenario C: rebalance inventory
```

Agents can create and modify scenarios through scenario tools. Simulation results are persisted with assumptions and model versions.

Users can change parameters and rerun simulations.

## UI/UX contract

The primary task experience is not a chat window alone.

```text
TASK
  |
  +-- what Nexus understood
  +-- tools/sources selected
  +-- plan
  +-- live agent progress
  +-- graph/evidence context
  +-- scenarios
  +-- comparison
  +-- recommendation
  +-- policy / approval
  +-- outcome
```

### Task Console

Persistent task page showing:

- task objective;
- constraints;
- current phase;
- agent activity;
- tool calls;
- evidence references;
- blockers;
- generated proposals.

### Graph Explorer

Interactive operational graph used as investigation context and memory visualization.

### Scenario Studio

Parameter editor + simulation canvas + multi-scenario comparison.

### Decision Room

Recommendation, assumptions, evidence, trade-offs, policy verdict, approvers, and final outcome.

## Backend module layout

Target structure:

```text
backend/app/modules/orchestration/
├── contracts.py
├── context.py
├── capability_registry.py
├── source_planner.py
├── tool_gateway.py
├── graph_context.py
├── supervisor.py
├── framework/
│   ├── base.py
│   └── agent_framework_adapter.py
├── agents/
│   ├── procurement.py
│   ├── logistics.py
│   ├── booking.py
│   ├── compliance.py
│   └── critic.py
├── scenarios.py
└── tracing.py
```

The existing `backend/app/modules/multi_agent/` implementation becomes the domain implementation source during migration. Legacy `backend/app/modules/agents/domain_agents/` remains outside the new production path.

## Migration strategy

### MAF-1

Introduce Nexus-owned orchestration contracts without changing customer APIs.

### MAF-2

Create the Agent Framework adapter and run a read-only investigation workflow.

### MAF-3

Move capability discovery to workspace-scoped registry.

### MAF-4

Replace synthetic toolkit responses with World State/database-backed tools.

### MAF-5

Add document and connected-system source discovery.

### MAF-6

Add graph context provider.

### MAF-7

Add scenario tool integration.

### MAF-8

Wire Decision Room + streaming task events.

### MAF-9

Add governed execution adapters.

### MAF-10

Run evaluation suite and staging rehearsal.

## Evaluation suite

A production task is successful only when:

- task intent is correctly identified;
- required capabilities are discovered;
- every material claim has evidence;
- tool arguments are valid;
- no unauthorized capability is used;
- no unsupported facts are fabricated;
- agent plan terminates within budget;
- scenario mutations never touch production state;
- recommendation is reproducible from recorded inputs;
- policy is enforced server-side;
- approval is required where configured;
- execution/outcome are persisted;
- NexusTrace is complete.

Track:

```text
task_success_rate
tool_selection_accuracy
grounded_claim_rate
unsupported_claim_rate
tool_error_rate
average_steps
latency
model_cost
human_override_rate
policy_block_rate
simulation_agreement
outcome_accuracy
```

## First real task

Use a supply-chain task that exercises the full platform:

> Analyze current inventory and inbound supply, identify the highest-impact exposure, determine the root causes, discover the relevant supplier/logistics capabilities and evidence, generate multiple interventions, simulate the alternatives under configurable assumptions, recommend the best action, and prepare it for governed approval.

No hardcoded route, supplier, world-state version, budget, forecast, or evidence identifiers are permitted in this flow.
