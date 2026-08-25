"""Propagation Service — orchestrates propagation runs with snapshot loading.

The PropagationService is the only component that talks to FeatureEngine,
OperationalStateEngine, SignalEngine, and GraphService in one place. It
produces a PropagationSnapshot that downstream programs (F, G, H) consume
without re-deriving anything.

Responsibilities:
  1. Load FeatureSnapshot (via FeatureEngine)
  2. Load OperationalContextSnapshot (via OperationalStateEngine)
  3. Fuse into EnrichedSnapshot (via ContextFusion)
  4. Detect signals (via SignalEngine)
  5. Build InMemoryGraph (via GraphService)
  6. Run propagation (via PropagationEngine)
  7. Return PropagationResult

One-way pipeline: Signal Engine → Propagation Engine — never the reverse.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.modules.graph.context_engine import OperationalStateEngine
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.feature_engine import FeatureEngine
from app.modules.graph.propagation_engine import PropagationEngine
from app.modules.graph.propagation_models import (
    ImpactSummary,
    ImpactType,
    PropagationRequest,
    PropagationResult,
    PropagationSnapshot,
    PropagationTree,
    Severity,
)
from app.modules.graph.service import GraphService
from app.modules.graph.signal_engine import SignalEngine
from app.modules.graph.signal_models import SignalInstance


@dataclass(frozen=True)
class PropagationServiceResult:
    """Result of a propagation service call."""

    result: PropagationResult
    signal_snapshot_version: int | None
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    total_execution_time_ms: float
    warnings: list[str]


class PropagationService:
    """Service layer that wires propagation to existing engines.

    Usage:
        service = PropagationService(
            feature_engine, context_engine, signal_engine, graph_service
        )
        result = await service.run_propagation(
            workspace_id, source_signal_id, source_node_id,
        )
    """

    def __init__(
        self,
        feature_engine: FeatureEngine,
        context_engine: OperationalStateEngine,
        signal_engine: SignalEngine,
        graph_service: GraphService,
        *,
        propagation_engine: PropagationEngine | None = None,
    ) -> None:
        self._feature_engine = feature_engine
        self._context_engine = context_engine
        self._signal_engine = signal_engine
        self._graph_service = graph_service
        self._propagation_engine = propagation_engine or PropagationEngine()

    async def run_propagation(
        self,
        workspace_id: str,
        source_signal_id: str,
        source_node_id: str,
        *,
        max_depth: int = 5,
        min_confidence: float = 0.1,
        impact_type_filter: ImpactType | None = None,
    ) -> PropagationServiceResult:
        """Run propagation from a signal in a workspace.

        Loads all required snapshots, finds the signal, runs propagation,
        and returns the result with audit metadata.
        """
        start = time.perf_counter()
        warnings: list[str] = []

        # 1. Load features
        feature_result = await self._feature_engine.compute_features(workspace_id, use_cache=True)

        # 2. Load operational context
        try:
            context_result = await self._context_engine.load_operational_state(workspace_id)
            context_snapshot = context_result.snapshot
        except Exception as e:
            context_snapshot = None
            warnings.append(f"Operational context load failed: {e}")

        # 3. Fuse
        enriched = EnrichedSnapshot.fuse(feature_result.snapshot, context_snapshot)

        # 4. Detect signals
        signal_result = await self._signal_engine.detect_signals(
            workspace_id, use_feature_cache=True
        )

        # Find the target signal
        target_signal: SignalInstance | None = None
        for sig in signal_result.snapshot.signals:
            if sig.signal_id == source_signal_id:
                target_signal = sig
                break

        if target_signal is None:
            return PropagationServiceResult(
                result=PropagationResult(
                    snapshot=_empty(),
                    success=False,
                    warnings=[f"Signal {source_signal_id} not found in workspace {workspace_id}"],
                ),
                signal_snapshot_version=signal_result.snapshot.snapshot_version,
                feature_snapshot_version=feature_result.snapshot.snapshot_version,
                context_snapshot_version=context_snapshot.snapshot_version
                if context_snapshot
                else None,
                total_execution_time_ms=round((time.perf_counter() - start) * 1000, 2),
                warnings=warnings,
            )

        # 5. Build InMemoryGraph
        workspace_graph = await self._graph_service.load_workspace_graph(workspace_id)
        graph = workspace_graph.graph

        # 6. Run propagation
        request = PropagationRequest(
            workspace_id=workspace_id,
            source_signal_id=source_signal_id,
            source_node_id=source_node_id,
            max_depth=max_depth,
            min_confidence=min_confidence,
            impact_type_filter=impact_type_filter,
        )

        propagation_result = self._propagation_engine.propagate(
            signal=target_signal,
            enriched=enriched,
            graph=graph,
            request=request,
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return PropagationServiceResult(
            result=propagation_result,
            signal_snapshot_version=signal_result.snapshot.snapshot_version,
            feature_snapshot_version=feature_result.snapshot.snapshot_version,
            context_snapshot_version=context_snapshot.snapshot_version
            if context_snapshot
            else None,
            total_execution_time_ms=round(elapsed_ms, 2),
            warnings=warnings + list(propagation_result.warnings),
        )


def _empty() -> PropagationSnapshot:
    """Build a minimal empty PropagationSnapshot.

    Placeholder until UUID7 generation is wired properly below.
    """
    from app.common.ids import uuid7

    return PropagationSnapshot(
        propagation_id=str(uuid7()),
        workspace_id="",
        source_signal_id="",
        source_signal_name="",
        source_node_id="",
        source_node_type="",
        source_severity=Severity.INFO,
        source_confidence=0.0,
        graph_version=None,
        feature_snapshot_version=None,
        context_snapshot_version=None,
        signal_snapshot_version=None,
        tree=PropagationTree(
            propagation_id="",
            source_signal_id="",
            source_node_id="",
            source_node_type="",
            steps=[],
        ),
        affected_entities=[],
        summary=ImpactSummary(total_affected=0),
        affected_facilities=[],
        affected_inventory=[],
        affected_orders=[],
        affected_customers=[],
        execution_time_ms=0.0,
        max_depth_reached=0,
        rules_applied=[],
    )
