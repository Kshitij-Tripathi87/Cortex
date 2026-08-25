# Cortex Launch Hardening Checklist

**Release Candidate:** RC-2 (0.3.0)  
**Launch Target:** 0.3.0 (Production)  
**Status:** In Progress

---

## Step 1: Freeze Release Candidate ✅

- [x] Tag current state as launch candidate
- [x] Freeze API contracts for graph, propagation, scenarios, recommendations, decisions
- [x] Freeze decision taxonomy (7 types)
- [x] Freeze scenario taxonomy (9 types)
- [x] Freeze recommendation taxonomy (13 types)
- [x] Record backend version (0.3.0)
- [x] Record frontend version (0.2.0)
- [x] Record migration version (004)
- [x] Record test count (348 tests)

**Artifacts:**
- `RELEASE_RC_2.md` — Release candidate documentation
- `LAUNCH_HARDENING.md` — This checklist

**Exit Criteria:** ✅ COMPLETE
- No new feature work merged unless launch-required
- All changes are launch-hardening only

---

## Step 2: Close Integration Gaps

**Owner:** Backend Team  
**Priority:** Critical

### 2.1 S3 Raw-Byte Ingestion
- [ ] Audit current compiler ingestion path
- [ ] Implement `S3RawByteReader` for production mode
- [ ] Add fallback to profiler path for legacy uploads
- [ ] Test with large files (>100MB)
- [ ] Verify content-addressed storage with raw bytes

### 2.2 Redis Cache Invalidation
- [ ] Audit current cache usage (NoOpCache in dev)
- [ ] Implement cache invalidation on graph compile
- [ ] Implement cache invalidation on feature computation
- [ ] Add TTL policies for derived artifacts
- [ ] Test cache hit rates under load

### 2.3 DB-Backed Monotonic Versioning
- [ ] Audit hardcoded `snapshot_version = 1` paths
- [ ] Implement `get_next_version(workspace_id)` from DB
- [ ] Update graph snapshot sealing to use DB version
- [ ] Update feature snapshot versioning to use DB
- [ ] Update scenario snapshot versioning to use DB
- [ ] Update recommendation snapshot versioning to use DB
- [ ] Add migration for version sequences if needed
- [ ] Test replay with monotonic versions

### 2.4 Recommendation API Wiring
- [ ] Audit `/recommendations/generate` endpoint
- [ ] Verify real engine output (no placeholders)
- [ ] Verify all ranked recommendations have:
  - [ ] Candidate with full lineage
  - [ ] Scores (all 8 dimensions)
  - [ ] Trade-offs (at least 1)
  - [ ] Explanation (all 8 fields)
  - [ ] Reversibility level
  - [ ] Policy classification
- [ ] Test with empty scenario (graceful handling)
- [ ] Test with unknown scenario type (error handling)

**Exit Criteria:**
- [ ] No production path depends on sample reconstruction when raw bytes available
- [ ] No core reasoning layer uses hardcoded version
- [ ] No placeholder recommendation route remains

---

## Step 3: Recommendation Path Production-Safe

**Owner:** Backend Team  
**Priority:** Critical

### 3.1 Closed-Taxonomy Verification
- [ ] Verify candidate generation only produces known recommendation types
- [ ] Verify `RecommendationType.CUSTOM` requires explicit policy approval flag
- [ ] Add test: unknown scenario type → no unknown recommendations

### 3.2 Determinism Verification
- [ ] Add replay test: same scenario + propagation → same recommendations
- [ ] Verify scoring formula is stable (no floating-point drift)
- [ ] Verify deduplication is deterministic (stable ordering)
- [ ] Verify tie-breaking uses stable criteria (candidate_id hash)

### 3.3 Explanation Quality
- [ ] Verify all 8 explanation fields are populated
- [ ] Verify `what` field is action-oriented
- [ ] Verify `why` field references scenario impact
- [ ] Verify `evidence_summary` lists key claims
- [ ] Verify `assumptions` list is non-empty
- [ ] Verify `uncertainties` list is non-empty
- [ ] Verify `review_guidance` is actionable

