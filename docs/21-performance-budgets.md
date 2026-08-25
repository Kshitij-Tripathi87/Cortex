# 21 — Performance Budgets

| Field | Value |
|---|---|
| Version | 1.0.0 |
| Status | Frozen |
| Owner role | Principal Engineer |
| Depends on | `01-architecture.md` (NFRs), `10-testing-and-ci-cd.md` (perf tests), `22-observability-model.md` |
| Frozen | Phase 1.5 (AR-001) |
| Change log | 1.0.0 — initial freeze |

---

## 1. Purpose

Without explicit budgets, performance degrades silently. Phase 1.5 freezes a
**budget per subsystem**, an enforcement mechanism, and a remediation rule
when a budget is exceeded. Budgets are SLO inputs and CI gates — not aspirational
targets. A subsystem that overruns its budget fails the nightly performance
suite (`10` §8) and triggers a capacity investigation.

## 2. Budget enforcement model (frozen)

- **Latency budgets** are p95 at the API boundary unless marked p99; measured on
  the sealed snapshot pilot fixture (`10` §8).
- **Throughput budgets** are per-worker.
- **Size budgets** are per-request, per-job, and per-tenant.
- **Time budgets** are wall-clock for jobs.
- **Capacity budgets** are per-tenant quotas enforced through CF4.

Every budget has three thresholds:
- `target` — what to design for and what the suite asserts.
- `alert` — when triggered, an alert fires (no auto-rollback) so the team
  investigates before breached.
- `breach` — when triggered, the subsystem is in violation; the perf suite
  fails; release gate blocks; an ACR is required to release.

## 3. Per-subsystem budgets

### 3.1 Upload
| Metric | Target | Alert | Breach |
|---|---|---|---|
| File size limit (per-tenant default) | 200 MB | 180 MB (warn user) | >200 MB rejects |
| Upload HTTP request handling | p95 ≤ 1 s | p95 ≤ 1.5 s | p95 >2 s |
| Validation throughput (per worker) | ≥5 MB/s | <4 MB/s | <2.5 MB/s |
| Validation job duration (≤200 MB CSV) | ≤10 s | >15 s | >30 s |

### 3.2 Ingestion / Evidata extraction
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Extraction throughput (per worker) | ≥3 000 claims/min | <2 000 | <1 000 |
| Claim write latency (single upsert) | p95 ≤ 25 ms | p95 ≤ 50 ms | p95 > 100 ms |
| Evidence content-hash compute (≤200 MB) | ≤4 s | >6 s | >12 s |

### 3.3 Canonicalization / entity resolution
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Single canonical attribute promotion | p95 ≤ 50 ms | p95 ≤ 100 ms | p95 > 250 ms |
| Entity resolution sweep (10k candidate claims) | ≤30 s | >45 s | >60 s |
| Conflict detection sweep (10k claims) | ≤20 s | >30 s | >60 s |

### 3.4 Graph (read)
(`01` §10 / `06` §7)
| Metric | Target | Alert | Breach |
|---|---|---|---|
| `GET /graph/nodes/{id}` p95 | ≤100 ms | ≤200 ms | >400 ms |
| `GET /graph/nodes/{id}/neighbors` (≤2 hops, ≤10k edges) p95 | ≤300 ms | ≤450 ms | >800 ms |
| `GET /graph/paths` (single source→target, depth ≤4) p95 | ≤500 ms | ≤800 ms | >1.5 s |
| `GET /graph/impact` (≤2 hops, ≤10k reachable) p95 | ≤600 ms | ≤900 ms | >2 s |
| `GET /graph/history` p95 (any depth ≤3) | ≤250 ms | ≤400 ms | >800 ms |
| `GET /graph/diff` between snapshots p95 | ≤2 s | ≤4 s | >10 s |
| Recursive CTE depth upper bound at runtime | 4 hops | — | hard reject (server) |

### 3.5 Graph (write, snapshot build)
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Snapshot build (≤100k nodes + ≤500k edges) | ≤15 s | >25 s | >60 s |
| Snapshot build (≤1M edges) | ≤90 s | >150 s | >300 s |
| Snapshot seal verify (`content_hash`) | ≤3 s | >6 s | >12 s |
| Readiness decision (post-seal) | ≤5 s | >8 s | >15 s |

### 3.6 Intelligence (signals)
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Signal detection over sealed snapshot (≤500k edges) | ≤30 s | >45 s | >120 s |
| ML candidate score lookup (per-snapshot batch) | ≤10 s | >20 s | >60 s |

