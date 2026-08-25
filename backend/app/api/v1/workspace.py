"""Program S â€” Live Nexus Workspace REST Endpoints.

Provides complete REST access for:
- Data Ingestion & Live Multi-Table File Uploads
- Proportional Operational Graph Queries (Viewport subgraphs & Critical hubs)
- Live Anomaly Signals & Blast Radius Analytics
- Multi-Agent Decision Room Deliberation Triggers
- Digital Twin Counterfactual Comparisons & Decision Evidence Graphs
- Live Event Streaming & Graph Delta Inspections
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.common.context import ExecutionContext
from app.modules.data_intelligence.live_workspace import LiveNexusWorkspace

router = APIRouter(prefix="/workspace", tags=["Live Data Intelligence Workspace"])

# Global singleton in-memory workspace instance (can be per-tenant/workspace in production)
_workspace_instance = LiveNexusWorkspace(workspace_id="ws_default", organization_id="org_default")


class IngestRawRequest(BaseModel):
    table_name: str = Field(..., description="Table name (e.g. orders, sellers, customers, order_items)")
    csv_content: str = Field(..., description="Raw CSV content string")
    primary_key: str | None = Field(default=None)
    max_rows: int = Field(default=5000)


class StreamEventRequest(BaseModel):
    event_type: str = Field(..., description="e.g. ORDER_PLACED, SELLER_DEGRADATION")
    payload: dict[str, Any] = Field(..., description="Structured event payload")


class DeliberateRequest(BaseModel):
    incident_entity_id: str | None = Field(default=None, description="Target entity ID to investigate")


@router.get("/state")
async def get_workspace_state() -> dict[str, Any]:
    """Returns current workspace overview, loaded datasets, graph size, and active signals."""
    return _workspace_instance.get_state().to_dict()


@router.post("/demo/load")
async def load_demo_incident() -> dict[str, Any]:
    """Loads the canonical 6-minute controlled demo dataset into the live backend workspace."""
    demo_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "datasets_test", "demo")
    loaded = []

    table_files = [
        ("sellers", "sellers.csv", "seller_id"),
        ("orders", "orders.csv", "order_id"),
        ("routes", "routes.csv", "route_id"),
        ("products", "products.csv", "product_id"),
    ]

    for table_name, filename, pk in table_files:
        filepath = os.path.join(demo_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            res = _workspace_instance.ingest_csv_content(
                table_name=table_name,
                csv_text=content,
                primary_key=pk,
                max_rows=5000,
            )
            loaded.append({"table": table_name, "rows": res.get("ingested_rows", 0)})

    state = _workspace_instance.get_state().to_dict()
    return {
        "status": "SUCCESS",
        "loaded_tables": loaded,
        "workspace_state": state,
    }


@router.post("/ingest-raw")
async def ingest_raw_table(req: IngestRawRequest) -> dict[str, Any]:
    """Dynamically ingests raw CSV table and expands the operational graph proportionally."""
    try:
        res = _workspace_instance.ingest_csv_content(
            table_name=req.table_name,
            csv_text=req.csv_content,
            primary_key=req.primary_key,
            max_rows=req.max_rows,
        )
        return {"status": "SUCCESS", "result": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/upload")
async def upload_dataset_files(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Multi-table CSV upload endpoint."""
    results = []
    for f in files:
        contents = await f.read()
        text = contents.decode("utf-8", errors="replace")
        table_name = os.path.splitext(f.filename or "dataset")[0]
        res = _workspace_instance.ingest_csv_content(
            table_name=table_name,
            csv_text=text,
            max_rows=5000,
        )
        results.append(res)
    return {"status": "SUCCESS", "processed_files_count": len(results), "files": results}


@router.get("/graph/subgraph")
async def get_graph_subgraph(
    center_node_id: str | None = Query(None, description="Focal node ID for 2-hop ego-network"),
    max_hops: int = Query(2, ge=1, le=4),
    limit_nodes: int = Query(100, ge=10, le=500),
) -> dict[str, Any]:
    """Returns viewport-aware localized subgraph for high-performance canvas rendering."""
    return _workspace_instance.get_subgraph(
        center_node_id=center_node_id,
        max_hops=max_hops,
        limit_nodes=limit_nodes,
    )


@router.get("/graph/critical-nodes")
async def get_critical_nodes() -> dict[str, Any]:
    """Returns ranked list of Single Points of Failure (SPOFs) and top PageRank hubs."""
    analytics = _workspace_instance.graph_engine.compute_graph_analytics()
    return {
        "top_critical_suppliers": analytics.top_critical_suppliers,
        "top_critical_routes": analytics.top_critical_routes,
        "high_dependency_spofs": analytics.high_dependency_spofs,
        "supplier_concentration_gini": analytics.supplier_concentration_gini,
    }


@router.get("/signals")
async def get_active_signals() -> dict[str, Any]:
    """Returns detected operational anomaly signals and downstream blast radius exposure."""
    signals = [s.to_dict() for s in _workspace_instance.active_signals]
    blast_radius = None
    if _workspace_instance.active_signals:
        blast = _workspace_instance.root_cause_engine.analyze_blast_radius(_workspace_instance.active_signals[0])
        blast_radius = blast.to_dict()
    return {"active_signals": signals, "primary_blast_radius": blast_radius}