### 3.4 Authorization
- [ ] Verify `/recommendations/generate` requires workspace access
- [ ] Verify recommendations are filtered by workspace_id
- [ ] Verify cross-workspace access is blocked
- [ ] Add test: unauthorized user → 403

### 3.5 Frontend Trade-Off Rendering
- [ ] Verify frontend displays all trade-off dimensions
- [ ] Verify `gain` and `loss` are human-readable
- [ ] Verify `magnitude` is color-coded (low/medium/high)
- [ ] Verify quantified values show units ($, hours, %)

**Exit Criteria:**
- [ ] Given same scenario and propagation input, same ranked recommendations produced
- [ ] Unsupported actions never appear
- [ ] No route bypasses recommendation service

---

## Step 4: Harden Auth, Rate Limits, Circuit Breakers

**Owner:** Platform Team  
**Priority:** Critical

### 4.1 Authorization Audit
- [ ] Audit `/graph/traverse` — requires workspace access
- [ ] Audit `/graph/propagate` — requires workspace access
- [ ] Audit `/graph/scenarios` — requires workspace access
- [ ] Audit `/graph/recommendations/generate` — requires workspace access
- [ ] Audit `/graph/decisions` — requires workspace access
- [ ] Verify `require_workspace_access()` is called on all expensive endpoints
- [ ] Add integration test: cross-workspace access → 403

### 4.2 Rate Limiting
- [ ] Identify expensive endpoints:
  - [ ] `/graph/propagate` (graph traversal + impact analysis)
  - [ ] `/graph/scenarios` (what-if simulation)
  - [ ] `/graph/recommendations/generate` (candidate generation + scoring)
  - [ ] `/graph/traverse` (large graph traversal)
- [ ] Implement rate limits per workspace:
  - [ ] Propagation: 10 req/min
  - [ ] Scenarios: 10 req/min
  - [ ] Recommendations: 10 req/min
  - [ ] Traverse: 30 req/min
- [ ] Add rate limit headers:
  - [ ] `X-RateLimit-Limit`
  - [ ] `X-RateLimit-Remaining`
  - [ ] `X-RateLimit-Reset`
- [ ] Return 429 on limit exceeded
- [ ] Add test: rate limit exceeded → 429

### 4.3 Circuit Breakers
- [ ] Implement circuit breaker for:
  - [ ] Propagation engine (timeout: 30s, threshold: 5 failures)
  - [ ] Scenario engine (timeout: 30s, threshold: 5 failures)
  - [ ] Recommendation engine (timeout: 30s, threshold: 5 failures)
- [ ] Add circuit breaker states:
  - [ ] CLOSED (normal operation)
  - [ ] OPEN (failing fast)
  - [ ] HALF-OPEN (testing recovery)
- [ ] Return 503 with `Retry-After` header when circuit is OPEN
- [ ] Add metrics: `circuit_breaker.{name}.state`
- [ ] Add test: circuit opens after 5 failures

### 4.4 Request ID Propagation
- [ ] Verify server-side UUIDv7 generation in `app/main.py`
- [ ] Verify request ID is added to all log lines
- [ ] Verify request ID is propagated to:
  - [ ] OpenTelemetry traces
  - [ ] Prometheus metrics
  - [ ] Audit events
- [ ] Verify correlation ID links related requests
- [ ] Add test: request ID present in logs

### 4.5 Uniform Denial Behavior
- [ ] Verify 401 for missing authentication
- [ ] Verify 403 for workspace access denied
- [ ] Verify 429 for rate limit exceeded
- [ ] Verify 503 for circuit breaker OPEN
- [ ] Verify all denials are logged with request ID
- [ ] Verify all denials include `WWW-Authenticate` or `Retry-After` headers

**Exit Criteria:**
- [ ] Unauthorized or cross-workspace access blocked everywhere
- [ ] Expensive endpoints fail closed, not open
- [ ] Rate limits enforced per workspace
- [ ] Circuit breakers protect backend from cascade failures

---

## Step 5: Complete Frontend Operational Workspace

**Owner:** Frontend Team  
**Priority:** Critical

