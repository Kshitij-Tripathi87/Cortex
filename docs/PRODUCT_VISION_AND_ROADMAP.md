# Cortex Product Vision and Roadmap

**Status:** Product direction for planning and prioritisation  
**Date:** 2026-11-03  
**Repository:** `Kshitij-Tripathi87/Cortex`

> **Definitive product identity:** Cortex is a **Unified Enterprise Intelligence & Action Platform**.
> The initial product strategy is narrower: prove trusted supplier-disruption decision intelligence,
> then graduate orchestration and governed action on the same foundation.

## 1. Executive definition

Cortex is the **Unified Enterprise Intelligence & Action Platform for complex enterprises**.

It turns fragmented operational data into one continuously versioned view of reality, explains how events propagate through the operating system, evaluates possible responses, and helps authorised people make and execute decisions with evidence, policy, and outcome history attached.

The first commercial wedge is **supply-chain disruption and mitigation**. Supply chain is the initial proving ground, not the permanent category boundary. The durable product is the intelligence layer for operations across manufacturing, logistics, procurement, inventory, service delivery, and other environments where decisions depend on interconnected systems.

The product loop is:

> **Connect → Understand → Reason → Verify → Decide → Coordinate → Learn**

The customer-facing promise is:

> **Understand your enterprise. Trust your decisions. Coordinate your actions.**

The product is not primarily a chatbot, dashboard, forecasting tool, ERP replacement, generic AI copilot,
or unrestricted autonomous agent. AI is a replaceable interface and reasoning component;
**trusted operational state, evidence, policy, and traceability are the foundation**.

## 2. Product vision

Every important operational decision should be made against a shared, current, explainable model of the enterprise—not disconnected spreadsheets, stale dashboards, undocumented assumptions, or ungoverned AI output.

Cortex will become the system that connects:

1. **Enterprise data** — ingesting structured and semi-structured operational sources.
2. **Operational state** — reconstructing entities, relationships, constraints, events, and versions.
3. **Causal understanding** — identifying signals, risks, dependencies, and impact propagation.
4. **Decision intelligence** — comparing scenarios and recommendations against explicit objectives and constraints.
5. **Governed action** — moving from proposal to approval to controlled execution.
6. **Decision memory** — recording evidence, assumptions, outcomes, and forecast accuracy so the system improves.
7. **Governed orchestration** — turning a bounded user objective into authorised tasks, capability calls,
   approvals, and recoverable actions.

The long-term ambition is a reusable **enterprise operational intelligence substrate**: a platform on which domain-specific workflows and specialist agents can operate safely without inventing authority or bypassing enterprise controls.

## 3. Product principles

### 3.1 One authoritative world

PostgreSQL-backed world state is the authority. Graphs, projections, caches, UI state, and model context are derived and rebuildable. No in-memory singleton may be treated as enterprise truth.

### 3.2 Evidence before assertion

Every material signal, risk, recommendation, decision, and outcome must be traceable to source data, transformations, assumptions, and model or policy versions. If a claim cannot be checked, it must be labelled as uncertain or future capability.

### 3.3 Simulation before commitment

The default path is inspect, compare, and simulate before approval. Recommendations are proposals, not authority.

### 3.4 Humans govern consequential action

Permissions, roles, approvals, separation of duties, stale-state checks, policy gates, and immutable audit trails are product features—not infrastructure afterthoughts.

### 3.5 Deterministic core, probabilistic assistance

State transitions, permissions, evidence lineage, event ordering, and execution policy must be deterministic and testable. ML and LLM components may assist classification, prediction, retrieval, and explanation, but cannot manufacture authority or silently mutate the world.

### 3.6 Show the operational consequence

The product should answer: what changed, why it matters, what will happen next, what options exist, what each option costs or protects, and who must approve it.

### 3.7 Narrow wedge, expandable substrate

Launch with a high-value supply-chain disruption workflow. Build reusable primitives so later domains extend the ontology, connectors, policies, and playbooks rather than requiring a new product.

### 3.8 No demo leakage

