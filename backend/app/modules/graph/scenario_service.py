"""Scenario Service — orchestrates scenario execution with snapshot loading.

The ScenarioService wires ScenarioEngine to existing engines (FeatureEngine,
OperationalStateEngine, SignalEngine, PropagationService) and produces
ScenarioSnapshots that Program G (Recommendations) consumes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.modules.graph.context_engine import OperationalStateEngine
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.feature_engine import FeatureEngine
from app.modules.graph.propagation_models import PropagationSnapshot
from app.modules.graph.propagation_service import PropagationService
from app.modules.graph.scenario_engine import ScenarioEngine
from app.modules.graph.scenario_models import (
    ScenarioDefinition,
    ScenarioRequest,
    ScenarioResult,
)
from app.modules.graph.signal_engine import SignalEngine


@dataclass(frozen=True)
class ScenarioServiceResult:
    """Result of a scenario service call."""

    result: ScenarioResult
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    signal_snapshot_version: int | None
    propagation_snapshot_version: int | None
    total_execution_time_ms: float
    warnings: list[str]


class ScenarioService:
    """Service layer that wires scenario execution to existing engines.

    Usage:
        service = ScenarioService(
            feature_engine, context_engine, signal_engine,
            propagation_service, scenario_engine
        )
        result = await service.run_scenario(
            workspace_id,
            scenario_definition,
            source_propagation_id="...",
        )
    """

    def __init__(
        self,
        feature_engine: FeatureEngine,
        context_engine: OperationalStateEngine,
        signal_engine: SignalEngine,
        propagation_service: PropagationService,
        scenario_engine: ScenarioEngine,
    ) -> None:
        self._feature_engine = feature_engine
        self._context_engine = context_engine
        self._signal_engine = signal_engine
        self._propagation_service = propagation_service
        self._scenario_engine = scenario_engine

    async def run_scenario(
        self,
        workspace_id: str,
        scenario_definition: ScenarioDefinition,
        *,
        source_propagation_id: str | None = None,
        source_signal_id: str | None = None,
        dry_run: bool = False,
        snapshot_version: int | None = None,
    ) -> ScenarioServiceResult:
        """Execute a scenario for a workspace.

        Loads all required snapshots, finds/creates propagation if needed,
        runs scenario engine, returns full result.

        Args:
            workspace_id: Target workspace
            scenario_definition: Scenario to execute
            source_propagation_id: Optional existing propagation ID
            source_signal_id: Optional source signal ID
            dry_run: If True, snapshot is not persisted
            snapshot_version: Optional pre-allocated DB-backed version.
                If None, the engine fallback (1) is used. API layer is
                responsible for allocating monotonic versions via
                ``get_next_version(db, workspace_id, "scenario")``.
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

        # 5. Get propagation (if source specified)
        propagation: PropagationSnapshot | None = None
        propagation_snapshot_version: int | None = None

        if source_propagation_id:
            # In production, would load from cache/store
            # For now, re-run propagation if we have source_signal_id
            if source_signal_id:
                prop_result = await self._propagation_service.run_propagation(
                    workspace_id=workspace_id,
                    source_signal_id=source_signal_id,
                    source_node_id=scenario_definition.parameters[0].value
                    if scenario_definition.parameters
                    else "",
                )
                if prop_result.result.success:
                    propagation = prop_result.result.snapshot
                    # PropagationSnapshot has no dedicated snapshot_version field;
                    # its provenance is anchored to the signal snapshot it ran
                    # against, so we surface that as the propagation's version.
                    propagation_snapshot_version = prop_result.signal_snapshot_version
                else:
                    warnings.append(f"Propagation failed: {prop_result.result.warnings}")
        elif source_signal_id:
            # No specific propagation ID, but have signal - run fresh propagation
            prop_result = await self._propagation_service.run_propagation(
                workspace_id=workspace_id,
                source_signal_id=source_signal_id,
                source_node_id=scenario_definition.parameters[0].value
                if scenario_definition.parameters
                else "",
            )
            if prop_result.result.success:
                propagation = prop_result.result.snapshot
                propagation_snapshot_version = prop_result.signal_snapshot_version

        # 6. Run scenario
        request = ScenarioRequest(
            workspace_id=workspace_id,
            scenario_definition=scenario_definition,
            source_propagation_id=source_propagation_id,
            source_signal_id=source_signal_id,
            dry_run=dry_run,
            snapshot_version=snapshot_version,
        )

        scenario_result = self._scenario_engine.execute_scenario(
            enriched=enriched,
            propagation=propagation,
            request=request,
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        return ScenarioServiceResult(
            result=scenario_result,
            feature_snapshot_version=feature_result.snapshot.snapshot_version,
            context_snapshot_version=context_snapshot.snapshot_version
            if context_snapshot
            else None,
            signal_snapshot_version=signal_result.snapshot.snapshot_version,
            propagation_snapshot_version=propagation_snapshot_version,
            total_execution_time_ms=round(elapsed_ms, 2),
            warnings=warnings + list(scenario_result.warnings),
        )