### 5.1 Page Completion Audit

#### Home Dashboard (`/`)
- [ ] Displays workspace summary cards
- [ ] Links to all 7 operational pages
- [ ] Shows recent activity
- [ ] Shows readiness status

#### Upload (`/upload`)
- [ ] File upload with validation feedback
- [ ] Source-system selection dropdown
- [ ] Upload progress indicator
- [ ] Error handling for failed uploads
- [ ] Success state with batch ID

#### Evidence Explorer (`/evidence`)
- [ ] Filter by state (raw/profiling/profiled/compiled)
- [ ] Filter by entity type
- [ ] Filter by field name
- [ ] Filter by confidence
- [ ] Sort by created_at, entity_type, confidence
- [ ] Pagination (50/page)
- [ ] Claim drawer with full claim details
- [ ] Empty state (no evidence uploaded)
- [ ] Loading state
- [ ] Error state with retry

#### Conflict Center (`/conflicts`)
- [ ] Filter by severity (info/warning/critical/blocking)
- [ ] Filter by status (open/in_review/resolved)
- [ ] Filter by blocking flag
- [ ] Claims comparison modal
- [ ] Resolution form with rationale
- [ ] Conflict count badge
- [ ] Empty state (no conflicts)
- [ ] Loading state
- [ ] Error state with retry

#### Readiness Center (`/readiness`)
- [ ] Compute readiness button
- [ ] Readiness state display (pending/computing/ready/failed)
- [ ] Assumptions list
- [ ] Audit history timeline
- [ ] Readiness score visualization
- [ ] Empty state (no batch selected)
- [ ] Loading state
- [ ] Error state with retry

#### Audit Timeline (`/audit`)
- [ ] Filter by category (source/compiler/quality/domain/integration)
- [ ] Filter by type
- [ ] Filter by subject
- [ ] Date range picker
- [ ] Payload viewer (collapsible JSON)
- [ ] Pagination (100/page)
- [ ] Empty state (no audit events)
- [ ] Loading state
- [ ] Error state with retry

#### Graph Explorer (NEW — `/graph`)
- [ ] Node list with entity type filter
- [ ] Edge list with relationship type filter
- [ ] Graph visualization (force-directed or table view)
- [ ] Snapshot version display
- [ ] Integrity status badge
- [ ] Node detail drawer with attributes
- [ ] Edge detail drawer with provenance
- [ ] Empty state (graph not compiled)
- [ ] Loading state
- [ ] Error state with retry

#### Signals (NEW — `/signals`)
- [ ] Signal list with severity color-coding
- [ ] Filter by category (concentration/bottleneck/isolation/criticality)
- [ ] Filter by severity (info/warning/critical)
- [ ] Signal detail with affected nodes
- [ ] Feature evidence display
- [ ] Explanation text
- [ ] Empty state (no signals detected)
- [ ] Loading state
- [ ] Error state with retry

#### Propagation (NEW — `/propagation`)
- [ ] Select signal to propagate
- [ ] Propagation tree visualization
- [ ] Affected entities list
- [ ] Impact summary (by severity, by type, by entity type)
- [ ] Affected facilities/inventory/orders/customers
- [ ] Execution time display
- [ ] Empty state (no signal selected)
- [ ] Loading state (propagation running)
- [ ] Error state with retry

#### Scenarios (NEW — `/scenarios`)
- [ ] Scenario definition form
- [ ] Scenario type selector
- [ ] Parameter inputs (dynamic by type)
- [ ] Run scenario button
- [ ] Assumptions list
- [ ] Impact list with severity
- [ ] Summary metrics
- [ ] Comparison view (multiple scenarios)
- [ ] Empty state (no scenarios)
- [ ] Loading state (scenario running)
- [ ] Error state with retry

#### Recommendations (NEW — `/recommendations`)
- [ ] Select scenario to generate recommendations
- [ ] Ranked recommendation list
- [ ] Recommendation detail modal:
  - [ ] Candidate info
  - [ ] Scores (radar chart or table)
  - [ ] Trade-offs list
  - [ ] Explanation
  - [ ] Reversibility level
  - [ ] Policy classification