Demo fixtures, legacy in-memory routes, hardcoded risks, silent fallbacks, and swallowed API failures must never appear in the customer journey. A missing or stale data response must be visible and actionable.

### 3.9 Operational reliability is part of value

Durable events, replay, resynchronisation, tenant isolation, backup/restore, observability, and deployment rehearsal are required for trust. A feature that works only in a single process is not a product capability.

## 4. Capability map

### A. Data and connectivity foundation

- Source registration and connector contracts
- CSV and bulk data ingestion
- Schema profiling, validation, claims, and conflicts
- Idempotency, provenance, lineage, and source freshness
- Workspace and tenant isolation
- Data-quality and readiness status

### B. Operational world model

- Canonical entities: products, components, suppliers, factories, warehouses, orders, customers, and routes
- Relationships, BOMs, dependencies, constraints, and capacities
- Versioned world state and event history
- Graph traversal, state diff, replay, rollback, and verification
- Digital-twin and snapshot lifecycle

### C. Detection and understanding

- Signals and anomaly detection
- Risk records and prioritisation
- Critical-node and dependency analysis
- Impact propagation through the operational graph
- Forecasts, observations, calibration, bias, and confidence
- Evidence DAG and explanation surfaces

### D. Decision intelligence

- Scenario creation and counterfactual simulation
- Alternatives, constraints, objectives, and trade-offs
- Recommendations with rationale and evidence
- Decision lifecycle and decision memory
- Forecast-versus-outcome feedback loop
- Role-oriented briefs and investigations

### E. Governance and execution

- Role and tool permissions
- Approval workflows and separation of duties
- Stale-world-state protection
- Policy and safety gates
- Controlled execution adapters
- Outcome recording and immutable audit trail

### F. Real-time and platform operations

- Transactional outbox
- Redis fan-out and workspace sequence numbers
- SSE/WebSocket delivery
- Replay and client resynchronisation
- Health, readiness, metrics, tracing, and structured logs
- Backup, restore verification, deployment, and disaster recovery

### G. Orchestration and extensibility

- Grounded assistant using authorised tools
- Task intent, planning, capability discovery, delegation, and durable task state
- Nexus-owned Tool Gateway for every agent/tool invocation
- Specialist agents and agent lifecycle controls
- Model registry, evaluation, promotion, rollback, and drift
- GNN/RL and advanced optimisation capabilities
- Plugin and connector architecture

### H. SaaS control plane

- Organisations, workspaces, users, roles, and secure access
- Usage metering, plans, entitlements, integrations, and administration
- Enterprise configuration and support operations

## 5. MVP boundary: Cortex v1 operational decision loop

The MVP is a **customer-usable, end-to-end disruption-to-decision workflow**, not the whole capability map.

### MVP promise

For one customer workspace, Cortex can accept a defined supply-chain dataset, reconstruct a trustworthy operational world, identify a material disruption, show its evidence and propagation, compare response scenarios, and guide an authorised user through approval and controlled execution while recording the outcome.

### In scope

1. Account creation, login, session handling, password reset, one workspace per organisation.
2. CSV/bulk ingestion for the initial supply-chain data contract.
3. Validation, data-readiness report, provenance, conflicts, and ingestion status.
4. PostgreSQL-backed world state and operational graph.
5. Canonical signals, risks, evidence, scenarios, decisions, approvals, execution, and outcomes APIs.
6. A focused authenticated UI for cockpit, world state, risk detail, scenario comparison, decision review, and evidence.
7. Human-supervised decision lifecycle: draft → proposed → approved → authorised → executed → outcome.
8. Real-time updates with durable outbox relay, replay, sequence-gap detection, and resynchronisation.
9. Tenant/workspace authorization, audit records, policy gates, and visible failure states.
10. Basic production operations: observability, backups, restore rehearsal, staging deployment, and security review.
11. Usage metering for tasks, runs, and actions, even while final billing remains staged.

### Explicitly out of MVP

