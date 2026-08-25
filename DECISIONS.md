# DECISIONS.md — Cortex MVP Wedge

A running log of decisions that deviate from the MVP execution plan
(`cortex-mvp-execution-plan.md`). Entries are appended chronologically. Each
entry records: date, decision, reason, who approved.

The MVP execution plan is the source of truth. This file exists to capture
in-flight adjustments without losing them in chat history.

| Date | Decision | Reason | Approved by |
|------|----------|--------|-------------|
| 2026-08-01 | Adopted MVP wedge plan v2 (replaced Programs I-Q roadmap) | Strategic pivot: build one validated decision wedge before expanding platform | Engineering |
| 2026-08-01 | Locked 12 ADRs (0001 through 0012) | Architectural decisions frozen before implementation begins | Engineering |
| 2026-08-01 | Workflow engine moved to `app/deferred/` (per ADR-0007) | Excluded from MVP per execution plan §7.2; preserved for Phase 2+ | Engineering |
| 2026-08-01 | Adopted native PostgreSQL UUID for new tables (per ADR-0001) | Mixed types acceptable in MVP; Phase 2 migrates existing tables | Engineering |
| 2026-08-01 | Adopted schema separation: core, operational, inventory, orders, analytics, decision, audit (per ADR-0006) | RBAC + backup isolation + future data warehouse export | Engineering |
| 2026-08-01 | Authentication: bcrypt + JWT, no sessions (per ADR-0004) | Stateless, easy Azure AD replacement later | Engineering |
| 2026-08-01 | Deployment: Docker Compose on single VM (per ADR-0005) | Kubernetes not justified by MVP scale | Engineering |
| 2026-08-01 | Frontend: refactor existing `frontend/`, do not rebuild (per ADR-0012) | Existing Next.js + Tailwind + TS already present | Engineering |
| 2026-08-01 | Frontend types: OpenAPI-generated only (per ADR-011) | Drift-proof; generated types are the contract | Engineering |
| 2026-08-07 | Froze wedge as `v1.0.0-wedge` for pilot phase (ADR-013) | Pilot requires stable API contract, engines, and scenario for reproducible backtest | Founder/CTO |
| 2026-08-07 | Launched pilot phase (validate, prove, sell) per execution board W1–W4 | Wedge shipped; next gate is external operator review + backtest within tolerance | Founder/CTO |
| 2026-08-07 | Separated architecture docs into `active/` (wedge, governing) vs `platform/` (draft, North Star) vs `roadmap/` (phase migration) | Prevent scope creep during pilot; give engineers one source of truth; preserve long-term vision without conflating it with current contract | Founder/CTO |
| 2026-08-09 | Adopted ADR-015: Event-Sourced World State Architecture (Program J constitution) | Lock invariants for World State substrate before Programs K–N (GNN, RL, Multi-Agent, Execution Plane) build on it; prevent substrate drift | Engineering |
| 2026-08-09 | Program J sequenced as 4 milestones — J.1 Event Kernel → J.2 World State → J.3 Digital Twin → J.4 Simulation & Knowledge (per-workstream flags, not one global flag) | Simulator must never touch production state; per-workstream flags give independent rollback if Simulation breaks | Engineering |
| 2026-08-09 | Hash-chain events stored inside `metadata` JSONB column on `world_state_events` (deliberate deviation from first-class columns) | Avoids schema migration on already-deployed tables; Postgres JSONB containment suffices for `verify()`; first-class columns can be promoted later without breaking consumers | Engineering |
| 2026-08-09 | Marked 100k replay-determinism tests `@pytest.mark.stress`; default `pytest` (and PR CI) now skips them; added nightly `stress` CI job (`/.github/workflows/stress.yml`); nightly + release tags + manual | ~2-min stress tests shouldn't tax every PR, but must gate releases; prevents bitrot while keeping PR CI fast | Engineering |
| 2026-08-09 | Adopted ADR-016: World State Engine — canonical projection & version semantics; one `EVENT_PROJECTORS` registry; version = event count; drop `world_versions` table; typed `StateValue` with provenance/freshness split from value; repository is read/snapshot-only (no `update_*`); performance budgets measured, not frozen at `<500 ms` | Eliminates the pre-ADR dual-projection fork (`event_projection.py` + `state_projection.py`); resolves the 42 pre-existing `mypy` arithmetic-typing errors; gives Programs L/M a safe numeric surface and makes `POST /inventory/update`-style violations structurally impossible | Engineering |
| 2026-08-12 | Completed J.2 Slice 2: Typed StateValue with provenance; added `StateValue` ABC, `NumericValue` base, 12 concrete types (InventoryQuantity, SafetyStock, etc.); fixed 17 test failures via `raw_value` projections; added `tests/test_state_values.py` with 56 tests | Enabled strong typing for arithmetic operations (no more `float | int | str + int` mypy errors); preserved determinism via `raw_value`-based state hashes; backward-compatible via `StateVariable.__post_init__` auto-wrap; ready for J.2.3 repository simplification | Engineering |
| 2026-08-18 | Adopted ADR-015: Event-Sourced World State Architecture (Program J constitution); Program J sequenced J.1→J.2→J.3→J.4; J.2.3 Repository hardening frozen (991 PG tests passing) | Lock invariants for World State substrate; single write path, concurrency, idempotency, workspace isolation, deterministic replay verified | Engineering |
| 2026-08-19 | Completed J.3.1 Twin Lifecycle: immutable lineage (parent_world_id, parent_version, snapshot_id, fork_of_twin_id, fork_from_run_id, organization_id, workspace_id, created_at), strict state machine (CREATED→READY→RUNNING→COMPLETED→ARCHIVED/DESTROYED, terminal states reject transitions), production isolation (fingerprint equality on 5 protected tables), fork independence, deterministic runs (seed + rng/engine/simulation versions), event sourcing (twin_events, twin_versions, twin_state, twin_results), 13 API endpoints. 30 tests (27 SQLite + 3 PG), 1004 full regression passes, 0 new ruff/mypy errors. | Establish Digital Twin substrate: isolated, lineage-preserving, reproducible computational branch of World State. Prerequisite for J.3.2 Scenario Runtime, J.3.3 KPI Engine, J.3.4 Counterfactual Comparison, J.4 Simulation Evaluation, and K GNN/RL/Agents. | Engineering |

---

## How to Add an Entry

When making a deviation from the MVP execution plan:

```markdown
| YYYY-MM-DD | Brief description of the decision | Why this was needed | Who signed off |
```

Keep entries brief — the ADR (if any) carries the full reasoning. This file
is a timestamped index.
