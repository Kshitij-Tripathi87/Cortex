# Cortex Release Candidate — RC-2 (Program H Complete)

**Release Date:** 2026-07-20  
**Version:** 0.3.0  
**Status:** Launch Hardening In Progress

---

## Frozen API Contracts

The following API contracts are frozen for launch. No breaking changes allowed without major version bump.

### Graph API (`/api/v1/graph`)
- `POST /batches/{batch_id}/compile` — Compile evidence to graph
- `GET /nodes` — List graph nodes
- `GET /edges` — List graph edges
- `GET /snapshots` — List graph snapshots
- `GET /snapshots/{snapshot_id}` — Get snapshot detail
- `GET /integrity` — Run integrity checks
- `POST /traverse` — BFS/DFS traversal
- `POST /shortest-path` — Shortest path computation
- `POST /reachable` — Reachability computation
- `POST /paths` — Find all paths
- `POST /snapshots/diff` — Diff two snapshots
- `GET /validate` — Validation suite
- `GET /features` — Workspace features
- `GET /features/{node_id}` — Node features
- `GET /signals` — Detect signals
- `POST /propagate` — Run propagation
- `POST /scenarios` — Execute scenario
- `POST /recommendations/generate` — Generate recommendations
- `GET /recommendations/taxonomy` — Get recommendation taxonomy
- `GET /recommendations/types` — List recommendation types
- `POST /decisions` — Create decision record
- `POST /decisions/{id}/outcomes` — Append outcome
- `POST /decisions/{id}/lessons` — Append lesson
- `GET /decisions/{id}` — Get decision snapshot
- `GET /decisions` — List decisions
- `GET /decisions/{id}/export` — Export decision for ML
- `GET /decisions/taxonomy` — Get decision taxonomy

### Sources API (`/api/v1/sources`)
- `POST /upload` — Upload file
- `GET /batches/{id}` — Batch status
- `GET /files/{id}/profile` — File profile
- `GET /batches/{id}/claims` — List claims
- `GET /batches/{id}/conflicts` — List conflicts
- `POST /conflicts/{id}/resolve` — Resolve conflict
- `POST /batches/{id}/compile` — Extract claims, detect conflicts

### Readiness API (`/api/v1/readiness`)
- `POST /batches/{id}` — Compute readiness
- `GET /assessments/{id}` — Get readiness assessment

### Audit API (`/api/v1/audit`)
- `GET /` — List audit events

---

## Frozen Taxonomies

### Decision Types (Program H)
- `approve_recommendation` — Terminal, Reversible
- `approve_with_modification` — Terminal, Reversible
- `reject_recommendation` — Terminal, Irreversible
- `defer_decision` — Non-terminal, Reversible
- `request_more_evidence` — Non-terminal, Reversible
- `escalate_for_review` — Non-terminal, Irreversible
- `no_action_monitor` — Terminal, Reversible

### Outcome Statuses
- `success`, `partial_success`, `failed`, `no_impact`, `unintended_consequences`, `pending`

### Lesson Categories
- `policy_error`, `assumption_error`, `data_quality_issue`, `model_bias`, `process_gap`, `success_pattern`, `best_practice`

### Scenario Types (Program F)
- `supplier_failure`, `warehouse_outage`, `route_closure`, `shipment_delay`, `demand_spike`, `demand_drop`, `inventory_shortage`, `capacity_constraint`, `custom`

### Recommendation Types (Program G)
- `expedite_shipment`, `use_alternate_supplier`, `transfer_inventory`, `rebalance_stock`
- `prioritize_critical_orders`, `delay_low_priority_orders`, `split_fulfillment`
- `reroute_shipment`, `expedite_alternative_carrier`
- `hold_shipment_pending_review`, `reallocate_to_critical_customers`
- `no_action_monitor`, `custom`

---

## Component Versions

| Component | Version | Commit | Notes |
|-----------|---------|--------|-------|
| Backend | 0.3.0 | TBD | Programs A-H complete |
| Frontend | 0.2.0 | TBD | Next.js 14, all 7 pages functional |
| Database Schema | 004 | TBD | 4 migrations (initial, RLS, graph, decisions) |
| Test Suite | 348 tests | TBD | 100% Programs A-H coverage |
| Docker Compose | 1.0.0 | TBD | PostgreSQL 16, Redis 7, MinIO, Prometheus, Grafana |
| CI Workflows | 5 | TBD | lint, test, typecheck, security, build |

---

## Known Limitations (Pre-Launch)

These items are tracked in the launch hardening plan and must be closed before launch:

1. **S3 Raw-Byte Ingestion** — Compiler currently uses profiler path; needs direct S3 byte streaming for production
2. **Redis Cache Invalidation** — Cache layer exists but invalidation strategy not production-hardened
3. **DB-Backed Versioning** — Some paths still use `snapshot_version = 1` hardcoded; needs monotonic DB versioning
4. **Recommendation API Wiring** — Must verify end-to-end real engine output, no placeholders
5. **AuthZ Rate Limits** — Workspace scoping enforced but rate limits/circuit breakers need verification
6. **Frontend Error States** — All 7 pages functional but loading/error/retry states need completion

---

## Upgrade Path

### From RC-1 (0.2.0)
```bash
# Apply new migration
alembic upgrade 004

# Verify test suite
pytest tests/ -v --tb=short

# Expected: 348 tests passing
```

### From 0.1.0
```bash
# Apply all migrations
alembic upgrade head

# Verify test suite
pytest tests/ -v --tb=short
```

---

## Rollback Plan

If launch issues occur:

1. **Database Rollback**
   ```bash
   alembic downgrade 003  # Remove decision memory tables
   ```

2. **Code Rollback**
   ```bash
   git revert --no-commit HEAD~N..HEAD  # Revert launch changes
   git checkout rc-1-tag
   ```

3. **Docker Rollback**
   ```bash
   docker compose down
   docker compose up -d --force-recreate backend:rc-1
   ```

---

## Sign-Off

| Role | Name | Date | Status |
|------|------|------|--------|
| Backend Lead | TBD | — | Pending |
| Frontend Lead | TBD | — | Pending |
| Platform Lead | TBD | — | Pending |
| QA Lead | TBD | — | Pending |
| Security Review | TBD | — | Pending |

---

**Next Milestone:** Launch (0.3.0) — After hardening Steps 2-9 complete