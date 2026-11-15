# Cortex Nexus — Multi-Agent Orchestration Architecture

## Purpose

Cortex Nexus is a multi-agent orchestration and decision platform for operating supply-chain, logistics, commercial, and adjacent business workflows from one operational control plane.

A user gives Nexus a task. Nexus determines what the task requires, discovers the capabilities and knowledge available to the workspace, plans the work, invokes bounded tools and connected systems, uses the operational graph as contextual memory, evaluates alternatives in an isolated scenario environment, and produces a traceable outcome.

The orchestration layer is therefore a first-class platform subsystem, not a dashboard feature.

## Core task lifecycle

```text
USER TASK
  |
  v
INTENT / TASK ANALYSIS
  |
  +--> identify objective
  +--> identify constraints
  +--> identify required entities
  +--> identify required systems / data
  +--> identify authority level
  |
  v
CAPABILITY DISCOVERY
  |
  +--> workspace tools
  +--> MCP / external tools
  +--> connected business systems
  +--> documents / knowledge
  +--> graph context
  +--> domain skills
  |
  v
TASK PLAN
  |
  +--> decomposition
  +--> dependency graph
  +--> specialist assignment
  +--> evidence requirements
  +--> budget / timeout
  +--> policy constraints
  |
  v
MULTI-AGENT EXECUTION
  |
  +--> specialist agents
  +--> parallel work where safe
  +--> delegation / handoff
  +--> tool invocation
  +--> observation collection
  +--> critique
  |
  v
GRAPH / KNOWLEDGE CONTEXT
  |
  +--> entities
  +--> relationships
  +--> current operational state
  +--> historical evidence
  +--> previous decisions / outcomes
  |
  v
SCENARIO STUDIO
  |
  +--> create isolated scenario
  +--> mutate scenario only
  +--> run simulations
  +--> vary parameters
  +--> compare outcomes
  |
  v
DECISION SYNTHESIS
  |
  +--> recommendation
  +--> confidence
  +--> evidence
  +--> expected impact
  +--> trade-offs
  |
  v
POLICY / AUTHORIZATION
  |
  +--> deterministic policy checks
  +--> approval requirement
  +--> authorization
  |
  v
EXECUTION / OUTCOME
  |
  +--> execute through governed adapter
  +--> persist execution record
  +--> observe result
  +--> record outcome
  |
  v
NEXUSTRACE
```

## Framework decision

Use **Microsoft Agent Framework (Python)** as the primary orchestration engine for the framework-backed implementation, behind a Nexus-owned orchestration interface.

Microsoft Agent Framework is currently GA for Python and supports workflow/executor composition plus Sequential, Concurrent, Group Chat, Handoff, and Magentic orchestration patterns. Its current Python release line is 1.18.x as of September 2026. citeturn512315search6turn512315search0

The framework is an implementation detail of the orchestration layer. Nexus owns the business contracts, authorization, persistence, evidence, and execution boundaries.

### Why this choice

The platform needs both agent behavior and explicit workflow control. Agent Framework provides agents, tools, workflow executors, structured orchestration patterns, streaming, checkpoint-related primitives, and observability hooks that match those requirements. citeturn703011search0turn703011search1turn703011search2

AutoGen and CrewAI remain viable integration targets through the Nexus orchestration contract. They are not allowed to become the system of record or execution authority.

## Nexus orchestration boundary

```python
class NexusOrchestrator:
    async def run_task(self, context: TaskContext) -> TaskResult:
        ...
```

The implementation behind this interface may use Agent Framework, while the rest of Cortex depends only on Nexus contracts.

This preserves the ability to evaluate or add another orchestration backend without rewriting World State, Decision Room, governance, evidence, or execution services.

## Agent model

### Supervisor

The supervisor owns:

- task decomposition;
- dependency planning;
- capability discovery;
- agent selection;
- delegation and handoff;
- iteration/time/token budgets;
- progress events;
- failure recovery;
- synthesis routing.

The supervisor does not own business truth.

### Specialist agents

Initial domain families:

- Procurement / Sourcing
- Logistics / Route / Load Optimization
- Booking / Carrier Negotiation
- Compliance / Documentation / Finance validation

Additional specialists can be registered when grounded capabilities exist.

Each specialist receives a bounded `AgentContext`:

```text
workspace_id
tenant_id
task_id
trace_id
world_state_version
entity scope
allowed capabilities
evidence scope
policy scope
budget
iteration limit
```

## Capability discovery

Nexus must discover what can actually be used before planning execution.

Sources include:

```text
Tool Registry
MCP servers
Connected application adapters
Document/knowledge index
Graph tools
World State query tools
Scenario tools
Approved execution adapters
```

A capability declaration contains:

```text
capability_id
name
version
description
input_schema
output_schema
read/write classification
authorization requirements
workspace availability
side-effect class
timeout
budget
provenance requirements
```

The planner can only assign capabilities present in the authorized workspace registry.

## Tool safety model

Every tool invocation passes through a Nexus tool gateway.