- [ ] Generate button
- [ ] Empty state (no scenario selected)
- [ ] Loading state (generating)
- [ ] Error state with retry

#### Decisions (NEW — `/decisions`)
- [ ] Decision list with status badges
- [ ] Filter by type, status, reviewer
- [ ] Decision detail:
  - [ ] Original decision info
  - [ ] Linked scenario
  - [ ] Linked recommendation
  - [ ] Evidence lineage
  - [ ] Outcomes list
  - [ ] Lessons learned list
  - [ ] Export button
- [ ] Create decision form (from recommendation)
- [ ] Append outcome form
- [ ] Append lesson form
- [ ] Empty state (no decisions)
- [ ] Loading state
- [ ] Error state with retry

### 5.2 API Contract Integration
- [ ] Run `npm run generate-types` to generate OpenAPI types
- [ ] Verify all API calls use generated types
- [ ] Verify no `any` types in API response handling
- [ ] Verify error responses are typed

### 5.3 Workspace Context
- [ ] Verify workspace selector is present on all pages
- [ ] Verify workspace_id is included in all API calls
- [ ] Verify workspace switch clears page state
- [ ] Verify cross-workspace access shows 403

### 5.4 Provenance Visibility
- [ ] Verify snapshot version is shown on:
  - [ ] Graph Explorer
  - [ ] Signals page
  - [ ] Propagation page
  - [ ] Scenarios page
  - [ ] Recommendations page
  - [ ] Decisions page
- [ ] Verify evidence claim IDs are shown on:
  - [ ] Graph node detail
  - [ ] Decision detail

**Exit Criteria:**
- [ ] User can move upload → evidence → graph → signal → propagation → scenario → recommendation → decision without confusion
- [ ] No page is a mock shell
- [ ] All pages have loading, empty, error, and retry states

---

## Step 6: Run Golden Regression Suite

**Owner:** QA Team  
**Priority:** Critical

### 6.1 End-to-End Golden Dataset
- [ ] Run 7-file golden dataset through full pipeline
- [ ] Verify validation passes for every file
- [ ] Verify profiling matches golden expectations
- [ ] Verify schema mapping is correct
- [ ] Verify quality scores are in [0.0, 1.0]
- [ ] Verify anomaly detection fires correctly
- [ ] Verify graph compile produces same node/edge counts
- [ ] Verify signal detection produces same signals
- [ ] Verify propagation produces same affected entities
- [ ] Verify scenario execution produces same impacts
- [ ] Verify recommendation generation produces same rankings
- [ ] Verify decision creation works

### 6.2 Replay Stability
- [ ] Run golden dataset twice
- [ ] Verify identical outputs (except timestamps/IDs)
- [ ] Verify hash chains match
- [ ] Verify snapshot hashes are deterministic

### 6.3 RC-1 + Programs A-H Regression
- [ ] Run `test_golden_dataset.py` (84 cases)
- [ ] Run `test_modules.py` (RC-1 invariants)
- [ ] Run `test_backend.py` (pre-existing tests)
- [ ] Run `test_graph_*.py` (Programs A-D)
- [ ] Run `test_propagation.py` (Program E)
- [ ] Run `test_scenarios.py` (Program F)
- [ ] Run `test_recommendations.py` (Program G)
- [ ] Run `test_decisions.py` (Program H)
- [ ] Expected: 348+ tests passing

### 6.4 Cross-Layer Regression
- [ ] Verify S3 changes don't break profiling
- [ ] Verify cache changes don't break feature computation
- [ ] Verify versioning changes don't break snapshot sealing
- [ ] Verify auth changes don't break legitimate access
- [ ] Verify rate limits don't break normal usage

### 6.5 Failure Case Verification
- [ ] Verify invalid upload → validation error
- [ ] Verify duplicate tax_id → integrity warning
- [ ] Verify missing required parameter → scenario error
- [ ] Verify unknown scenario type → graceful handling
- [ ] Verify cross-workspace access → 403
- [ ] Verify rate limit exceeded → 429