### 3.7 Scenarios
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Scenario creation (fork sealed base snapshot, apply overrides) | ≤5 s | >8 s | >15 s |
| Scenario branch snapshot recompute (≤10 overrides) | ≤10 s | >15 s | >30 s |
| Scenario compare (1 diff) | ≤3 s | >5 s | >15 s |

### 3.8 Recommendations
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Recommendation generation (single policy, single snapshot) | ≤2 s | >3 s | >6 s |
| Recommendation full sweep (all MVP policies, ≤500k edges) | ≤45 s | >75 s | >180 s |

### 3.9 Decisions
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Decision recording (single accept) | ≤200 ms | ≤500 ms | >1 s |
| Outcome evaluation sweep (1k open decisions) | ≤60 s | >120 s | >300 s |

### 3.10 Audit / event log
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Audit event INSERT (single) | p95 ≤ 5 ms | ≤10 ms | >25 ms |
| Audit chain verify (per workspace, 24h window) | ≤30 s | >60 s | >300 s |
| Hash-chain append batch (≤1k events) | ≤250 ms | ≤500 ms | >1 s |

### 3.11 Frontend / API edge
| Metric | Target | Alert | Breach |
|---|---|---|---|
| API p95 read latency (graph explore) | ≤300 ms | ≤450 ms | >800 ms |
| API p95 write latency (canonical single upsert) | ≤150 ms | ≤250 ms | >500 ms |
| Frontend TTI (workspace shell) on pilot perf fixture | ≤1.8 s | ≤2.5 s | >4 s |
| Frontend graph render (≤10k edges WebGL) | ≤2 s | ≤3 s | >5 s |
| Frontend route transition (App Router) | ≤400 ms | ≤700 ms | >1.2 s |

### 3.12 Workers / jobs
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Worker job dispatch latency (queue→start) | ≤2 s | ≤5 s | >15 s |
| Job concurrency cap (per-tenant) | 16 workers | — | enforced (queues) |
| Long-running job heartbeat | every 15 s | gap >30 s | job killed and retried |

### 3.13 Storage
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Object storage PUT (signed URL, ≤200 MB) | ≤10 s | >15 s | >30 s |
| Snapshot artifact write (≤500 MB) | ≤20 s | >30 s | >60 s |
| Backup daily incremental | ≤30 min | >60 min | >180 min |

### 3.14 Capacity (per workspace)
| Metric | Target | Alert | Breach |
|---|---|---|---|
| Active canonical entities per workspace | ≤1M | >1.5M | >3M (jaeger-traced investigation) |
| Current edges per workspace | ≤5M | >7M | >10M |
| Open conflicts per workspace | ≤5 000 | >10 000 | >50 000 |
| Sealed snapshots stored per workspace | ≤90 days | — | retention cutoff |
| API requests per tenant per minute | ≤10 000 | >15 000 | >30 000 (rate-limited) |

## 4. Enforcement and alerting

- **CI**: k6 perf suite (`10` §8) asserts `target` on the pilot perf fixture.
  Drift >10% vs the last green run is **advisory**; crossing `target` is a
  release block.
- **Pilot runtime**: per-route Prometheus metrics (`22-observability-model.md`)
  are compared against `alert` thresholds; crossing triggers a pageable alert.
  Crossing `breach` blocks the next release candidate and pages both the
  capability owner and the on-call.
- **Per-tenant**: quotas enforced in code CF4; `quota_exceeded` is a 429 with
  the relevant `Retry-After`.
- **Slow-query log**: threshold 200 ms (`06` §15); a query in the log for ≥3
  consecutive days raises a follow-up issue.
- **Snapshot budget enforcement**: if a snapshot build exceeds its time budget,
  the job halts at 70% of `breach` and the partial snapshot is **not** sealed
  (no unsealed artifacts enter the read path).

## 5. Remediation discipline

- A breached budget opens a tracked `perf-investigation` issue assigned to the
  owning capability team; the budget contract cannot be relaxed without an
  ACR.
- If a budget must change, the ACR must include: rationale, expected new
  steady-state, evidence (k6 trends, p50/p95/p99 traces), and an updated
  budget row.
- Sprint-by-sprint, every team owns a "budget report" entry summarizing their
  subsystem's p50/p95 trends and any near-`alert` threshold.

## 6. Frozen decisions summary

- Per-subsystem budgets with `target/alert/breach` and fixed CI vs runtime
  enforcement.
- Perf regressions blocking release is non-negotiable; ACRs required to relax.
- Per-tenant quotas enforced via CF4; 429s with `Retry-After` for offenders.
- Snapshot time budget breach leaves the result unsealed; unsealed
  artifacts never enter the read path.
- Frontend, edge API, audit, and storage budgets are first-class (not just
  the headline graph numbers).