- Autonomous or unsupervised execution
- Broad multi-industry ontology and dozens of connectors
- Full billing, enterprise marketplace, and complex entitlement tiers
- SSO/SAML, multi-region active-active, service mesh, and Kafka
- Mobile applications
- General-purpose autonomous multi-agent operations
- Production-critical GNN/RL optimisation surfaces
- LLM-generated authority, opaque recommendations, or ungrounded chat
- A large dashboard suite that does not support a decision workflow
- Mobile and voice as a core product requirement
- Multiple model providers at launch; begin with one hosted provider behind an adapter
- GNN/RL models as production decision authorities before evaluation and rollback gates pass

### Risk-tiered autonomy

| Tier | Activity | Default control |
| --- | --- | --- |
| R0 | Read authorised data | Automatic within permissions |
| R1 | Analyse and simulate | Automatic within limits |
| R2 | Produce recommendations | Proposal only |
| R3 | Reversible internal action | Policy check and conditional approval |
| R4 | Financial commitment, production write, external communication, or irreversible action | Human approval by default |

This control is enforced by the backend capability and policy boundary, not by frontend buttons or agent instructions.

### Signature trust capability: Decision Receipt

A Decision Receipt is the reconstructable record of consequential work. It links original data and evidence,
dataset and World State versions, calculations/model/policy versions, scenarios, assumptions, confidence,
recommendation, approval identity, execution details, and observed outcome. It is the external product concept
built over durable decision/task records and NexusTrace; it does not replace the authoritative decision lifecycle.

## 6. Customer value proposition

### Primary statement

**Cortex helps operations teams understand disruption, compare response options, and act with confidence—using one evidence-backed view of their operational reality.**

### For operations leaders

See the business impact of a disruption across suppliers, inventory, production, orders, and customers before committing to a response.

### For planners and analysts

Replace manual cross-spreadsheet investigation with a traceable operational graph, scenario comparison, and reusable decision memory.

### For executives and risk owners

Know what changed, which decisions are available, what each option protects or costs, and whether the recommendation is supported by evidence.

### For technology, security, and governance teams

Deploy intelligence without surrendering control: isolated workspaces, explicit permissions, durable state, auditability, policy gates, and reversible rollout.

### Value proof metrics

The product should measure, not merely claim:

- Time from data arrival to validated operational view
- Time from disruption detection to decision-ready alternatives
- Investigation steps and manual handoffs avoided
- Evidence coverage for decisions
- Scenario accuracy versus observed outcomes
- Forecast calibration and bias over time
- Approval and execution policy compliance
- Data freshness, event delivery, and recovery SLOs

## 7. Reconciliation with the existing GitHub architecture

### Keep and make authoritative

- `backend/app/modules/world`, `graph`, `ontology`, `sources`, `ingestion`
- Persistent Nexus services and `/api/v1/nexus/*`
- Alembic migrations and PostgreSQL persistence
- Evidence, decision, approval, execution, outcome, and audit models
- AuthZ and workspace-scoping controls
- Transactional outbox and realtime infrastructure
- Frontend API clients, workspace shell, graph, evidence, decisions, and scenario components

The architectural invariant remains:

> **One authoritative world, one trace, one governed decision loop, one evidence chain.**

### Promote to the customer path

- Rewire authenticated frontend screens from `/workspace/*` and `/graph/*` demo paths to canonical `/nexus/*`, `/world/*`, `/sources/*`, and `/simulation/*` APIs.
- Make the cockpit render persisted risks and evidence rather than `demoRisks` or fixture data.
- Complete the outbox relay deployment and frontend sequence-gap/resync behavior.
- Prove ingestion → world state → signal/risk → scenario → decision with a real end-to-end test.

### Keep mounted but defer

- GNN, RL, twin, multi-agent, Workflo, and advanced agent-runtime surfaces are strategic extensions, not MVP dependencies.
- `/v07-legacy/*` and the in-memory `/workspace/*` paths should be test/migration-only, then removed or hard-gated.
- Kafka should not remain a required MVP production dependency unless a measured workload justifies it.

### Architecture risks to manage