**Exit Criteria:**
- [ ] All launch-critical tests pass
- [ ] No reasoning-layer output changes unexpectedly
- [ ] Golden dataset produces identical results

---

## Step 7: Add Production Observability Checks

**Owner:** Platform Team  
**Priority:** Medium

### 7.1 Log Verification
- [ ] Verify all logs include:
  - [ ] Request ID
  - [ ] Workspace ID (if applicable)
  - [ ] Correlation ID (if applicable)
  - [ ] Timestamp (ISO 8601)
  - [ ] Log level
  - [ ] Message
- [ ] Verify structured logging (JSON format)
- [ ] Verify sensitive fields are redacted

### 7.2 Metrics Verification
- [ ] Verify Prometheus metrics exist for:
  - [ ] `upload_duration_seconds` (histogram)
  - [ ] `graph_compile_duration_seconds` (histogram)
  - [ ] `traversal_duration_seconds` (histogram)
  - [ ] `signal_detection_duration_seconds` (histogram)
  - [ ] `propagation_duration_seconds` (histogram)
  - [ ] `scenario_execution_duration_seconds` (histogram)
  - [ ] `recommendation_generation_duration_seconds` (histogram)
  - [ ] `decision_creation_duration_seconds` (histogram)
  - [ ] `cache_hit_total` (counter)
  - [ ] `cache_miss_total` (counter)
  - [ ] `rate_limit_exceeded_total` (counter)
  - [ ] `circuit_breaker_state` (gauge)
  - [ ] `http_requests_total` (counter, by endpoint, status)
  - [ ] `http_request_duration_seconds` (histogram, by endpoint)
- [ ] Verify metrics are exposed at `/metrics`
- [ ] Verify Grafana dashboard shows all metrics

### 7.3 Health/Readiness Endpoints
- [ ] Verify `/healthz` returns 200 when healthy
- [ ] Verify `/healthz` returns 503 when unhealthy
- [ ] Verify `/readyz` returns 200 when ready
- [ ] Verify `/readyz` returns 503 when not ready (e.g., DB down)
- [ ] Verify health checks include:
  - [ ] Database connectivity
  - [ ] Redis connectivity (if configured)
  - [ ] S3 connectivity (if configured)

### 7.4 Trace Propagation
- [ ] Verify OpenTelemetry traces include:
  - [ ] Trace ID
  - [ ] Span ID
  - [ ] Parent Span ID
  - [ ] Service name
  - [ ] Operation name
  - [ ] Duration
  - [ ] Status (OK/Error)
- [ ] Verify traces propagate through:
  - [ ] Upload → Profile → Compile
  - [ ] Scenario → Propagation → Recommendation
  - [ ] Recommendation → Decision

**Exit Criteria:**
- [ ] A failed request can be traced end to end
- [ ] A slow path can be identified without guessing
- [ ] Grafana dashboard shows real-time metrics

---

## Step 8: Deployment-from-Scratch Verification

**Owner:** Platform Team  
**Priority:** Medium

### 8.1 Clean Build
- [ ] Clone repository to fresh directory
- [ ] Run `make docker-up`
- [ ] Verify all containers start:
  - [ ] PostgreSQL
  - [ ] Redis
  - [ ] MinIO
  - [ ] Backend
  - [ ] Frontend
  - [ ] Prometheus
  - [ ] Grafana
- [ ] Verify no manual intervention required

### 8.2 Migrations from Scratch
- [ ] Run `make migrate`
- [ ] Verify all 4 migrations apply:
  - [ ] 001_initial
  - [ ] 002_row_level_security
  - [ ] 003_operational_graph
  - [ ] 004_decision_memory
- [ ] Verify no migration errors
- [ ] Verify schema matches expected state

### 8.3 Test Suite from Scratch
- [ ] Run `make test`
- [ ] Verify 348+ tests pass
- [ ] Verify no test failures
- [ ] Verify test coverage report generated

### 8.4 Golden Flow from Scratch
- [ ] Upload test file via `/api/v1/sources/upload`
- [ ] Verify profiling completes
- [ ] Verify compile completes
- [ ] Verify graph is queryable
- [ ] Verify signals are detected
- [ ] Verify propagation runs
- [ ] Verify scenario executes
- [ ] Verify recommendations generate
- [ ] Verify decision can be created

