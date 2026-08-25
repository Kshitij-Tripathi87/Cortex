# Cortex — Technical Deep Dive

For: CTO, Head of Data, Integration Engineer.
Read time: ~12 minutes.

## 1. Architecture at a glance

```
                  ┌──────────────────────────────────────────┐
                  │           Supply-chain graph             │
                  │  (suppliers, components, products,       │
                  │   warehouses, orders, BOMs, lead times) │
                  └────────────────┬─────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │                      │                      │
            ▼                      ▼                      ▼
   ┌─────────────────┐   ┌──────────────────┐   ┌─────────────────┐
   │   Propagation   │   │  Confidence      │   │   Timeline      │
   │   (graph walk)  │   │  (5 sub-scores)  │   │  (depletion)    │
   └────────┬────────┘   └─────────┬────────┘   └────────┬────────┘
            │                      │                      │
            └──────────────────────┼──────────────────────┘
                                   ▼
                         ┌──────────────────┐
                         │     Impact       │
                         │  (6 components)  │
                         └─────────┬────────┘
                                   ▼
                         ┌──────────────────┐
                         │   Ranking        │
                         │  (net benefit)   │
                         └─────────┬────────┘
                                   ▼
                         ┌──────────────────┐
                         │  Decision Brief  │
                         │   (one screen)   │
                         └──────────────────┘
```

Every box is pure-functional Python. No hidden state, no LLM, no database
calls inside the math.

## 2. The contract

The single API surface is `POST /api/v1/briefs/supplier-failure`. It returns
a `DecisionBrief` JSON document with `contract_version: "0.3.0"`. The
schema is frozen for the MVP.

The schema is generated from Pydantic and served at
`/openapi.json`. The frontend types are generated from the same
document, so the contract is the source of truth.

## 3. The math

### 3.1 Propagation

A supplier-failure scenario is a node-deletion in the supply-chain graph.
We perform a BFS from the failed supplier, propagating `attenuated_exposure`
through each edge (default attenuation = 0.5 per hop). The result is a
set of affected components, products, warehouses, and open orders.

### 3.2 Confidence

Five deterministic sub-scores, all in `[0, 1]`:

- **Completeness** — fraction of required entities present in the snapshot.
- **Freshness** — `exp(-Δt / τ)` where `τ` is configurable per data source.
- **Agreement** — inverse of pairwise disagreement across data sources.
- **Conflict density** — `1 - (conflicting_edges / total_edges)`.
- **Coverage** — fraction of affected orders with a known customer impact.

The overall confidence is a weighted geometric mean.

### 3.3 Impact

Six components, each in `[0, 100]`:

- `revenue_risk_usd` × weight
- `margin_risk_usd` × weight
- `penalty_exposure_usd` × weight
- `working_capital_impact_usd` × weight
- `customer_impact_score` × weight
- `operational_impact_score` × weight

The weights are configurable per workspace. The formula string is
returned in the response so it is auditable.

### 3.4 Ranking

Each action in your playbook is scored on:

- `net_benefit` (primary)
- `execution_cost_usd`
- `execution_time_hours`
- `confidence`
- `business_impact_reduction`
- `customer_impact_protected`
- `operational_risk`
- `dependency_readiness`

We rank by `net_benefit` descending. The formula is returned in the
response.

## 4. The data

The MVP connector is **CSV only**. The contract:

| File | Required columns |
| --- | --- |
| `suppliers.csv` | `id`, `name`, `country`, `tier`, `lead_time_days` |
| `components.csv` | `id`, `sku`, `name`, `unit_cost_usd` |
| `products.csv` | `id`, `sku`, `name` |
| `boms.csv` | `product_id`, `component_id`, `qty_per_unit` |
| `warehouses.csv` | `id`, `name` |
| `inventory.csv` | `warehouse_id`, `component_id`, `quantity`, `safety_stock`, `daily_usage` |
| `orders.csv` | `id`, `customer_id`, `product_id`, `quantity`, `due_date`, `status` |
| `supplier_components.csv` | `supplier_id`, `component_id` |

The loader is idempotent. Re-uploading the same file is a no-op.

## 5. The backtest

`python scripts/run_backtest.py --scenario supplier_delay` runs the canonical
scenario against the seeded dataset and reports:

- Accuracy
- Precision
- Recall
- F1
- Confusion matrix (TP / FP / FN)

The scenario file is the ground truth. New scenarios can be added by
extending `app/modules/disruption/scenarios/`.

## 6. Non-goals for the MVP

- No real-time connectors. CSVs are uploaded by an integration engineer.
- No auth beyond a workspace UUID. Production-grade auth is post-pilot.
- No multi-tenant isolation at the DB layer. One workspace per deployment.
- No persistence of briefs. Every request recomputes from the snapshot.

## 7. Performance

The full pipeline runs in under 2s on the seeded dataset (5 orders, 4
components, 2 products, 1 warehouse, 2 suppliers). Linear in the size of
the affected subgraph.

## 8. Where to look in the code

| Component | File |
| --- | --- |
| API entry | `backend/app/api/v1/briefs.py` |
| Orchestrator | `backend/app/modules/disruption/runner.py` |
| Propagation | `backend/app/modules/disruption/engines/propagation.py` |
| Confidence | `backend/app/modules/disruption/engines/confidence.py` |
| Impact | `backend/app/modules/disruption/engines/impact.py` |
| Ranking | `backend/app/modules/disruption/engines/ranking.py` |
| Timeline | `backend/app/modules/disruption/engines/timeline.py` |
| Scenarios | `backend/app/modules/disruption/scenarios/` |
| Backtest runner | `backend/scripts/run_backtest.py` |
| Frontend | `frontend/src/features/morning-brief/` |