- Too many overlapping product surfaces and route families
- Product terminology split across Cortex, Nexus, Workflo, and release slices
- Demo and legacy code still reachable from the application
- Large backend surface area relative to the focused MVP
- Strong recorded test claims that still require repeatable staging execution
- Public repository has no product description, topics, release, or README positioning

## 8. Phased roadmap

### Phase 0 — Product and architecture alignment

**Objective:** establish one product story and one authoritative customer path.

- Adopt this document as the product baseline.
- Rename and classify capabilities as Core, Expansion, or Research.
- Define the canonical vocabulary: Cortex platform; Nexus operational decision loop.
- Inventory every route and API; mark canonical, legacy, demo, or deferred.
- Add a real repository README, product description, topics, and release notes.
- Freeze new surface-area expansion until the MVP path is green.

**Exit:** one agreed MVP journey, one canonical API path, and no ambiguity about what is production authority.

### Phase 1 — MVP operational decision loop

**Objective:** make one supply-chain disruption workflow genuinely customer-usable.

- Finish frontend canonical rewire and cockpit rework.
- Land and verify durable outbox relay and realtime resync.
- Complete ingestion-to-world-state vertical slice.
- Harden evidence, approvals, execution policy, audit, and failure states.
- Run staging deployment, backup restore, security review, and golden-path E2E.

**Exit:** a design partner can onboard, load defined data, investigate a disruption, compare scenarios, approve an action, execute under policy, and inspect the outcome without engineering repair.

### Phase 2 — Pilot hardening and repeatability

**Objective:** support multiple design partners with repeatable onboarding and operational reliability.

- Connector templates and import mapping tools
- Data-quality and freshness operations
- Saved investigations, briefs, and decision workspaces
- Admin/support/status tools and transactional email
- Trial entitlement and billing foundation
- Redis-backed rate limits, token/session hardening, and SSO discovery
- RPO/RTO measurements, chaos tests, and tenant-isolation verification

**Exit:** repeatable pilot deployment with measured adoption, reliability, decision-cycle, and value metrics.

### Phase 3 — Operational intelligence platform

**Objective:** expand from a wedge product into a reusable enterprise platform.

- More connectors and domain packs
- Richer ontology and cross-functional operational views
- Model registry, promotion, drift, and evaluation as managed product workflows
- Role-based morning briefs and proactive risk monitoring
- Constrained specialist agents for investigation and analysis
- Plugin architecture for customer policies, tools, and execution adapters

**Exit:** multiple operational domains can be configured on the same authoritative substrate without forking the product.

### Phase 4 — Governed optimisation network

**Objective:** enable advanced optimisation while preserving control.

- GNN-based representation and risk propagation
- RL and optimisation for candidate generation, never direct unapproved action
- Multi-agent specialist coordination with shared evidence and policy
- Portfolio-level and network-level scenario planning
- Closed-loop learning from outcomes and human feedback
- Enterprise federation, advanced identity, and regional resilience

**Exit:** Cortex improves the quality and speed of operational decisions across a network while remaining explainable, auditable, and bounded by policy.

## 9. Prioritisation rule

When deciding whether to build a feature, ask:

1. Does it improve the operational decision loop?
2. Does it use or strengthen the authoritative world and evidence chain?
3. Can a customer verify its result?
4. Is its failure mode visible and safe?
5. Does it reduce time-to-decision or improve decision quality?
6. Can it ship without creating another competing path?

If the answer to most of these is no, the feature belongs in research or a later phase—not in the MVP.

## 10. Current repository status and planning implication

The public GitHub repository is **public, active, not archived, MIT-licensed, and on `main`**, with approximately 34 commits, three open issues reported by the GitHub API, no stars, no releases, and no repository description or topics. The local checkout is tracking `origin/main` at commit `15edf97` (`Delete product directory`) with a clean working tree.

The repository is technically ahead of its public product presentation. The immediate strategic need is not another broad subsystem; it is to convert the existing persistent Nexus architecture into one coherent, demonstrable, customer-ready Cortex journey, then use real pilot evidence to decide which advanced capabilities deserve Phase 3 and Phase 4 investment.
