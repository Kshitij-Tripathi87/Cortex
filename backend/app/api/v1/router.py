"""API v1 router — mounts all v1 endpoints under /api/v1.

Nexus routing (v0.8.2 closeout — routing flip + dual-path removal):

  * /nexus/*            → CANONICAL production path: the persistent
                          (PostgreSQL-backed) router. Every authoritative
                          operation terminates at AsyncSession → PostgreSQL →
                          Authoritative* services. There is NO fallback to the
                          v0.7 in-memory singletons.

  * /v07-legacy/nexus/* → the v0.7 in-memory routers (process-local state),
                          mounted ONLY when CORTEX_NEXUS_V07_LEGACY_ROUTES is
                          explicitly enabled (unit tests, migration tooling,
                          historical v0.7 demonstrations). Never mounted in
                          production by default.
"""

from fastapi import APIRouter
from product.workflo_api import router as workflo_router

from app.api.v1 import (
    agent_runtime,
    agents_router,
    audit,
    auth,
    briefs,
    execution,
    gnn,
    governance,
    graph,
    ingestion,
    intelligence_gateway,
    knowledge,
    multi_agent,
    nexus_persistent,
    nexus_v07,
    readiness,
    realtime,
    rl,
    simulation,
    sources,
    spine,
    twin,
    validation,
    workspace,
    world,
)
from app.api.v1 import nexus as nexus_v1
from app.config import get_settings

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(readiness.router, prefix="/readiness", tags=["readiness"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])
api_router.include_router(ingestion.router, prefix="/mvp", tags=["mvp"])
api_router.include_router(briefs.router, prefix="/mvp", tags=["mvp"])
# Program J — World State & Digital Twin APIs
api_router.include_router(world.router, prefix="", tags=["world"])
api_router.include_router(twin.router, prefix="", tags=["twin"])
api_router.include_router(simulation.router, prefix="", tags=["simulation"])
api_router.include_router(knowledge.router, prefix="", tags=["knowledge"])
# Program K — Graph Intelligence & GNN APIs
api_router.include_router(gnn.router, prefix="/gnn", tags=["gnn"])
# Program L — Reinforcement Learning APIs
api_router.include_router(rl.router, prefix="/rl", tags=["rl"])
# Program M — Multi-Agent Coordination APIs
api_router.include_router(multi_agent.router, prefix="/multi-agent", tags=["multi-agent"])
# Program N — Supervised Execution APIs
api_router.include_router(execution.router, prefix="/execution", tags=["execution"])
# Program O — Closed-Loop Continuous Learning & Governance APIs
api_router.include_router(governance.router, prefix="/governance", tags=["governance"])
# Program P — Enterprise Production Validation APIs
api_router.include_router(validation.router, prefix="/validation", tags=["validation"])
# Cortex Nexus — Production Runtime Extensions
api_router.include_router(agent_runtime.router, prefix="", tags=["Agent Runtime"])
api_router.include_router(intelligence_gateway.router, prefix="", tags=["Intelligence Gateway"])
api_router.include_router(realtime.router, prefix="", tags=["Real-Time Streaming"])
api_router.include_router(agents_router.router, prefix="", tags=["Agent Operations Center"])
# Program S — Live Nexus Data Intelligence Workspace
api_router.include_router(workspace.router, prefix="", tags=["Live Data Intelligence Workspace"])
# Nexus Spine — Real Data Vertical Slice
api_router.include_router(spine.router, prefix="/spine", tags=["Nexus Spine"])
# Workflo — Sandboxed QA & Runtime Execution Control Plane
api_router.include_router(workflo_router, prefix="", tags=["Workflo"])

# ─────────────────────────────────────────────────────────────────────
# Nexus Decision Intelligence — v0.8.2 routing flip
#
# The persistent (PostgreSQL-backed) router is the CANONICAL and ONLY
# production authority for /api/v1/nexus/*. All decision, memory, forecast,
# observation, calibration, and vanessa/ask operations terminate at
# AsyncSession → PostgreSQL → Authoritative* services.
# ─────────────────────────────────────────────────────────────────────
api_router.include_router(
    nexus_persistent.router,
    prefix="",
    tags=["Nexus Decision Intelligence"],
)

# ─────────────────────────────────────────────────────────────────────
# Nexus v0.7 legacy — in-memory singletons, demoted 2026-09 (v0.8.2).
#
# These routers keep process-local state (DecisionLifecycleManager /
# DecisionMemory / TruthLoop singletons) and are NOT authoritative.
# They are mounted under an explicit /v07-legacy/* namespace and only
# when CORTEX_NEXUS_V07_LEGACY_ROUTES is enabled, so that normal
# production code cannot reach them accidentally. Reserved for unit
# tests, explicit migration tooling, and historical v0.7 demonstrations.
# TODO(v0.9): remove these mounts and the routers' production claim.
# ─────────────────────────────────────────────────────────────────────
if get_settings().nexus_v07_legacy_routes:
    api_router.include_router(
        nexus_v1.router,
        prefix="/v07-legacy/nexus",
        tags=["nexus-v07-legacy"],
    )
    api_router.include_router(
        nexus_v07.router,
        prefix="/v07-legacy/nexus",
        tags=["nexus-v07-legacy"],
    )
