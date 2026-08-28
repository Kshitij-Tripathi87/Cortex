# F1 — P50 / P95 / P99 Latency SLO Catalog (Phase 15 Production Gate)

This document freezes the per-route-family latency targets that the
Prometheus histogram `cortex_api_latency_seconds` is queried against in
the SLO alert rules. The targets here are what Grafana / Alertmanager
burn the 28-day error budget on. Changing any of these values is a
release-gating decision, not a one-line config edit.

This catalog is referenced by:

- `app/infrastructure/slo.py` — the runtime evaluator that
  `MetricsMiddleware` calls (or a scheduled job calls) to produce
  `cortex_slo_compliance{route,percentile}` gauges that the alert
  rules key off.
- `tests/test_slo_catalog.py` — the regression suite that pins the
  bucket schema, target values, and route classification.

## 1. Route families (frozen)

We do not set per-endpoint SLOs. The route set changes too often
(deprecation, versioning, refactors) for per-endpoint targets to
survive. Instead, every route is mapped to a `route_family` (the
first non-empty path segment after the API version), and the SLO is
applied to the family. This mirrors how Grafana dashboards roll up
the histogram.

| route_family     | example routes                                        |
|------------------|--------------------------------------------------------|
| `workspace`      | `/api/v1/workspace/state`, `/api/v1/workspace/stream` |
| `ingest`         | `/api/v1/ingest/raw`, `/api/v1/ingest/file`           |
| `graph`          | `/api/v1/graph/subgraph`, `/api/v1/graph/critical`    |
| `decisions`      | `/api/v1/decisions`, `/api/v1/decisions/evidence`     |
| `realtime`       | `/api/v1/realtime/*` (WebSocket + SSE)                |
| `agents`         | `/api/v1/agents/*`                                     |
| `workflow`       | `/api/v1/workflow/*`                                   |
| `twin`           | `/api/v1/twin/*` (Digital Twin runtime — G1)          |
| `admin`          | `/api/v1/admin/*` (audit, RLS inspection)              |
| `health`         | `/healthz`, `/readyz`, `/metrics`                      |

A request to an unknown route is bucketed under `_unmatched` and is
NOT subject to SLO burn; it is, however, recorded in
`cortex_api_requests_total` so we can see that the routing layer
missed something.

## 2. Latency targets (frozen — P50 / P95 / P99)

The unit is seconds. P99 is the binding target; P50 and P95 are
informational and used for capacity planning, not for alert rules.

| route_family     | P50 (s) | P95 (s) | **P99 (s) — alert target** | error budget (28d) |
|------------------|---------|---------|----------------------------|--------------------|
| `workspace`      | 0.05    | 0.20    | **0.50**                   | 99% within P99     |
| `ingest`         | 0.20    | 0.80    | **2.00**                   | 99% within P99     |
| `graph`          | 0.10    | 0.40    | **1.00**                   | 99% within P99     |
| `decisions`      | 0.15    | 0.60    | **1.50**                   | 99% within P99     |
| `realtime`       | 0.01    | 0.05    | **0.20**                   | 99% within P99     |
| `agents`         | 0.30    | 1.50    | **3.00**                   | 99% within P99     |
| `workflow`       | 0.20    | 1.00    | **2.50**                   | 99% within P99     |
| `twin`           | 0.10    | 0.50    | **1.50**                   | 99% within P99     |
| `admin`          | 0.20    | 1.00    | **2.00**                   | 99% within P99     |
| `health`         | 0.005   | 0.02    | **0.05**                   | 99.9% within P99   |

Rationale for the per-family split:

- `realtime` is hot-path streaming (SSE, WebSocket) — must be
  sub-100ms at P99 so the live canvas doesn't stutter. The
  histogram bucketing ([0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0,
  2.5, 5.0, 10.0]) already covers this range, but the
  alert target is the binding contract.
- `ingest` carries multi-MB CSV uploads; P99 at 2s reflects the
  large-body tier.
- `decisions` and `twin` are interactive ("what if I pull the
  lever?") paths; 1–1.5s at P99 is the budget for the full
  deliberation + counterfactual cycle.
- `agents` is the slow-path orchestration that triggers
  multi-agent deliberation; 3s P99 is acceptable because the
  client UI shows a "deliberating…" state.

## 3. Bucket schema (frozen)

`cortex_api_latency_seconds` exposes buckets at:

```
0.01, 0.025, 0.05, 0.10, 0.25, 0.50, 1.0, 2.5, 5.0, 10.0
```

This is the schema the SLO evaluator and the alert rules assume.
Changing the buckets invalidates historical SLO data — it is a
schema migration, not a config edit. The regression test
`tests/test_slo_catalog.py::TestHistogramBucketSchema` pins the
exact list.

`histogram_quantile(0.99, sum by (le, route_family) (rate(cortex_api_latency_seconds_bucket[5m])))`
is the canonical query for the P99 SLO signal in Grafana.

## 4. SLO evaluation — `app/infrastructure/slo.py`

The evaluator exposes:

- `ROUTE_FAMILIES` — the frozen family → predicate map.
- `LATENCY_TARGETS` — the frozen family → P50/P95/P99 dict.
- `classify_route(path: str) -> str` — given a request path,
  returns the `route_family` (or `_unmatched`).
- `evaluate_observation(family, observed_seconds) -> ComplianceResult`
  — given a single observation, returns whether the P99 target
  was met. Used in unit tests; production alert rules compute
  percentiles from the histogram directly.
- `compliance_from_buckets(family, bucket_counts, total_count) -> float`
  — given a `cortex_api_latency_seconds_bucket` series snapshot
  (cumulative counts per `le` boundary), returns the fraction of
  observations that were within the P99 target. Used by a
  scheduled job to publish `cortex_slo_compliance{route,percentile}`.

## 5. Out of scope for F1

- Per-endpoint SLOs — the family rollup is the contract.
- Traces, logs, audit — covered by O3, O4, O5 in
  `docs/22-observability-model.md`.
- The SLO alert rules themselves (A-D1 etc.) — added in F3
  (end-to-end observability trace).