@router.post("/deliberate")
async def trigger_agent_deliberation(req: DeliberateRequest) -> dict[str, Any]:
    """Runs the live Multi-Agent Decision Room and counterfactual simulations."""
    ctx = ExecutionContext.create_system_context()
    res = await _workspace_instance.run_multi_agent_decision_room(
        incident_entity_id=req.incident_entity_id,
        context=ctx,
    )
    return {"status": "SUCCESS", "deliberation_result": res}


@router.get("/decisions/evidence")
async def get_decision_evidence(
    decision_id: str | None = Query(None, description="Decision to retrieve evidence for"),
) -> dict[str, Any]:
    """Returns the traversable Decision Evidence Graph with SHA-256 node hashes.

    When ``decision_id`` is provided the lookup is fail-closed: evidence is
    only ever returned if it belongs to exactly that decision — never to an
    unrelated earlier or later decision.
    """
    evidence = _workspace_instance.last_decision_evidence
    if not evidence:
        raise HTTPException(
            status_code=404,
            detail="No synthesized decision generated yet in this workspace.",
        )
    if decision_id is not None and str(evidence.get("decision_id")) != decision_id:
        raise HTTPException(
            status_code=404,
            detail=f"No evidence found for decision {decision_id!r} in this workspace.",
        )
    return evidence


@router.get("/decisions/validity")
async def get_decision_validity() -> dict[str, Any]:
    """Returns whether the latest decision is valid or invalidated by world state mutation."""
    target_id = getattr(_workspace_instance, "last_decision_id", "dec_live_01")
    is_valid = _workspace_instance.invalidation_engine.is_decision_valid(target_id)
    dep = _workspace_instance.invalidation_engine.decisions.get(target_id)
    return {
        "decision_id": target_id,
        "is_valid": is_valid,
        "invalidation_reason": dep.invalidation_reason if dep else None,
        "dependency_set": dep.to_dict() if dep else None,
    }


class AskQuestionRequest(BaseModel):
    query: str = Field(..., description="Operational natural language question")


@router.post("/query/ask")
async def ask_workspace_question(req: AskQuestionRequest) -> dict[str, Any]:
    """Natural-language data interrogation and evidence-backed answer generation."""
    res = _workspace_instance.ask_natural_language_question(req.query)
    return res


@router.get("/query/readiness")
async def check_query_readiness(query: str = Query(..., description="Query to evaluate answerability for")) -> dict[str, Any]:
    """Preflight answerability check answering 'Can I answer this?' before execution."""
    rep = _workspace_instance.query_engine.readiness_checker.evaluate_answerability(
        query_text=query,
        loaded_tables=_workspace_instance.datasets,
        graph_nodes_count=len(_workspace_instance.graph_engine.nodes),
    )
    return rep.to_dict()


@router.post("/append-stream")
async def append_stream_event(req: StreamEventRequest) -> dict[str, Any]:
    """Injects live streaming event to mutate the operational graph via GraphDeltaEngine."""
    delta = _workspace_instance.append_stream_event(req.event_type, req.payload)
    return {"status": "SUCCESS", "delta": delta.to_dict()}


@router.get("/graph/delta")
async def get_graph_deltas(since_version: str = Query("", description="Previous graph version")) -> dict[str, Any]:
    """Returns list of incremental graph deltas since specified graph version."""
    deltas = _workspace_instance.delta_engine.get_deltas_since(since_version)
    return {"deltas_count": len(deltas), "deltas": [d.to_dict() for d in deltas]}


@router.get("/stream")
async def stream_workspace_events(request: Request) -> StreamingResponse:
    """Server-Sent Events channel for live workspace reconciliation.

    Emits:
    - ``graph_delta``  — fired when the delta engine records new mutations
    - ``heartbeat``    — periodic authoritative versions + graph size, so
      clients can detect out-of-band changes (e.g. ingestion) and reconcile
      even when no delta event was recorded.
    """
    workspace = _workspace_instance

    async def event_stream() -> AsyncGenerator[str]:
        last_counter = workspace.delta_engine.current_version_counter
        while True:
            if await request.is_disconnected():
                break
            engine = workspace.delta_engine
            counter = engine.current_version_counter
            if counter != last_counter:
                last_counter = counter
                yield (
                    "event: graph_delta\n"
                    f"data: {json.dumps({
                        'type': 'graph_delta',
                        'graph_version': f'graph_v{counter}',
                        'world_state_version': workspace.world_state_version,
                    })}\n\n"
                )
            else:
                yield (
                    "event: heartbeat\n"
                    f"data: {json.dumps({
                        'type': 'heartbeat',
                        'graph_version': f'graph_v{counter}',
                        'world_state_version': workspace.world_state_version,
                        'total_graph_nodes': len(workspace.graph_engine.nodes),
                        'total_graph_edges': len(workspace.graph_engine.edges),
                    })}\n\n"
                )
            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
