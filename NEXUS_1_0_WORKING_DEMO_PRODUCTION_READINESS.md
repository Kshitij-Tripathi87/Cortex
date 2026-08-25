# Cortex Nexus 1.0 — Working Demo & Production Readiness Execution Pack

## Objective

Produce a real, repeatable Nexus demonstration in which a user:
1. Starts the complete stack (`docker compose -f docker-compose.prod.yml up --build`);
2. Creates an isolated workspace;
3. Uploads operational CSV/XLSX data;
4. Watches data profiling and entity resolution complete;
5. Sees the operational graph grow from the uploaded data;
6. Explores graph relationships, signals, risk and blast radius;
7. Asks Nexus a natural-language operational question;
8. Receives an answerability preflight, structured answer and evidence links;
9. Watches the relevant specialist agents communicate and deliberate;
10. Compares counterfactual actions in the Digital Twin;
11. Reviews a governed decision and its evidence chain;
12. Approves an action in an explicitly controlled demo environment;
13. Injects a live event;
14. Sees the graph/world state update;
15. Sees the prior decision become invalid if its dependency set changed;
16. Triggers re-deliberation and re-simulation;
17. Observes the refreshed decision.

The current architecture and operating loop are source-defined as:
$$\text{Data Ingestion / Resolution} \to \text{Dynamic Graph} \to \text{Anomaly / Blast Radius} \to \text{Deliberation} \to \text{Twin Simulation} \to \text{Governed Decision / Evidence} \to \text{Execution} \to \text{Live Mutation} \to \text{Invalidation / Redeliberation}$$

---

## Release Maturity Boundary

Do not conflate:
* **Engineering RC1**: Code, contracts, state machines, services and automated acceptance verified.
* **Production-Ready Deployment**: Hardened infrastructure, recovery, secrets, observability, failover and operational controls verified.
* **Production-Validated Product**: Real enterprise data and empirical decision-quality/NEV evidence.
* **Operationally Proven**: Longitudinal commercial evidence across multi-quarter enterprise pilots.

The working demo may ship before the latter two stages, but its UI and documentation must label simulated/controlled results accurately:
`CONTROLLED DEMO BENCHMARK • DETERMINISTIC EXECUTION SANDBOX`.

---

## Demo Environment & Local Launch Contract

### Required Services (9 Clustered Containers)
1. `frontend`: Next.js 14 Production Server
2. `backend`: FastAPI Clustered Node Alpha
3. `postgres`: PostgreSQL 16 Source of Truth
4. `redis`: Redis 7.2 Cache & Distributed Locks
5. `kafka`: Apache Kafka KRaft 7.6.0
6. `object-storage`: MinIO S3 Storage
7. `agent-runtime`: Multi-Agent Swarm Worker
8. `simulation-worker`: Digital Twin Simulation Worker
9. `realtime`: Realtime Gateway API Process

### Local Launch Command
```bash
docker compose -f docker-compose.prod.yml up --build
```

---

## Working Demo Script (6-Minute Deterministic Journey)

| Time | Stage | Action & Operator Experience |
| :---: | :--- | :--- |
| **00:00** | **Open Nexus** | Open `http://localhost:3000/workspace/cockpit`. Connection status: `ONLINE`, World State: `v101`. |
| **00:15** | **Upload Dataset** | Navigate to `/workspace/data` or drop `olist_sellers_dataset.csv` + `olist_orders_dataset.csv`. |
| **00:45** | **Data Quality** | State transitions: `UPLOADED ➔ PARSING ➔ PROFILING ➔ RESOLVING ➔ GRAPHING ➔ READY`. Display 100% completeness. |
| **01:00** | **Graph Render** | Dynamic graph renders on hardware canvas (784 nodes, 942 edges). |
| **01:20** | **Select Entity** | Select focal Single Point of Failure: `seller_01a00b8e99` (PageRank: 0.042, Betweenness: 0.31). |
| **01:40** | **Signals & Risk** | View `SELLER_DEGRADATION (+90%)` signal and `$1,746.00 USD` revenue exposure across 12 orders. |
| **02:00** | **Ask Nexus** | Ask natural language question: *"What is the revenue risk for seller_01a00b8e99?"* |
| **02:20** | **Evidence Answer** | Receive structured answer with readiness preflight report, key reasons, and data citations. |
| **02:40** | **Decision Room** | Open Agent Deliberation Protocol. |
| **03:00** | **Agent Messages** | Inspect structured messages: `OBSERVATION`, `CRITIQUE`, `PROPOSAL`, `SYNTHESIS` (Consensus: 0.94). |
| **03:30** | **4 Counterfactuals** | Run Digital Twin simulation comparing Candidates A ($-\$4.2\text{k}$), B ($+\$1.3\text{k}$), C ($+\$2.9\text{k}$), D ($+\$1.95\text{k}$). |
| **04:00** | **Recommendation** | Candidate C yields highest simulated Net Economic Value ($+\$2,900.00$) and 98% SLA protection. |
| **04:20** | **Evidence Graph** | Inspect cryptographically verifiable SHA-256 Merkle DAG and 9-part semantic version tuple. |
| **04:40** | **Controlled Approval**| Click **"Approve Candidate C"** with operator governance handoff (Owner: Procurement, Reviewer: COO). |
| **05:00** | **Live Event** | Click **"⚡ Test Mutation"** (injects real-time stream telemetry modification). |
| **05:10** | **Graph Mutation** | World State increments from `v101 ➔ v102`. Real-time reconciliation vector updates. |
| **05:15** | **Decision Invalidation**| Decision `DEC-1029` transitions from `VALID ➔ INVALIDATED` with visible drift explanation. |
| **05:30** | **Redeliberation** | Click **"Trigger Swarm Redeliberation"** $\to$ agents re-deliberate on mutated state in $<600\text{ms}$. |
| **06:00** | **Refreshed Decision** | New decision generated and verified against World State `v102`. |
