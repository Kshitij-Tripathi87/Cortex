"""Graph API v1 — compile, inspect nodes/edges, list snapshots, integrity, recommendations."""

from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.graph.compiler import compile_evidence_to_graph
from app.modules.graph.decision_models import (
    DecisionRequest,
    DecisionStatus,
    DecisionType,
    LessonCategory,
    OutcomeStatus,
)
from app.modules.graph.decision_service import DecisionService
from app.modules.graph.integrity import get_integrity_report
from app.modules.graph.models import GraphEdge, GraphNode
from app.modules.graph.scenario_models import (
    ScenarioDefinition,
    ScenarioParameter,
    ScenarioType,
)
from app.modules.graph.snapshots import get_snapshot, list_snapshots, verify_snapshot_chain

router = APIRouter()


class NodeResponse(BaseModel):
    node_id: str
    entity_type: str
    entity_id: str
    attributes: dict[str, Any]
    first_seen_version: int
    last_modified_version: int


class EdgeResponse(BaseModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    relationship_type: str
    attributes: dict[str, Any]
    first_seen_version: int
    last_modified_version: int


class SnapshotResponse(BaseModel):
    snapshot_id: str
    version: int
    snapshot_hash: str
    prev_snapshot_hash: str | None
    node_count: int
    edge_count: int
    source_batch_id: str | None
    sealed_at: str


class CompilationResponse(BaseModel):
    snapshot_id: str
    version: int
    snapshot_hash: str
    node_count: int
    edge_count: int
    write_event_count: int
    provenance_link_count: int
    integrity_passed: bool


class OperationalStateUpsertRequest(BaseModel):
    """Validated operational-state payload from an approved upstream connector."""

    workspace_id: str
    state_type: str
    state: dict[str, Any]


class OperationalStateUpsertResponse(BaseModel):
    workspace_id: str
    node_id: str
    state_type: str


class IntegrityResponse(BaseModel):
    no_orphan_edges: bool
    all_nodes_have_provenance: bool
    all_edges_have_provenance: bool
    chain_verified: bool


@router.put("/operational-state", response_model=OperationalStateUpsertResponse)
async def upsert_operational_state(
    body: OperationalStateUpsertRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> OperationalStateUpsertResponse:
    """Persist operational state from a trusted connector and invalidate context."""
    require_workspace_access(body.workspace_id, auth)
    from app.modules.graph.context_engine import SqlOperationalStateRepository, create_context_cache
    from app.modules.graph.context_models import (
        BusinessOperationalState,
        InventoryOperationalState,
        LogisticsOperationalState,
        OrderOperationalState,
        ProductionOperationalState,
    )

    state_classes = {
        "inventory": InventoryOperationalState,
        "order": OrderOperationalState,
        "logistics": LogisticsOperationalState,
        "production": ProductionOperationalState,
        "business": BusinessOperationalState,
    }
    state_class = state_classes.get(body.state_type.lower())
    if state_class is None:
        raise HTTPException(status_code=422, detail="Unsupported operational state type")
    try:
        state = TypeAdapter(state_class).validate_python(body.state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await SqlOperationalStateRepository(db, create_context_cache()).upsert_state(
        body.workspace_id, state
    )
    await db.commit()
    return OperationalStateUpsertResponse(
        workspace_id=body.workspace_id, node_id=state.node_id, state_type=body.state_type.lower()
    )


@router.post("/batches/{batch_id}/compile", response_model=CompilationResponse)
async def compile_batch_to_graph(
    batch_id: str,
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> CompilationResponse:
    """Compile approved evidence claims for a batch into the operational graph."""
    require_workspace_access(workspace_id, auth)
    try:
        result = await compile_evidence_to_graph(db, workspace_id, batch_id)

        # Invalidate derived caches — features and operational context
        # depend on the sealed graph snapshot, so any cached snapshot
        # built from a previous graph version is now stale.
        from app.modules.graph.cache import create_cache
        from app.modules.graph.context_engine import create_context_cache

        # Cache invalidation is best-effort — failure here should
        # not undo a successful compile. Stale entries will simply
        # expire when their TTL elapses.
        with contextlib.suppress(Exception):
            await create_cache().invalidate_workspace(workspace_id)

        ctx_cache = create_context_cache()
        if hasattr(ctx_cache, "invalidate"):
            with contextlib.suppress(Exception):
                await ctx_cache.invalidate(workspace_id)

        return CompilationResponse(
            snapshot_id=result.snapshot_id,
            version=result.version,
            snapshot_hash=result.snapshot_hash,
            node_count=result.node_count,
            edge_count=result.edge_count,
            write_event_count=result.write_event_count,
            provenance_link_count=result.provenance_link_count,
            integrity_passed=result.integrity_passed,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/nodes", response_model=list[NodeResponse])
async def list_nodes(
    workspace_id: str = Query(...),
    entity_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[NodeResponse]:
    """List graph nodes for a workspace, optionally filtered by entity type."""
    require_workspace_access(workspace_id, auth)
    stmt = (
        select(GraphNode)
        .where(GraphNode.workspace_id == workspace_id)
        .where(GraphNode.valid_to.is_(None))
        .offset(offset)
        .limit(limit)
        .order_by(GraphNode.entity_type, GraphNode.entity_id)
    )
    if entity_type:
        stmt = stmt.where(GraphNode.entity_type == entity_type)
    result = await db.execute(stmt)
    return [
        NodeResponse(
            node_id=n.node_id,
            entity_type=n.entity_type,
            entity_id=n.entity_id,
            attributes=n.attributes,
            first_seen_version=n.first_seen_version,
            last_modified_version=n.last_modified_version,
        )
        for n in result.scalars().all()
    ]


@router.get("/edges", response_model=list[EdgeResponse])
async def list_edges(
    workspace_id: str = Query(...),
    relationship_type: str | None = Query(None),
    source_node_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[EdgeResponse]:
    """List graph edges for a workspace."""
    require_workspace_access(workspace_id, auth)
    stmt = (
        select(GraphEdge)
        .where(GraphEdge.workspace_id == workspace_id)
        .where(GraphEdge.valid_to.is_(None))
        .offset(offset)
        .limit(limit)
        .order_by(GraphEdge.relationship_type)
    )
    if relationship_type:
        stmt = stmt.where(GraphEdge.relationship_type == relationship_type)
    if source_node_id:
        stmt = stmt.where(GraphEdge.source_node_id == source_node_id)
    result = await db.execute(stmt)
    return [
        EdgeResponse(
            edge_id=e.edge_id,
            source_node_id=e.source_node_id,
            target_node_id=e.target_node_id,
            relationship_type=e.relationship_type,
            attributes=e.attributes,
            first_seen_version=e.first_seen_version,
            last_modified_version=e.last_modified_version,
        )
        for e in result.scalars().all()
    ]


@router.get("/snapshots", response_model=list[SnapshotResponse])
async def list_workspace_snapshots(
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[SnapshotResponse]:
    """List graph snapshots for a workspace, newest first."""
    require_workspace_access(workspace_id, auth)
    snaps = await list_snapshots(db, workspace_id)
    return [
        SnapshotResponse(
            snapshot_id=s.snapshot_id,
            version=s.version,
            snapshot_hash=s.snapshot_hash,
            prev_snapshot_hash=s.prev_snapshot_hash,
            node_count=s.node_count,
            edge_count=s.edge_count,
            source_batch_id=s.source_batch_id,
            sealed_at=s.sealed_at.isoformat() if s.sealed_at else "",
        )
        for s in snaps
    ]


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot_detail(
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> SnapshotResponse:
    """Get a single graph snapshot by ID."""
    snap = await get_snapshot(db, snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    require_workspace_access(snap.workspace_id, auth)
    return SnapshotResponse(
        snapshot_id=snap.snapshot_id,
        version=snap.version,
        snapshot_hash=snap.snapshot_hash,
        prev_snapshot_hash=snap.prev_snapshot_hash,
        node_count=snap.node_count,
        edge_count=snap.edge_count,
        source_batch_id=snap.source_batch_id,
        sealed_at=snap.sealed_at.isoformat() if snap.sealed_at else "",
    )


@router.get("/integrity", response_model=IntegrityResponse)
async def graph_integrity(
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> IntegrityResponse:
    """Run integrity checks on the workspace's graph."""
    require_workspace_access(workspace_id, auth)
    report = await get_integrity_report(db, workspace_id)
    chain_verified = await verify_snapshot_chain(db, workspace_id)
    return IntegrityResponse(
        no_orphan_edges=report["no_orphan_edges"],
        all_nodes_have_provenance=report["all_nodes_have_provenance"],
        all_edges_have_provenance=report["all_edges_have_provenance"],
        chain_verified=chain_verified,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Traversal endpoints — Program B
# ─────────────────────────────────────────────────────────────────────────────


class TraverseRequest(BaseModel):
    node_id: str
    algorithm: str = "bfs"  # bfs | dfs
    max_depth: int = 3
    direction: str = "out"
    relationship_type: str | None = None


class TraverseResponse(BaseModel):
    visited: list[str]
    depths: dict[str, int] | None = None
    parents: dict[str, str | None] | None = None


@router.post("/traverse", response_model=TraverseResponse)
async def traverse_graph(
    workspace_id: str = Query(...),
    body: TraverseRequest = ...,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> TraverseResponse:
    """Run a BFS or DFS traversal from a seed node."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    loaded = await service.load_workspace_graph(workspace_id)

    if body.algorithm == "dfs":
        visited = service.dfs(
            loaded.graph,
            body.node_id,
            max_depth=body.max_depth,
            direction=body.direction,
            relationship_type=body.relationship_type,
        )
        return TraverseResponse(visited=visited, depths=None, parents=None)

    result = service.bfs(
        loaded.graph,
        body.node_id,
        max_depth=body.max_depth,
        direction=body.direction,
        relationship_type=body.relationship_type,
    )
    return TraverseResponse(
        visited=result.visited,
        depths={k: v for k, v in result.depths.items()},
        parents={k: v for k, v in result.parents.items()},
    )


class ShortestPathRequest(BaseModel):
    source_id: str
    target_id: str
    direction: str = "out"
    relationship_type: str | None = None


@router.post("/shortest-path")
async def compute_shortest_path(
    workspace_id: str = Query(...),
    body: ShortestPathRequest = ...,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Find the shortest path between two nodes."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    loaded = await service.load_workspace_graph(workspace_id)

    path = service.shortest_path(
        loaded.graph,
        body.source_id,
        body.target_id,
        direction=body.direction,
        relationship_type=body.relationship_type,
    )
    return {
        "source_id": body.source_id,
        "target_id": body.target_id,
        "path": path,
        "length": len(path) - 1 if path else None,
    }


class ReachableRequest(BaseModel):
    node_id: str
    direction: str = "out"  # out = reachable_from, in = reachable_to
    max_depth: int = 10
    relationship_type: str | None = None


@router.post("/reachable")
async def compute_reachable(
    workspace_id: str = Query(...),
    body: ReachableRequest = ...,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Compute the set of nodes reachable from (or that can reach) a node."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    loaded = await service.load_workspace_graph(workspace_id)

    if body.direction == "in":
        reached = service.reachable_to(
            loaded.graph,
            body.node_id,
            max_depth=body.max_depth,
            relationship_type=body.relationship_type,
        )
    else:
        reached = service.reachable_from(
            loaded.graph,
            body.node_id,
            max_depth=body.max_depth,
            relationship_type=body.relationship_type,
        )
    return {
        "node_id": body.node_id,
        "direction": body.direction,
        "reachable": sorted(reached),
        "count": len(reached),
    }


class FindPathsRequest(BaseModel):
    source_id: str
    target_id: str
    max_depth: int = 4
    max_paths: int = 100
    relationship_type: str | None = None


@router.post("/paths")
async def compute_paths(
    workspace_id: str = Query(...),
    body: FindPathsRequest = ...,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Find all simple paths between two nodes (bounded by max_depth + max_paths)."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    loaded = await service.load_workspace_graph(workspace_id)

    paths = service.find_paths(
        loaded.graph,
        body.source_id,
        body.target_id,
        max_depth=body.max_depth,
        max_paths=body.max_paths,
        relationship_type=body.relationship_type,
    )
    return {
        "source_id": body.source_id,
        "target_id": body.target_id,
        "paths": paths,
        "count": len(paths),
    }


class DiffRequest(BaseModel):
    from_snapshot_id: str
    to_snapshot_id: str


@router.post("/snapshots/diff")
async def diff_two_snapshots(
    workspace_id: str = Query(...),
    body: DiffRequest = ...,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Compute the structural diff between two snapshots."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.temporal import diff_snapshots, summarize_diff

    diff = await diff_snapshots(
        db,
        workspace_id,
        body.from_snapshot_id,
        body.to_snapshot_id,
    )
    return summarize_diff(diff)


@router.get("/validate")
async def validate_graph(
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Run the full validation suite against the workspace's graph.

    Released to CI as a gate: if `passed` is False, the release is blocked.
    """
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.validation import validate_workspace_graph

    report = await validate_workspace_graph(db, workspace_id)
    return report.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Feature endpoints — Program C
# ─────────────────────────────────────────────────────────────────────────────


class NodeFeaturesResponse(BaseModel):
    node_id: str
    entity_type: str
    entity_id: str
    in_degree: int
    out_degree: int
    total_degree: int
    degree_centrality: float
    in_degree_centrality: float
    out_degree_centrality: float
    downstream_reach: int
    upstream_reach: int
    total_reach: int
    downstream_depth: int
    upstream_depth: int
    criticality: float
    single_point_of_failure: float
    concentration_risk: float
    redundancy: float
    betweenness: float


class WorkspaceFeaturesResponse(BaseModel):
    workspace_id: str
    snapshot_id: str | None
    snapshot_version: int | None
    snapshot_hash: str | None
    node_count: int
    edge_count: int
    connected_components: int
    max_degree: int
    avg_degree: float
    p95_degree: int
    single_point_of_failure_nodes: int
    high_betweenness_nodes: int
    isolated_nodes: int
    avg_concentration_risk: float
    avg_redundancy: float
    max_criticality: float
    entity_type_counts: dict[str, int]


class FeatureSnapshotResponse(BaseModel):
    workspace_id: str
    snapshot_id: str | None
    snapshot_version: int | None
    snapshot_hash: str | None
    workspace: WorkspaceFeaturesResponse | None
    by_node: dict[str, NodeFeaturesResponse]


@router.get("/features", response_model=FeatureSnapshotResponse)
async def get_workspace_features(
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> FeatureSnapshotResponse:
    """Compute (or retrieve from cache) the full feature snapshot for a workspace."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.cache import create_cache
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    engine = FeatureEngine(service, create_cache())

    result = await engine.compute_features(workspace_id, use_cache=True)
    fs = result.snapshot

    return FeatureSnapshotResponse(
        workspace_id=fs.workspace_id,
        snapshot_id=fs.snapshot_id,
        snapshot_version=fs.snapshot_version,
        snapshot_hash=fs.snapshot_hash,
        workspace=WorkspaceFeaturesResponse(
            workspace_id=fs.workspace.workspace_id,
            snapshot_id=fs.workspace.snapshot_id,
            snapshot_version=fs.workspace.snapshot_version,
            snapshot_hash=fs.workspace.snapshot_hash,
            node_count=fs.workspace.node_count,
            edge_count=fs.workspace.edge_count,
            connected_components=fs.workspace.connected_components,
            max_degree=fs.workspace.max_degree,
            avg_degree=fs.workspace.avg_degree,
            p95_degree=fs.workspace.p95_degree,
            single_point_of_failure_nodes=fs.workspace.single_point_of_failure_nodes,
            high_betweenness_nodes=fs.workspace.high_betweenness_nodes,
            isolated_nodes=fs.workspace.isolated_nodes,
            avg_concentration_risk=fs.workspace.avg_concentration_risk,
            avg_redundancy=fs.workspace.avg_redundancy,
            max_criticality=fs.workspace.max_criticality,
            entity_type_counts=fs.workspace.entity_type_counts,
        )
        if fs.workspace
        else None,
        by_node={
            nid: NodeFeaturesResponse(
                node_id=nf.node_id,
                entity_type=nf.entity_type,
                entity_id=nf.entity_id,
                in_degree=nf.in_degree,
                out_degree=nf.out_degree,
                total_degree=nf.total_degree,
                degree_centrality=nf.degree_centrality,
                in_degree_centrality=nf.in_degree_centrality,
                out_degree_centrality=nf.out_degree_centrality,
                downstream_reach=nf.downstream_reach,
                upstream_reach=nf.upstream_reach,
                total_reach=nf.total_reach,
                downstream_depth=nf.downstream_depth,
                upstream_depth=nf.upstream_depth,
                criticality=nf.criticality,
                single_point_of_failure=nf.single_point_of_failure,
                concentration_risk=nf.concentration_risk,
                redundancy=nf.redundancy,
                betweenness=nf.betweenness,
            )
            for nid, nf in fs.by_node.items()
        },
    )


@router.get("/features/{node_id}", response_model=NodeFeaturesResponse)
async def get_node_features(
    node_id: str,
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> NodeFeaturesResponse:
    """Get feature vector for a single node."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.cache import create_cache
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    engine = FeatureEngine(service, create_cache())

    result = await engine.compute_features(workspace_id, use_cache=True)
    fs = result.snapshot

    if node_id not in fs.by_node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")

    nf = fs.by_node[node_id]
    return NodeFeaturesResponse(
        node_id=nf.node_id,
        entity_type=nf.entity_type,
        entity_id=nf.entity_id,
        in_degree=nf.in_degree,
        out_degree=nf.out_degree,
        total_degree=nf.total_degree,
        degree_centrality=nf.degree_centrality,
        in_degree_centrality=nf.in_degree_centrality,
        out_degree_centrality=nf.out_degree_centrality,
        downstream_reach=nf.downstream_reach,
        upstream_reach=nf.upstream_reach,
        total_reach=nf.total_reach,
        downstream_depth=nf.downstream_depth,
        upstream_depth=nf.upstream_depth,
        criticality=nf.criticality,
        single_point_of_failure=nf.single_point_of_failure,
        concentration_risk=nf.concentration_risk,
        redundancy=nf.redundancy,
        betweenness=nf.betweenness,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Signal endpoints — Program D
# ─────────────────────────────────────────────────────────────────────────────


class SignalInstanceResponse(BaseModel):
    signal_id: str
    signal_name: str
    signal_version: str
    workspace_id: str
    snapshot_version: int | None
    snapshot_hash: str | None
    severity: str
    confidence: float
    category: str
    affected_node_ids: list[str]
    affected_entity_types: list[str]
    affected_entity_ids: list[str]
    propagation_scope: str
    feature_evidence: dict[str, float]
    explanation: str
    created_at: str


class SignalSnapshotResponse(BaseModel):
    workspace_id: str
    snapshot_version: int | None
    snapshot_hash: str | None
    signals: list[SignalInstanceResponse]
    metadata: dict[str, Any]


@router.get("/signals", response_model=SignalSnapshotResponse)
async def get_workspace_signals(
    workspace_id: str = Query(...),
    signal_names: str | None = Query(None, description="Comma-separated signal names to compute"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> SignalSnapshotResponse:
    """Detect all operational signals for a workspace."""
    require_workspace_access(workspace_id, auth)
    from app.modules.graph.cache import create_cache
    from app.modules.graph.context_engine import (
        OperationalStateEngine,
        SqlOperationalStateRepository,
        create_context_cache,
    )
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService
    from app.modules.graph.signal_engine import SignalEngine

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    feature_engine = FeatureEngine(service, create_cache())
    context_engine = OperationalStateEngine(
        SqlOperationalStateRepository(db, create_context_cache()),
        context_cache=create_context_cache(),
    )
    signal_engine = SignalEngine(feature_engine, context_engine)

    signals_to_compute = signal_names.split(",") if signal_names else None
    result = await signal_engine.detect_signals(workspace_id, signal_names=signals_to_compute)
    ss = result.snapshot

    return SignalSnapshotResponse(
        workspace_id=ss.workspace_id,
        snapshot_version=ss.snapshot_version,
        snapshot_hash=ss.snapshot_hash,
        signals=[
            SignalInstanceResponse(
                signal_id=sig.signal_id,
                signal_name=sig.signal_name,
                signal_version=sig.signal_version,
                workspace_id=sig.workspace_id,
                snapshot_version=sig.snapshot_version,
                snapshot_hash=sig.snapshot_hash,
                severity=sig.severity.value,
                confidence=sig.confidence,
                category=sig.category.value,
                affected_node_ids=sig.affected_node_ids,
                affected_entity_types=sig.affected_entity_types,
                affected_entity_ids=sig.affected_entity_ids,
                propagation_scope=sig.propagation_scope,
                feature_evidence=sig.feature_evidence,
                explanation=sig.explanation,
                created_at=sig.created_at.isoformat(),
            )
            for sig in ss.signals
        ],
        metadata=ss.metadata,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Propagation endpoints — Program E
# ─────────────────────────────────────────────────────────────────────────────


class PropagationStepResponse(BaseModel):
    propagation_id: str
    source_signal_id: str
    source_node_id: str
    source_node_type: str
    affected_node_id: str
    affected_node_type: str
    affected_entity_id: str
    hop_number: int
    relationship_type: str
    parent_node_id: str | None
    attenuation: float
    confidence: float
    impact_type: str
    impact_severity: str
    impact_reason: str


class AffectedEntityResponse(BaseModel):
    node_id: str
    entity_id: str
    entity_type: str
    hop_number: int
    impact_type: str
    impact_severity: str
    confidence: float
    impact_reason: str


class ImpactSummaryResponse(BaseModel):
    total_affected: int
    by_impact_type: dict[str, int]
    by_severity: dict[str, int]
    by_entity_type: dict[str, int]
    max_hop: int
    avg_confidence: float
    min_confidence: float


class PropagationTreeResponse(BaseModel):
    propagation_id: str
    source_signal_id: str
    source_node_id: str
    source_node_type: str
    steps: list[PropagationStepResponse]


class PropagationSnapshotResponse(BaseModel):
    propagation_id: str
    workspace_id: str
    source_signal_id: str
    source_signal_name: str
    source_node_id: str
    source_node_type: str
    source_severity: str
    source_confidence: float
    graph_version: int | None
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    signal_snapshot_version: int | None
    tree: PropagationTreeResponse
    affected_entities: list[AffectedEntityResponse]
    summary: ImpactSummaryResponse
    affected_facilities: list[str]
    affected_inventory: list[str]
    affected_orders: list[str]
    affected_customers: list[str]
    execution_time_ms: float
    max_depth_reached: int
    rules_applied: list[str]
    created_at: str
    metadata: dict[str, Any]


class PropagationRequestModel(BaseModel):
    workspace_id: str
    source_signal_id: str
    source_node_id: str
    max_depth: int = 5
    min_confidence: float = 0.1
    impact_type_filter: str | None = None


@router.post("/propagate", response_model=PropagationSnapshotResponse)
async def run_propagation(
    body: PropagationRequestModel,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> PropagationSnapshotResponse:
    """Run propagation from a signal across the operational graph."""
    require_workspace_access(body.workspace_id, auth)
    from app.modules.graph.cache import create_cache
    from app.modules.graph.context_engine import (
        OperationalStateEngine,
        SqlOperationalStateRepository,
        create_context_cache,
    )
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.propagation_models import ImpactType
    from app.modules.graph.propagation_service import PropagationService
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService
    from app.modules.graph.signal_engine import SignalEngine

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    feature_engine = FeatureEngine(service, create_cache())
    context_engine = OperationalStateEngine(
        SqlOperationalStateRepository(db, create_context_cache()),
        context_cache=create_context_cache(),
    )
    signal_engine = SignalEngine(feature_engine, context_engine)

    it_filter = None
    if body.impact_type_filter:
        try:
            it_filter = ImpactType(body.impact_type_filter)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Unknown impact_type: {body.impact_type_filter}"
            ) from None

    propagation_service = PropagationService(
        feature_engine=feature_engine,
        context_engine=context_engine,
        signal_engine=signal_engine,
        graph_service=service,
    )

    result = await propagation_service.run_propagation(
        workspace_id=body.workspace_id,
        source_signal_id=body.source_signal_id,
        source_node_id=body.source_node_id,
        max_depth=body.max_depth,
        min_confidence=body.min_confidence,
        impact_type_filter=it_filter,
    )

    if not result.result.success:
        raise HTTPException(status_code=404, detail="; ".join(result.result.warnings))

    snap = result.result.snapshot

    return PropagationSnapshotResponse(
        propagation_id=snap.propagation_id,
        workspace_id=snap.workspace_id,
        source_signal_id=snap.source_signal_id,
        source_signal_name=snap.source_signal_name,
        source_node_id=snap.source_node_id,
        source_node_type=snap.source_node_type,
        source_severity=snap.source_severity.value,
        source_confidence=snap.source_confidence,
        graph_version=snap.graph_version,
        feature_snapshot_version=snap.feature_snapshot_version,
        context_snapshot_version=snap.context_snapshot_version,
        signal_snapshot_version=snap.signal_snapshot_version,
        tree=PropagationTreeResponse(
            propagation_id=snap.tree.propagation_id,
            source_signal_id=snap.tree.source_signal_id,
            source_node_id=snap.tree.source_node_id,
            source_node_type=snap.tree.source_node_type,
            steps=[
                PropagationStepResponse(
                    propagation_id=s.propagation_id,
                    source_signal_id=s.source_signal_id,
                    source_node_id=s.source_node_id,
                    source_node_type=s.source_node_type,
                    affected_node_id=s.affected_node_id,
                    affected_node_type=s.affected_node_type,
                    affected_entity_id=s.affected_entity_id,
                    hop_number=s.hop_number,
                    relationship_type=s.relationship_type,
                    parent_node_id=s.parent_node_id,
                    attenuation=s.attenuation,
                    confidence=s.confidence,
                    impact_type=s.impact_type.value,
                    impact_severity=s.impact_severity.value,
                    impact_reason=s.impact_reason,
                )
                for s in snap.tree.steps
            ],
        ),
        affected_entities=[
            AffectedEntityResponse(
                node_id=e.node_id,
                entity_id=e.entity_id,
                entity_type=e.entity_type,
                hop_number=e.hop_number,
                impact_type=e.impact_type.value,
                impact_severity=e.impact_severity.value,
                confidence=e.confidence,
                impact_reason=e.impact_reason,
            )
            for e in snap.affected_entities
        ],
        summary=ImpactSummaryResponse(
            total_affected=snap.summary.total_affected,
            by_impact_type=snap.summary.by_impact_type,
            by_severity=snap.summary.by_severity,
            by_entity_type=snap.summary.by_entity_type,
            max_hop=snap.summary.max_hop,
            avg_confidence=snap.summary.avg_confidence,
            min_confidence=snap.summary.min_confidence,
        ),
        affected_facilities=snap.affected_facilities,
        affected_inventory=snap.affected_inventory,
        affected_orders=snap.affected_orders,
        affected_customers=snap.affected_customers,
        execution_time_ms=snap.execution_time_ms,
        max_depth_reached=snap.max_depth_reached,
        rules_applied=snap.rules_applied,
        created_at=snap.created_at.isoformat(),
        metadata=snap.metadata,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario endpoints — Program F
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioParameterModel(BaseModel):
    name: str
    value: Any
    unit: str | None = None
    description: str = ""


class ScenarioDefinitionModel(BaseModel):
    scenario_id: str
    workspace_id: str
    scenario_type: str
    name: str
    description: str
    parameters: list[ScenarioParameterModel] = []
    source_propagation_id: str | None = None
    source_signal_id: str | None = None
    max_depth: int | None = None
    min_confidence: float | None = None
    impact_type_filter: str | None = None
    created_by: str | None = None
    version: str = "1.0.0"
    tags: list[str] = []
    metadata: dict[str, Any] = {}


class ScenarioAssumptionResponse(BaseModel):
    assumption_id: str
    scenario_id: str
    description: str
    category: str
    confidence: float
    source: str
    metadata: dict[str, Any]


class ScenarioImpactResponse(BaseModel):
    scenario_id: str
    affected_node_id: str
    affected_entity_id: str
    affected_entity_type: str
    hop_number: int
    impact_category: str
    severity: str
    confidence: float
    estimated_recovery_hours: float | None
    estimated_financial_impact: float | None
    estimated_service_level_impact_pct: float | None
    source_propagation_step_id: str | None


class ScenarioSummaryResponse(BaseModel):
    total_impacted_entities: int
    by_impact_category: dict[str, int]
    by_severity: dict[str, int]
    by_entity_type: dict[str, int]
    max_hop: int
    avg_confidence: float
    min_confidence: float
    total_estimated_recovery_hours: float
    total_estimated_financial_impact: float
    max_service_level_impact_pct: float


class ScenarioSnapshotResponse(BaseModel):
    scenario_id: str
    workspace_id: str
    scenario_definition: ScenarioDefinitionModel
    status: str
    assumptions: list[ScenarioAssumptionResponse]
    impacts: list[ScenarioImpactResponse]
    summary: ScenarioSummaryResponse
    source_propagation_id: str | None
    source_signal_id: str | None
    graph_version: int | None
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    propagation_snapshot_version: int | None
    execution_time_ms: float
    rules_applied: list[str]
    warnings: list[str]
    error: str | None
    scenario_snapshot_version: int
    scenario_snapshot_hash: str | None
    created_at: str
    completed_at: str | None
    metadata: dict[str, Any]


class ScenarioRequestModel(BaseModel):
    workspace_id: str
    scenario_definition: ScenarioDefinitionModel
    source_propagation_id: str | None = None
    source_signal_id: str | None = None
    dry_run: bool = False


@router.post("/scenarios", response_model=ScenarioSnapshotResponse)
async def run_scenario(
    body: ScenarioRequestModel,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ScenarioSnapshotResponse:
    """Execute a what-if scenario simulation."""
    require_workspace_access(body.workspace_id, auth)
    from app.modules.graph.cache import create_cache
    from app.modules.graph.context_engine import (
        OperationalStateEngine,
        SqlOperationalStateRepository,
        create_context_cache,
    )
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService

    repo = SqlGraphRepository(db)
    service = GraphService(repo)
    feature_engine = FeatureEngine(service, create_cache())
    context_engine = OperationalStateEngine(
        SqlOperationalStateRepository(db, create_context_cache()),
        context_cache=create_context_cache(),
    )

    # Parse scenario type
    try:
        scenario_type = ScenarioType(body.scenario_definition.scenario_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario_type: {body.scenario_definition.scenario_type}",
        ) from None

    # Build ScenarioDefinition
    definition = ScenarioDefinition(
        scenario_id=body.scenario_definition.scenario_id,
        workspace_id=body.workspace_id,
        scenario_type=scenario_type,
        name=body.scenario_definition.name,
        description=body.scenario_definition.description,
        parameters=[
            ScenarioParameter(
                name=p.name,
                value=p.value,
                unit=p.unit,
                description=p.description,
            )
            for p in body.scenario_definition.parameters
        ],
        source_propagation_id=body.source_propagation_id
        or body.scenario_definition.source_propagation_id,
        source_signal_id=body.source_signal_id or body.scenario_definition.source_signal_id,
        max_depth=body.scenario_definition.max_depth,
        min_confidence=body.scenario_definition.min_confidence,
        impact_type_filter=body.scenario_definition.impact_type_filter,
        created_by=body.scenario_definition.created_by,
        version=body.scenario_definition.version,
        tags=body.scenario_definition.tags,
        metadata=body.scenario_definition.metadata,
    )

    # Get propagation if provided.
    # NOTE: full propagation-loading by source_propagation_id/source_signal_id
    # is not yet implemented (Program E integration); propagation remains None
    # and scenarios operate on the freshly computed snapshot below.
    propagation = None

    # Get enriched snapshot for context-aware estimates
    feature_result = await feature_engine.compute_features(body.workspace_id, use_cache=True)
    context_result = await context_engine.load_operational_state(body.workspace_id)
    from app.modules.graph.context_fusion import EnrichedSnapshot

    enriched = EnrichedSnapshot.fuse(feature_result.snapshot, context_result.snapshot)

    # Allocate a DB-backed monotonic version for the scenario snapshot
    from app.modules.graph.versioning import get_next_version

    scenario_version = await get_next_version(db, body.workspace_id, "scenario")

    # Execute scenario
    # NB: this endpoint runs ScenarioEngine directly (no propagation loading).
    # The full ScenarioService.run_scenario path is exercised by the
    # recommendation endpoint below; here the caller may supply their own
    # propagation by id (Program E integration is deferred).
    from app.modules.graph.scenario_engine import ScenarioEngine
    from app.modules.graph.scenario_models import ScenarioRequest

    request = ScenarioRequest(
        workspace_id=body.workspace_id,
        scenario_definition=definition,
        source_propagation_id=body.source_propagation_id,
        source_signal_id=body.source_signal_id,
        dry_run=body.dry_run,
        snapshot_version=scenario_version,
    )
    result = ScenarioEngine().execute(
        request=request,
        propagation=propagation,
        enriched=enriched,
    )

    if not result.success:
        raise HTTPException(status_code=404, detail="; ".join(result.warnings)) from None

    snap = result.snapshot

    return ScenarioSnapshotResponse(
        scenario_id=snap.scenario_id,
        workspace_id=snap.workspace_id,
        scenario_definition=ScenarioDefinitionModel(
            scenario_id=snap.scenario_definition.scenario_id,
            workspace_id=snap.scenario_definition.workspace_id,
            scenario_type=snap.scenario_definition.scenario_type.value,
            name=snap.scenario_definition.name,
            description=snap.scenario_definition.description,
            parameters=[
                ScenarioParameterModel(
                    name=p.name, value=p.value, unit=p.unit, description=p.description
                )
                for p in snap.scenario_definition.parameters
            ],
            source_propagation_id=snap.scenario_definition.source_propagation_id,
            source_signal_id=snap.scenario_definition.source_signal_id,
            max_depth=snap.scenario_definition.max_depth,
            min_confidence=snap.scenario_definition.min_confidence,
            impact_type_filter=snap.scenario_definition.impact_type_filter,
            created_by=snap.scenario_definition.created_by,
            version=snap.scenario_definition.version,
            tags=snap.scenario_definition.tags,
            metadata=snap.scenario_definition.metadata,
        ),
        status=snap.status.value,
        assumptions=[
            ScenarioAssumptionResponse(
                assumption_id=a.assumption_id,
                scenario_id=a.scenario_id,
                description=a.description,
                category=a.category,
                confidence=a.confidence,
                source=a.source,
                metadata=a.metadata,
            )
            for a in snap.assumptions
        ],
        impacts=[
            ScenarioImpactResponse(
                scenario_id=i.scenario_id,
                affected_node_id=i.affected_node_id,
                affected_entity_id=i.affected_entity_id,
                affected_entity_type=i.affected_entity_type,
                hop_number=i.hop_number,
                impact_category=i.impact_category,
                severity=i.severity,
                confidence=i.confidence,
                estimated_recovery_hours=i.estimated_recovery_hours,
                estimated_financial_impact=i.estimated_financial_impact,
                estimated_service_level_impact_pct=i.estimated_service_level_impact_pct,
                source_propagation_step_id=i.source_propagation_step_id,
            )
            for i in snap.impacts
        ],
        summary=ScenarioSummaryResponse(
            total_impacted_entities=snap.summary.total_impacted_entities,
            by_impact_category=snap.summary.by_impact_category,
            by_severity=snap.summary.by_severity,
            by_entity_type=snap.summary.by_entity_type,
            max_hop=snap.summary.max_hop,
            avg_confidence=snap.summary.avg_confidence,
            min_confidence=snap.summary.min_confidence,
            total_estimated_recovery_hours=snap.summary.total_estimated_recovery_hours,
            total_estimated_financial_impact=snap.summary.total_estimated_financial_impact,
            max_service_level_impact_pct=snap.summary.max_service_level_impact_pct,
        ),
        source_propagation_id=snap.source_propagation_id,
        source_signal_id=snap.source_signal_id,
        graph_version=snap.graph_version,
        feature_snapshot_version=snap.feature_snapshot_version,
        context_snapshot_version=snap.context_snapshot_version,
        propagation_snapshot_version=snap.propagation_snapshot_version,
        execution_time_ms=snap.execution_time_ms,
        rules_applied=snap.rules_applied,
        warnings=snap.warnings,
        error=snap.error,
        scenario_snapshot_version=snap.scenario_snapshot_version,
        scenario_snapshot_hash=snap.scenario_snapshot_hash,
        created_at=snap.created_at.isoformat(),
        completed_at=snap.completed_at.isoformat() if snap.completed_at else None,
        metadata=snap.metadata,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation API Models
# ─────────────────────────────────────────────────────────────────────────────


class RecommendationRequestModel(BaseModel):
    """Request to generate recommendations for a scenario.

    A full scenario definition is required (recommendations are generated
    from the scenario type and its propagation context; there is currently
    no persisted-scenario lookup path). ``scenario_definition.scenario_id``
    is the upstream identifier returned to the caller.
    """

    workspace_id: str
    scenario_definition: ScenarioDefinitionModel
    source_propagation_id: str | None = None
    source_signal_id: str | None = None
    include_explanations: bool = True
    include_trade_offs: bool = True
    min_confidence: float = 0.0
    max_recommendations: int | None = None
    dry_run: bool = False


# Recommendation API Response Models
class RecommendationCandidateResponse(BaseModel):
    """A candidate recommendation."""

    candidate_id: str
    recommendation_type: str
    category: str
    name: str
    description: str
    source_scenario_id: str
    source_propagation_id: str | None
    source_signal_ids: list[str]
    required_evidence: list[str]
    affected_node_ids: list[str]
    affected_entity_ids: list[str]
    affected_entity_types: list[str]
    metadata: dict[str, Any] = {}


class RecommendationScoresResponse(BaseModel):
    """Scores for a recommendation."""

    overall_score: float
    risk_reduction_score: float
    cost_score: float
    time_score: float
    reversibility_score: float
    confidence_score: float
    policy_fit_score: float
    impact_reduction_score: float
    scoring_version: str
    scoring_formula: str


class RecommendationTradeOffResponse(BaseModel):
    """A trade-off for a recommendation."""

    trade_off_id: str
    dimension: str
    gain: str
    loss: str
    magnitude: str
    quantified_gain: float | None = None
    quantified_loss: float | None = None


class RecommendationExplanationResponse(BaseModel):
    """Explanation for a recommendation."""

    explanation_id: str
    what: str
    why: str
    evidence_summary: str
    scenario_addressed: str
    propagation_impact: str
    assumptions: list[str]
    uncertainties: list[str]
    review_guidance: str


class RankedRecommendationResponse(BaseModel):
    """A ranked recommendation."""

    recommendation_id: str
    rank: int
    candidate: RecommendationCandidateResponse
    scores: RecommendationScoresResponse
    trade_offs: list[RecommendationTradeOffResponse]
    explanation: RecommendationExplanationResponse | None
    reversibility: str
    policy_classification: str
    estimated_cost_usd: float | None = None
    estimated_time_to_benefit_hours: float | None = None
    estimated_impact_reduction_pct: float | None = None
    graph_version: int | None = None
    context_version: int | None = None
    scenario_snapshot_version: int | None = None
    created_at: str
    metadata: dict[str, Any] = {}


class RecommendationSnapshotResponse(BaseModel):
    """Complete recommendation snapshot."""

    recommendation_snapshot_id: str
    workspace_id: str
    source_scenario_id: str
    source_scenario_snapshot_version: int | None
    source_propagation_id: str | None
    source_propagation_snapshot_version: int | None
    source_signal_ids: list[str]
    graph_version: int | None
    context_version: int | None
    feature_snapshot_version: int | None
    recommendations: list[RankedRecommendationResponse]
    total_candidates_generated: int
    total_candidates_after_dedup: int
    scoring_version: str
    ranking_version: str
    execution_time_ms: float
    warnings: list[str]
    error: str | None = None
    created_at: str
    recommendation_snapshot_version: int
    recommendation_snapshot_hash: str | None = None
    metadata: dict[str, Any] = {}


class RecommendationResultResponse(BaseModel):
    """Recommendation result wrapper."""

    snapshot: RecommendationSnapshotResponse
    success: bool
    warnings: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/recommendations/generate", response_model=RecommendationResultResponse)
async def generate_recommendations(
    body: RecommendationRequestModel,
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> RecommendationResultResponse:
    """Generate recommendations for a scenario.

    This endpoint:
      1. Loads or executes the specified scenario
      2. Generates candidate recommendations based on scenario type
      3. Scores and ranks recommendations
      4. Returns structured recommendations with explanations and trade-offs

    Recommendations are advisory only — humans make final decisions.
    """
    from app.modules.graph.cache import create_cache
    from app.modules.graph.context_engine import (
        OperationalStateEngine,
        SqlOperationalStateRepository,
        create_context_cache,
    )
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.propagation_service import PropagationService
    from app.modules.graph.recommendation_engine import RecommendationEngine
    from app.modules.graph.recommendation_service import RecommendationService
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.scenario_engine import ScenarioEngine
    from app.modules.graph.scenario_service import ScenarioService
    from app.modules.graph.service import GraphService
    from app.modules.graph.signal_engine import SignalEngine

    # Verify workspace access
    require_workspace_access(workspace_id, auth)

    # Allocate DB-backed monotonic versions for scenario + recommendation snapshots
    from app.modules.graph.versioning import get_next_version

    scenario_version = await get_next_version(db, workspace_id, "scenario")
    recommendation_version = await get_next_version(db, workspace_id, "recommendation")

    # Initialize engines with proper dependencies
    repo = SqlGraphRepository(db)
    graph_service = GraphService(repo)
    feature_engine = FeatureEngine(graph_service, create_cache())
    context_engine = OperationalStateEngine(
        SqlOperationalStateRepository(db, create_context_cache()),
        context_cache=create_context_cache(),
    )
    signal_engine = SignalEngine(feature_engine, context_engine)

    propagation_service = PropagationService(
        feature_engine=feature_engine,
        context_engine=context_engine,
        signal_engine=signal_engine,
        graph_service=graph_service,
    )

    scenario_service = ScenarioService(
        feature_engine=feature_engine,
        context_engine=context_engine,
        signal_engine=signal_engine,
        propagation_service=propagation_service,
        scenario_engine=ScenarioEngine(),
    )

    recommendation_engine = RecommendationEngine()

    service = RecommendationService(
        feature_engine=feature_engine,
        context_engine=context_engine,
        signal_engine=signal_engine,
        propagation_service=propagation_service,
        scenario_service=scenario_service,
        recommendation_engine=recommendation_engine,
    )

    # Build scenario definition from request
    try:
        scenario_type = ScenarioType(body.scenario_definition.scenario_type)
    except ValueError as err:
        valid = [t.value for t in ScenarioType]
        raise HTTPException(
            status_code=422,
            detail=f"Unknown scenario_type: {body.scenario_definition.scenario_type}. "
            f"Valid types: {valid}",
        ) from err

    scenario_definition = ScenarioDefinition(
        scenario_id=body.scenario_definition.scenario_id,
        workspace_id=body.workspace_id,
        scenario_type=scenario_type,
        name=body.scenario_definition.name,
        description=body.scenario_definition.description,
        parameters=[
            ScenarioParameter(
                name=p.name,
                value=p.value,
                unit=p.unit,
                description=p.description,
            )
            for p in body.scenario_definition.parameters
        ],
        source_propagation_id=body.source_propagation_id
        or body.scenario_definition.source_propagation_id,
        source_signal_id=body.source_signal_id or body.scenario_definition.source_signal_id,
        max_depth=body.scenario_definition.max_depth,
        min_confidence=body.scenario_definition.min_confidence,
        impact_type_filter=body.scenario_definition.impact_type_filter,
        created_by=body.scenario_definition.created_by,
        version=body.scenario_definition.version,
        tags=body.scenario_definition.tags,
        metadata=body.scenario_definition.metadata,
    )

    # Generate recommendations
    result = await service.generate_recommendations(
        workspace_id=workspace_id,
        scenario_definition=scenario_definition,
        source_propagation_id=scenario_definition.source_propagation_id,
        source_signal_id=scenario_definition.source_signal_id,
        include_explanations=body.include_explanations,
        include_trade_offs=body.include_trade_offs,
        min_confidence=body.min_confidence,
        max_recommendations=body.max_recommendations,
        dry_run=body.dry_run,
        snapshot_version=recommendation_version,
        scenario_snapshot_version=scenario_version,
    )

    return RecommendationResultResponse(
        snapshot=result.result.snapshot,
        success=result.result.success,
        warnings=result.warnings,
    )


@router.get("/recommendations/taxonomy", response_model=dict[str, Any])
async def get_recommendation_taxonomy(
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the closed taxonomy of recommendation types.

    Returns all supported recommendation types with their specifications.
    """
    from app.modules.graph.recommendation_rules import RECOMMENDATION_TAXONOMY

    return {
        "taxonomy_version": "1.0.0",
        "recommendation_types": [spec.to_dict() for spec in RECOMMENDATION_TAXONOMY.values()],
    }


@router.get("/recommendations/types", response_model=list[dict[str, str]])
async def list_recommendation_types(
    auth: AuthContext = Depends(get_current_user),
) -> list[dict[str, str]]:
    """List all recommendation types."""
    from app.modules.graph.recommendation_rules import RECOMMENDATION_TAXONOMY

    return [
        {
            "type": spec.recommendation_type.value,
            "name": spec.name,
            "category": spec.category.value,
        }
        for spec in RECOMMENDATION_TAXONOMY.values()
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Decision Memory API — Program H
# ─────────────────────────────────────────────────────────────────────────────


class DecisionRequestModel(BaseModel):
    """Request to create a decision record."""

    workspace_id: str
    scenario_id: str
    recommendation_snapshot_id: str
    selected_recommendation_id: str | None
    decision_type: str
    reviewer_id: str
    rationale: str
    modification_notes: str | None = None
    tags: list[str] = []
    metadata: dict[str, Any] = {}


class DecisionRecordResponse(BaseModel):
    """A decision record."""

    decision_id: str
    workspace_id: str
    scenario_id: str
    recommendation_snapshot_id: str
    selected_recommendation_id: str | None
    decision_type: str
    decision_status: str
    reviewer_id: str
    rationale: str
    modification_notes: str | None
    source_propagation_id: str | None
    source_signal_ids: list[str]
    evidence_claim_ids: list[str]
    graph_version: int | None
    context_version: int | None
    feature_snapshot_version: int | None
    scenario_snapshot_version: int | None
    recommendation_snapshot_version: int | None
    tags: list[str]
    metadata: dict[str, Any]
    created_at: str


class OutcomeRequestModel(BaseModel):
    """Request to append an outcome."""

    outcome_status: str
    outcome_summary: str
    actual_impact_description: str | None = None
    actual_financial_impact: float | None = None
    actual_recovery_hours: float | None = None
    actual_service_level_impact_pct: float | None = None
    met_expectations: bool | None = None
    would_decide_again: bool | None = None
    recorded_by: str
    metadata: dict[str, Any] = {}


class OutcomeResponse(BaseModel):
    """An outcome record."""

    outcome_id: str
    decision_id: str
    workspace_id: str
    outcome_status: str
    outcome_summary: str
    actual_impact_description: str | None
    actual_financial_impact: float | None
    actual_recovery_hours: float | None
    actual_service_level_impact_pct: float | None
    met_expectations: bool | None
    would_decide_again: bool | None
    outcome_recorded_by: str
    created_at: str
    metadata: dict[str, Any]


class LessonRequestModel(BaseModel):
    """Request to append a lesson learned."""

    category: str
    title: str
    description: str
    what_happened: str
    what_expected: str
    what_learned: str
    policy_or_assumption_wrong: str | None = None
    what_to_change_next_time: str | None = None
    should_export_for_training: bool = False
    recorded_by: str
    metadata: dict[str, Any] = {}


class LessonResponse(BaseModel):
    """A lesson learned record."""

    lesson_id: str
    decision_id: str
    outcome_id: str | None
    workspace_id: str
    category: str
    title: str
    description: str
    what_happened: str
    what_expected: str
    what_learned: str
    policy_or_assumption_wrong: str | None
    what_to_change_next_time: str | None
    should_export_for_training: bool
    recorded_by: str
    created_at: str
    metadata: dict[str, Any]


class DecisionSnapshotResponse(BaseModel):
    """Complete decision snapshot with outcomes and lessons."""

    decision: DecisionRecordResponse
    outcomes: list[OutcomeResponse]
    lessons: list[LessonResponse]
    outcome_count: int
    lesson_count: int
    last_outcome_at: str | None
    last_lesson_at: str | None


class DecisionExportResponse(BaseModel):
    """Exportable decision record for training."""

    export_id: str
    decision_id: str
    workspace_id: str
    decision_type: str
    decision_status: str
    rationale: str
    modification_notes: str | None
    scenario_type: str | None
    recommendation_type: str | None
    graph_metrics: dict[str, float]
    outcome_status: str | None
    outcome_summary: str | None
    exportable_lessons: list[LessonResponse]
    exported_at: str
    export_version: str


@router.post("/decisions", response_model=DecisionRecordResponse)
async def create_decision(
    body: DecisionRequestModel,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> DecisionRecordResponse:
    """Create a new decision record.

    This endpoint records a human decision made after reviewing recommendations.
    The decision is append-only and cannot be modified once created.

    Required lineage:
      - scenario_id: which scenario this decision addresses
      - recommendation_snapshot_id: which recommendation snapshot was reviewed
      - selected_recommendation_id: which recommendation was chosen (if any)

    The decision captures:
      - what was decided
      - why it was decided (rationale)
      - who decided it (reviewer_id)
      - what evidence supported it (extracted from upstream snapshots)
    """

    # Verify workspace access
    require_workspace_access(body.workspace_id, auth)

    # Validate decision type
    try:
        decision_type = DecisionType(body.decision_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown decision_type: {body.decision_type}. "
            f"Valid types: {[t.value for t in DecisionType]}",
        ) from None

    # Create decision request
    request = DecisionRequest(
        workspace_id=body.workspace_id,
        scenario_id=body.scenario_id,
        recommendation_snapshot_id=body.recommendation_snapshot_id,
        selected_recommendation_id=body.selected_recommendation_id,
        decision_type=decision_type,
        reviewer_id=body.reviewer_id,
        rationale=body.rationale,
        modification_notes=body.modification_notes,
        tags=body.tags,
        metadata=body.metadata,
    )

    # Create service and execute
    service = DecisionService(db)
    result = await service.create_decision(request)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    decision = result.decision
    return DecisionRecordResponse(
        decision_id=decision.decision_id,
        workspace_id=decision.workspace_id,
        scenario_id=decision.scenario_id,
        recommendation_snapshot_id=decision.recommendation_snapshot_id,
        selected_recommendation_id=decision.selected_recommendation_id,
        decision_type=decision.decision_type.value,
        decision_status=decision.decision_status.value,
        reviewer_id=decision.reviewer_id,
        rationale=decision.rationale,
        modification_notes=decision.modification_notes,
        source_propagation_id=decision.source_propagation_id,
        source_signal_ids=decision.source_signal_ids,
        evidence_claim_ids=decision.evidence_claim_ids,
        graph_version=decision.graph_version,
        context_version=decision.context_version,
        feature_snapshot_version=decision.feature_snapshot_version,
        scenario_snapshot_version=decision.scenario_snapshot_version,
        recommendation_snapshot_version=decision.recommendation_snapshot_version,
        tags=decision.tags,
        metadata=decision.metadata,
        created_at=decision.created_at.isoformat(),
    )


@router.post("/decisions/{decision_id}/outcomes", response_model=OutcomeResponse)
async def append_outcome(
    decision_id: str,
    body: OutcomeRequestModel,
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> OutcomeResponse:
    """Append an outcome record to a decision.

    Outcomes record what happened after a decision was implemented.
    Multiple outcomes can be appended over time (append-only).

    Outcome types:
      - success: decision achieved desired outcome
      - partial_success: decision partially worked
      - failed: decision did not achieve desired outcome
      - no_impact: decision had no measurable effect
      - unintended_consequences: decision caused unexpected side effects
      - pending: outcome not yet determined
    """
    # Verify workspace access
    require_workspace_access(workspace_id, auth)

    # Validate outcome status
    try:
        outcome_status = OutcomeStatus(body.outcome_status)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown outcome_status: {body.outcome_status}. "
            f"Valid statuses: {[s.value for s in OutcomeStatus]}",
        ) from None

    # Create service and append outcome
    service = DecisionService(db)
    result = await service.append_outcome(
        decision_id=decision_id,
        workspace_id=workspace_id,
        outcome_status=outcome_status,
        outcome_summary=body.outcome_summary,
        recorded_by=body.recorded_by,
        actual_impact_description=body.actual_impact_description,
        actual_financial_impact=body.actual_financial_impact,
        actual_recovery_hours=body.actual_recovery_hours,
        actual_service_level_impact_pct=body.actual_service_level_impact_pct,
        met_expectations=body.met_expectations,
        would_decide_again=body.would_decide_again,
        metadata=body.metadata,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail="; ".join(result.warnings))

    outcome = result.outcome
    return OutcomeResponse(
        outcome_id=outcome.outcome_id,
        decision_id=outcome.decision_id,
        workspace_id=outcome.workspace_id,
        outcome_status=outcome.outcome_status.value,
        outcome_summary=outcome.outcome_summary,
        actual_impact_description=outcome.actual_impact_description,
        actual_financial_impact=outcome.actual_financial_impact,
        actual_recovery_hours=outcome.actual_recovery_hours,
        actual_service_level_impact_pct=outcome.actual_service_level_impact_pct,
        met_expectations=outcome.met_expectations,
        would_decide_again=outcome.would_decide_again,
        outcome_recorded_by=outcome.outcome_recorded_by,
        created_at=outcome.created_at.isoformat(),
        metadata=outcome.metadata,
    )


@router.post("/decisions/{decision_id}/lessons", response_model=LessonResponse)
async def append_lesson(
    decision_id: str,
    body: LessonRequestModel,
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> LessonResponse:
    """Append a lesson learned to a decision.

    Lessons capture structured learning from decisions and their outcomes.
    Multiple lessons can be appended per decision (append-only).

    Lesson categories:
      - policy_error: existing policy was incorrect
      - assumption_error: assumption proved wrong
      - data_quality_issue: data quality affected decision
      - model_bias: bias detected in reasoning
      - process_gap: process improvement needed
      - success_pattern: repeatable success pattern
      - best_practice: best practice to codify

    Mark should_export_for_training=true to include in ML export.
    """
    # Verify workspace access
    require_workspace_access(workspace_id, auth)

    # Validate lesson category
    try:
        category = LessonCategory(body.category)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown category: {body.category}. "
            f"Valid categories: {[c.value for c in LessonCategory]}",
        ) from None

    # Create service and append lesson
    service = DecisionService(db)
    result = await service.append_lesson(
        decision_id=decision_id,
        workspace_id=workspace_id,
        category=category,
        title=body.title,
        description=body.description,
        what_happened=body.what_happened,
        what_expected=body.what_expected,
        what_learned=body.what_learned,
        policy_or_assumption_wrong=body.policy_or_assumption_wrong,
        what_to_change_next_time=body.what_to_change_next_time,
        should_export_for_training=body.should_export_for_training,
        recorded_by=body.recorded_by,
        metadata=body.metadata,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail="; ".join(result.warnings))

    lesson = result.lesson
    return LessonResponse(
        lesson_id=lesson.lesson_id,
        decision_id=lesson.decision_id,
        outcome_id=lesson.outcome_id,
        workspace_id=lesson.workspace_id,
        category=lesson.category.value,
        title=lesson.title,
        description=lesson.description,
        what_happened=lesson.what_happened,
        what_expected=lesson.what_expected,
        what_learned=lesson.what_learned,
        policy_or_assumption_wrong=lesson.policy_or_assumption_wrong,
        what_to_change_next_time=lesson.what_to_change_next_time,
        should_export_for_training=lesson.should_export_for_training,
        recorded_by=lesson.recorded_by,
        created_at=lesson.created_at.isoformat(),
        metadata=lesson.metadata,
    )


@router.get("/decisions/{decision_id}", response_model=DecisionSnapshotResponse)
async def get_decision(
    decision_id: str,
    workspace_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> DecisionSnapshotResponse:
    """Get a complete decision snapshot with outcomes and lessons.

    Returns the full decision record including:
      - original decision details
      - all appended outcomes
      - all appended lessons
      - aggregate counts and timestamps

    This is the primary endpoint for viewing decision history.
    """
    # Verify workspace access
    require_workspace_access(workspace_id, auth)

    # Get service and fetch decision
    service = DecisionService(db)
    snapshot = await service.get_decision_snapshot(
        decision_id=decision_id,
        workspace_id=workspace_id,
    )

    if not snapshot:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision = snapshot.decision
    return DecisionSnapshotResponse(
        decision=DecisionRecordResponse(
            decision_id=decision.decision_id,
            workspace_id=decision.workspace_id,
            scenario_id=decision.scenario_id,
            recommendation_snapshot_id=decision.recommendation_snapshot_id,
            selected_recommendation_id=decision.selected_recommendation_id,
            decision_type=decision.decision_type.value,
            decision_status=decision.decision_status.value,
            reviewer_id=decision.reviewer_id,
            rationale=decision.rationale,
            modification_notes=decision.modification_notes,
            source_propagation_id=decision.source_propagation_id,
            source_signal_ids=decision.source_signal_ids,
            evidence_claim_ids=decision.evidence_claim_ids,
            graph_version=decision.graph_version,
            context_version=decision.context_version,
            feature_snapshot_version=decision.feature_snapshot_version,
            scenario_snapshot_version=decision.scenario_snapshot_version,
            recommendation_snapshot_version=decision.recommendation_snapshot_version,
            tags=decision.tags,
            metadata=decision.metadata,
            created_at=decision.created_at.isoformat(),
        ),
        outcomes=[
            OutcomeResponse(
                outcome_id=o.outcome_id,
                decision_id=o.decision_id,
                workspace_id=o.workspace_id,
                outcome_status=o.outcome_status.value,
                outcome_summary=o.outcome_summary,
                actual_impact_description=o.actual_impact_description,
                actual_financial_impact=o.actual_financial_impact,
                actual_recovery_hours=o.actual_recovery_hours,
                actual_service_level_impact_pct=o.actual_service_level_impact_pct,
                met_expectations=o.met_expectations,
                would_decide_again=o.would_decide_again,
                outcome_recorded_by=o.outcome_recorded_by,
                created_at=o.created_at.isoformat(),
                metadata=o.metadata,
            )
            for o in snapshot.outcomes
        ],
        lessons=[
            LessonResponse(
                lesson_id=lesson_var.lesson_id,
                decision_id=lesson_var.decision_id,
                outcome_id=lesson_var.outcome_id,
                workspace_id=lesson_var.workspace_id,
                category=lesson_var.category.value,
                title=lesson_var.title,
                description=lesson_var.description,
                what_happened=lesson_var.what_happened,
                what_expected=lesson_var.what_expected,
                what_learned=lesson_var.what_learned,
                policy_or_assumption_wrong=lesson_var.policy_or_assumption_wrong,
                what_to_change_next_time=lesson_var.what_to_change_next_time,
                should_export_for_training=lesson_var.should_export_for_training,
                recorded_by=lesson_var.recorded_by,
                created_at=lesson_var.created_at.isoformat(),
                metadata=lesson_var.metadata,
            )
            for lesson_var in snapshot.lessons
        ],
        outcome_count=snapshot.outcome_count,
        lesson_count=snapshot.lesson_count,
        last_outcome_at=snapshot.last_outcome_at.isoformat() if snapshot.last_outcome_at else None,
        last_lesson_at=snapshot.last_lesson_at.isoformat() if snapshot.last_lesson_at else None,
    )


@router.get("/decisions", response_model=list[DecisionRecordResponse])
async def list_decisions(
    workspace_id: str = Query(...),
    scenario_id: str | None = Query(None),
    reviewer_id: str | None = Query(None),
    decision_type: str | None = Query(None),
    decision_status: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[DecisionRecordResponse]:
    """List decisions with optional filtering.

    Filters:
      - scenario_id: filter by scenario
      - reviewer_id: filter by who made the decision
      - decision_type: filter by type of decision
      - decision_status: filter by status

    Returns decisions ordered by created_at descending (newest first).
    """
    # Verify workspace access
    require_workspace_access(workspace_id, auth)

    # Parse enums if provided
    parsed_decision_type = None
    if decision_type:
        try:
            parsed_decision_type = DecisionType(decision_type)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown decision_type: {decision_type}",
            ) from None

    parsed_decision_status = None
    if decision_status:
        try:
            parsed_decision_status = DecisionStatus(decision_status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown decision_status: {decision_status}",
            ) from None

    # Get service and list decisions
    service = DecisionService(db)
    decisions = await service.list_decisions(
        workspace_id=workspace_id,
        scenario_id=scenario_id,
        reviewer_id=reviewer_id,
        decision_type=parsed_decision_type,
        decision_status=parsed_decision_status,
        limit=limit,
        offset=offset,
    )

    return [
        DecisionRecordResponse(
            decision_id=d.decision_id,
            workspace_id=d.workspace_id,
            scenario_id=d.scenario_id,
            recommendation_snapshot_id=d.recommendation_snapshot_id,
            selected_recommendation_id=d.selected_recommendation_id,
            decision_type=d.decision_type.value,
            decision_status=d.decision_status.value,
            reviewer_id=d.reviewer_id,
            rationale=d.rationale,
            modification_notes=d.modification_notes,
            source_propagation_id=d.source_propagation_id,
            source_signal_ids=d.source_signal_ids,
            evidence_claim_ids=d.evidence_claim_ids,
            graph_version=d.graph_version,
            context_version=d.context_version,
            feature_snapshot_version=d.feature_snapshot_version,
            scenario_snapshot_version=d.scenario_snapshot_version,
            recommendation_snapshot_version=d.recommendation_snapshot_version,
            tags=d.tags,
            metadata=d.metadata,
            created_at=d.created_at.isoformat(),
        )
        for d in decisions
    ]


@router.get("/decisions/{decision_id}/export", response_model=DecisionExportResponse)
async def export_decision(
    decision_id: str,
    workspace_id: str = Query(...),
    anonymize: bool = Query(True, description="Whether to anonymize workspace ID"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> DecisionExportResponse:
    """Export a decision record for training/analysis.

    Exports a structured decision record suitable for ML training or analysis.
    Strips sensitive fields while preserving structural lineage.

    The export includes:
      - decision type and status
      - rationale (anonymized if requested)
      - scenario and recommendation types
      - graph metrics
      - outcome summary
      - exportable lessons (those marked should_export_for_training=true)

    Use anonymize=false only for internal analysis with proper authorization.
    """
    # Verify workspace access
    require_workspace_access(workspace_id, auth)

    # Get service and export decision
    service = DecisionService(db)
    export = await service.export_decision(
        decision_id=decision_id,
        workspace_id=workspace_id,
        anonymize=anonymize,
    )

    if not export:
        raise HTTPException(status_code=404, detail="Decision not found")

    return DecisionExportResponse(
        export_id=export.export_id,
        decision_id=export.decision_id,
        workspace_id=export.workspace_id,
        decision_type=export.decision_type.value,
        decision_status=export.decision_status.value,
        rationale=export.rationale,
        modification_notes=export.modification_notes,
        scenario_type=export.scenario_type,
        recommendation_type=export.recommendation_type,
        graph_metrics=export.graph_metrics,
        outcome_status=export.outcome_status.value if export.outcome_status else None,
        outcome_summary=export.outcome_summary,
        exportable_lessons=[
            LessonResponse(
                lesson_id=lesson_var.lesson_id,
                decision_id=lesson_var.decision_id,
                outcome_id=lesson_var.outcome_id,
                workspace_id=lesson_var.workspace_id,
                category=lesson_var.category.value,
                title=lesson_var.title,
                description=lesson_var.description,
                what_happened=lesson_var.what_happened,
                what_expected=lesson_var.what_expected,
                what_learned=lesson_var.what_learned,
                policy_or_assumption_wrong=lesson_var.policy_or_assumption_wrong,
                what_to_change_next_time=lesson_var.what_to_change_next_time,
                should_export_for_training=lesson_var.should_export_for_training,
                recorded_by=lesson_var.recorded_by,
                created_at=lesson_var.created_at.isoformat(),
                metadata=lesson_var.metadata,
            )
            for lesson_var in export.exportable_lessons
        ],
        exported_at=export.exported_at.isoformat(),
        export_version=export.export_version,
    )


@router.get("/decisions/taxonomy", response_model=dict[str, Any])
async def get_decision_taxonomy(
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the closed taxonomy of decision types.

    Returns all supported decision types with their specifications:
      - is_terminal: whether this decision type ends the workflow
      - is_reversible: whether this decision can be reversed
    """
    return {
        "taxonomy_version": "1.0.0",
        "decision_types": [
            {
                "type": dt.value,
                "name": dt.value.replace("_", " ").title(),
                "is_terminal": dt.is_terminal,
                "is_reversible": dt.is_reversible,
            }
            for dt in DecisionType
        ],
        "outcome_statuses": [s.value for s in OutcomeStatus],
        "lesson_categories": [c.value for c in LessonCategory],
    }
