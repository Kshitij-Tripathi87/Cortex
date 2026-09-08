"""API v1 router — mounts all v1 endpoints under /api/v1."""

from fastapi import APIRouter

from product.workflo_api import router as workflo_router
from app.api.v1 import nexus as nexus_v1

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
api_router.include_router(workflo.router, prefix="", tags=["Workflo"])
# Nexus Decision Intelligence — Operational Decision System (Phase A-F)
api_router.include_router(nexus_v1.router, prefix="/nexus", tags=["Nexus Decision Intelligence"])
# Nexus v0.7 — Production Intelligence & Learning
from app.api.v1 import nexus_v07
api_router.include_router(nexus_v07.router, prefix="/nexus", tags=["Nexus v0.7"])
# Nexus v0.8 — Persistent (PG-backed) production path
from app.api.v1 import nexus_persistent
api_router.include_router(nexus_persistent.router, prefix="", tags=["Nexus v0.8 Persistent"])