### 8.5 Rollback Verification
- [ ] Deploy RC-1 (0.2.0)
- [ ] Verify downgrade migration works
- [ ] Verify RC-1 functions correctly
- [ ] Re-upgrade to RC-2 (0.3.0)
- [ ] Verify upgrade migration works
- [ ] Verify RC-2 functions correctly

### 8.6 CI-Equivalent Build
- [ ] Verify GitHub Actions build passes:
  - [ ] `lint.yml`
  - [ ] `test.yml`
  - [ ] `typecheck.yml`
  - [ ] `security.yml`
  - [ ] `build.yml`
- [ ] Verify Docker images build successfully
- [ ] Verify `docker compose config` validates

**Exit Criteria:**
- [ ] Platform starts from zero without manual fixes
- [ ] Rollback is known and repeatable
- [ ] CI build passes in clean environment

---

## Step 9: Pilot Acceptance

**Owner:** All Teams  
**Priority:** Medium

### 9.1 Pilot Scenarios
- [ ] Create pilot scenario 1: Supplier failure with 2-week outage
- [ ] Create pilot scenario 2: Warehouse outage affecting 3 regions
- [ ] Create pilot scenario 3: Route closure requiring rerouting
- [ ] Run each scenario through full pipeline

### 9.2 User Workflow Verification

#### Operations User Persona
- [ ] Can upload file without confusion
- [ ] Can inspect evidence claims
- [ ] Can review conflicts and resolve
- [ ] Can inspect graph context
- [ ] Can understand detected signals
- [ ] Can evaluate propagation impact
- [ ] Can compare multiple scenarios
- [ ] Can review recommendations with trade-offs
- [ ] Can record decision with rationale
- [ ] Can append outcome after implementation
- [ ] Can record lesson learned

#### Analyst User Persona
- [ ] Can query decisions by workspace/scenario/reviewer
- [ ] Can export decisions for training
- [ ] Can inspect audit timeline
- [ ] Can trace decision back to evidence
- [ ] Can compare scenario outcomes

### 9.3 Explainability Verification
- [ ] Verify every recommendation has clear explanation
- [ ] Verify every decision has clear rationale
- [ ] Verify every signal has clear feature evidence
- [ ] Verify every propagation has clear impact reasoning
- [ ] Verify every scenario has clear assumptions

### 9.4 Auditability Verification
- [ ] Verify every action is logged in audit trail
- [ ] Verify audit events are immutable
- [ ] Verify audit events can be queried
- [ ] Verify audit payload is inspectable

### 9.5 Pilot Feedback Integration
- [ ] Collect pilot user feedback
- [ ] Prioritize critical issues
- [ ] Fix critical issues before launch
- [ ] Document known limitations

**Exit Criteria:**
- [ ] System is demonstrably usable by operations user
- [ ] Cortex behaves like a product, not a lab project
- [ ] All critical pilot feedback addressed

---

## Launch Gate Summary

**Cortex is launch-ready ONLY when ALL boxes are checked:**

- [ ] Programs A–H functioning together
- [ ] No placeholder reasoning routes remain
- [ ] Production S3 reading is active
- [ ] Snapshot versioning is DB-backed (monotonic)
- [ ] Redis caching is wired for safe derived data
- [ ] AuthZ/rate limits/circuit breakers are active
- [ ] Frontend is usable end to end (all 9 pages)
- [ ] Golden regression passes (348+ tests)
- [ ] Clean build/deploy/rollback works
- [ ] Pilot acceptance complete

---

## Sign-Off

| Role | Name | Date | Status | Notes |
|------|------|------|--------|-------|
| Backend Lead | | | | |
| Frontend Lead | | | | |
| Platform Lead | | | | |
| QA Lead | | | | |
| Security Review | | | | |
| Product Owner | | | | |

**Launch Approval Date:** _______________  
**Launch Version:** 0.3.0  
**Launch Build ID:** _______________