```text
Agent
  -> Tool Gateway
      -> identity / tenant check
      -> workspace check
      -> capability check
      -> argument validation
      -> policy classification
      -> budget check
      -> invocation
      -> evidence capture
      -> audit record
```

Agents never receive direct database credentials and never bypass the gateway for consequential actions.

## Graph memory

The operational graph is a contextual memory layer, not a second source of truth.

```text
Authoritative World State
          |
          v
Canonical operational graph
          |
          +--> entity neighborhood
          +--> relationships
          +--> dependencies
          +--> historical links
          +--> signals
          +--> decisions
          +--> evidence
```

Graph reads must be reproducible from authoritative state. Graph mutations that change operational truth are committed through World State services, not directly by agents.

The graph is used to construct task context and reduce repeated discovery work across agent steps.

## Scenario Studio

Scenario simulation is a separate product capability from the dashboard and is isolated from production World State.

```text
World State vN
      |
      +------> Scenario A
      |
      +------> Scenario B
      |
      +------> Scenario C
```

A scenario contains:

- immutable base World State version;
- parameter overrides;
- proposed actions;
- simulation configuration;
- model versions;
- assumptions;
- resulting state deltas;
- outcome metrics;
- comparison metadata.

Users can alter scenario parameters and re-run simulations without modifying production state.

## Simulation output

The UI should support comparison across dimensions such as:

```text
service level
stockout exposure
inventory value
lead time
transport cost
risk
working capital
capacity utilization
expected margin
```

Metrics must be derived from the scenario state and the approved simulation/model implementation. No static “good/bad” values may be embedded in the UI.

## Decision synthesis

The final recommendation is a structured object, not free-form prose alone:

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

Narrative text is generated from this structured result.

## Autonomy boundary

Nexus is autonomous in:

- understanding a task;
- discovering capabilities;
- planning;
- information gathering;
- specialist delegation;
- analysis;
- graph exploration;
- scenario generation;
- simulation;
- recommendation.

Nexus is governed in:

- consequential write actions;
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

A future customer policy may permit bounded automation for explicitly classified low-risk actions, but that is a governed policy capability rather than an implicit agent behavior.

## Persistence requirements

Agent execution state that must survive process restart belongs in persistent stores:

- task record;
- workflow state/checkpoint where applicable;
- agent run records;
- tool invocation records;
- evidence references;
- decision records;
- scenario records;
- approval records;
- execution records;
- outcome records.

In-memory agent state may be a performance optimization only.

## Realtime contract

The orchestration UI consumes committed events through the existing transactional outbox:

```text
task.created
task.step.started
task.step.completed
tool.invoked
tool.completed
scenario.created
scenario.completed
decision.proposed
approval.recorded
execution.completed
outcome.recorded
```

Events are progress/state-change notifications. They never become authoritative state.

## Framework implementation phases

### MAF-1 — Nexus orchestration contract

Create:

- `TaskContext`
- `TaskPlan`
- `AgentContext`
- `CapabilityDescriptor`
- `ToolInvocation`
- `AgentProposal`
- `TaskResult`
- `NexusOrchestrator` interface

### MAF-2 — Framework adapter

Implement the Agent Framework adapter using framework-native agents, tools, workflows, and orchestration patterns.

Start with:

```text
Supervisor
  |
  +--> parallel specialist analysis
  |
  +--> evidence aggregation
  |
  +--> critic
  |
  +--> synthesis
```

### MAF-3 — Capability registry

Replace hardcoded tool selection with workspace-scoped capability discovery.

### MAF-4 — Grounded tool gateway

Connect each capability to authoritative Nexus services and external adapters.

### MAF-5 — Graph context provider

Construct bounded graph context from the requested entities and World State version.

### MAF-6 — Scenario integration

Allow agents to create, mutate, simulate, and compare isolated scenarios through controlled tools.

### MAF-7 — Decision Room integration

Stream plan/progress/evidence/simulation/recommendation state into the operational UI.

### MAF-8 — Production evaluation

Measure:

- task success rate;
- groundedness;
- tool selection accuracy;
- unnecessary tool calls;
- latency;
- cost;
- policy-block rate;
- human override rate;
- simulation recommendation quality;
- outcome accuracy.

## Non-negotiable restrictions

No framework may:

- write directly to PostgreSQL business tables;
- bypass tenant/workspace authorization;
- fabricate evidence;
- fabricate model outputs;
- invent external system capabilities;
- execute a consequential action without the Nexus authorization path;
- turn a realtime event into the source of truth.

## Launch target

The first end-to-end platform demonstration should be a real task such as:

> “Find the highest-risk inventory exposure this week, determine why it is happening, identify feasible supplier/logistics interventions, simulate the alternatives, recommend the best action under our constraints, and prepare it for approval.”

The visible experience should show the same task moving through:

```text
Task
 -> Plan
 -> Capability discovery
 -> Agent activity
 -> Graph context
 -> Evidence
 -> Scenarios
 -> Comparison
 -> Recommendation
 -> Approval
 -> Outcome
```

This is the core Nexus product experience.
