"""Recommendation Service — orchestrates recommendation generation with snapshot loading.

The RecommendationService wires RecommendationEngine to existing engines
(FeatureEngine, OperationalStateEngine, SignalEngine, PropagationService,
ScenarioService) and produces RecommendationSnapshots.

This is the service layer consumed by API endpoints.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.common.ids import uuid7
from app.modules.graph.context_engine import OperationalStateEngine
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.feature_engine import FeatureEngine
from app.modules.graph.propagation_service import PropagationService
from app.modules.graph.recommendation_engine import RecommendationEngine
from app.modules.graph.recommendation_models import (
    RecommendationRequest,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.modules.graph.scenario_models import (
    ScenarioDefinition,
)
from app.modules.graph.scenario_models import (
    ScenarioRequest as ScenarioRequest,
)
from app.modules.graph.scenario_service import ScenarioService
from app.modules.graph.signal_engine import SignalEngine


@dataclass(frozen=True)
class RecommendationServiceResult:
    """Result of a recommendation service call."""

    result: RecommendationResult
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    signal_snapshot_version: int | None
    propagation_snapshot_version: int | None
    scenario_snapshot_version: int | None
    total_execution_time_ms: float
    warnings: list[str]


class RecommendationService:
    """Service layer that wires recommendation generation to existing engines.

    Usage:
        service = RecommendationService(
            feature_engine, context_engine, signal_engine,
            propagation_service, scenario_service, recommendation_engine
        )
        result = await service.generate_recommendations(
            workspace_id="ws-123",
            scenario_definition=scenario_def,
        )
    """

    def __init__(
        self,
        feature_engine: FeatureEngine,
        context_engine: OperationalStateEngine,
        signal_engine: SignalEngine,
        propagation_service: PropagationService,
        scenario_service: ScenarioService,
        recommendation_engine: RecommendationEngine,
    ) -> None:
        self._feature_engine = feature_engine
        self._context_engine = context_engine
        self._signal_engine = signal_engine
        self._propagation_service = propagation_service
        self._scenario_service = scenario_service
        self._recommendation_engine = recommendation_engine

    async def generate_recommendations(
        self,
        workspace_id: str,
        scenario_definition: ScenarioDefinition,
        *,
        source_propagation_id: str | None = None,
        source_signal_id: str | None = None,
        include_explanations: bool = True,
        include_trade_offs: bool = True,
        min_confidence: float = 0.0,
        max_recommendations: int | None = None,
        dry_run: bool = False,
        snapshot_version: int | None = None,
        scenario_snapshot_version: int | None = None,
    ) -> RecommendationServiceResult:
        """Generate recommendations for a scenario.

        Loads all required snapshots, executes scenario if needed,
        runs recommendation engine, returns full result.

        Args:
            workspace_id: Target workspace
            scenario_definition: Scenario to analyze
            source_propagation_id: Optional existing propagation ID
            source_signal_id: Optional source signal ID
            include_explanations: Whether to include explanations
            include_trade_offs: Whether to include trade-offs
            min_confidence: Minimum confidence threshold (0..1)
            max_recommendations: Maximum number of recommendations to return
            dry_run: If True, don't persist results
            snapshot_version: Optional pre-allocated DB-backed version for the
                recommendation snapshot. If None, the engine fallback (1) is
                used. API layer allocates monotonic versions via
                ``get_next_version(db, workspace_id, "recommendation")``.

        Returns:
            RecommendationServiceResult with full recommendation snapshot
        """
        start_time = time.perf_counter()
        warnings: list[str] = []

        # 1. Load features
        feature_result = await self._feature_engine.compute_features(
            workspace_id,
            use_cache=True,
        )

        # 2. Load operational context
        context_snapshot = None
        try:
            context_result = await self._context_engine.load_operational_state(workspace_id)
            context_snapshot = context_result.snapshot
        except Exception as e:
            warnings.append(f"Operational context load failed: {e}")

        # 3. Fuse feature + context
        enriched = EnrichedSnapshot.fuse(
            feature_result.snapshot,
            context_snapshot,
        )

        # 4. Detect signals
        signal_result = await self._signal_engine.detect_signals(
            workspace_id,
            use_feature_cache=True,
        )

        # 5. Run scenario
        scenario_result = await self._scenario_service.run_scenario(
            workspace_id=workspace_id,
            scenario_definition=scenario_definition,
            source_propagation_id=source_propagation_id,
            source_signal_id=source_signal_id,
            dry_run=dry_run,
            snapshot_version=scenario_snapshot_version,
        )

        if not scenario_result.result.success:
            return RecommendationServiceResult(
                result=RecommendationResult(
                    snapshot=RecommendationSnapshot(
                        recommendation_snapshot_id=f"rec-{uuid7()}",
                        workspace_id=workspace_id,
                        source_scenario_id=scenario_definition.scenario_id,
                        source_scenario_snapshot_version=None,
                        source_propagation_id=source_propagation_id,
                        source_propagation_snapshot_version=None,
                        source_signal_ids=[source_signal_id] if source_signal_id else [],
                        graph_version=None,
                        context_version=None,
                        feature_snapshot_version=None,
                        recommendations=[],
                        total_candidates_generated=0,
                        total_candidates_after_dedup=0,
                        scoring_version="1.0.0",
                        ranking_version="1.0.0",
                        execution_time_ms=0.0,
                        warnings=scenario_result.result.warnings,
                        error="Scenario execution failed",
                    ),
                    success=False,
                    warnings=scenario_result.result.warnings,
                ),
                feature_snapshot_version=feature_result.snapshot.snapshot_version,
                context_snapshot_version=context_snapshot.snapshot_version
                if context_snapshot
                else None,
                signal_snapshot_version=signal_result.snapshot.snapshot_version,
                propagation_snapshot_version=scenario_result.propagation_snapshot_version,
                scenario_snapshot_version=None,
                total_execution_time_ms=0.0,
                warnings=scenario_result.result.warnings,
            )

        scenario_snapshot = scenario_result.result.snapshot

        # 6. Generate recommendations
        # (propagation is embedded in scenario_snapshot, no separate load needed)
        request = RecommendationRequest(
            workspace_id=workspace_id,
            scenario_id=scenario_definition.scenario_id,
            scenario_snapshot_version=scenario_snapshot.scenario_snapshot_version,
            include_explanations=include_explanations,
            include_trade_offs=include_trade_offs,
            min_confidence=min_confidence,
            max_recommendations=max_recommendations,
            snapshot_version=snapshot_version,
        )

        recommendation_result = self._recommendation_engine.generate_recommendations(
            scenario_snapshot=scenario_snapshot,
            request=request,
            enriched_snapshot=enriched,
            signal_snapshot=signal_result.snapshot,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return RecommendationServiceResult(
            result=recommendation_result,
            feature_snapshot_version=feature_result.snapshot.snapshot_version,
            context_snapshot_version=context_snapshot.snapshot_version
            if context_snapshot
            else None,
            signal_snapshot_version=signal_result.snapshot.snapshot_version,
            propagation_snapshot_version=scenario_result.propagation_snapshot_version,
            scenario_snapshot_version=scenario_snapshot.scenario_snapshot_version,
            total_execution_time_ms=round(elapsed_ms, 2),
            warnings=warnings + scenario_result.warnings + recommendation_result.warnings,
        )

    async def get_recommendations_for_existing_scenario(
        self,
        workspace_id: str,
        scenario_id: str,
        scenario_snapshot_version: int | None = None,
        include_explanations: bool = True,
        include_trade_offs: bool = True,
        min_confidence: float = 0.0,
        max_recommendations: int | None = None,
    ) -> RecommendationServiceResult:
        """Generate recommendations for an existing scenario snapshot.

        This is used when the scenario has already been executed and
        we want to generate or regenerate recommendations.

        Args:
            workspace_id: Target workspace
            scenario_id: ID of existing scenario
            scenario_snapshot_version: Optional specific version
            include_explanations: Whether to include explanations
            include_trade_offs: Whether to include trade-offs
            min_confidence: Minimum confidence threshold
            max_recommendations: Maximum recommendations to return

        Returns:
            RecommendationServiceResult with recommendations
        """
        # In production, would load scenario snapshot from cache/store
        # For now, this is a placeholder that would need scenario storage
        warnings = ["Scenario snapshot loading not yet implemented"]

        return RecommendationServiceResult(
            result=RecommendationResult(
                snapshot=RecommendationSnapshot(
                    recommendation_snapshot_id=f"rec-{uuid7()}",
                    workspace_id=workspace_id,
                    source_scenario_id=scenario_id,
                    source_scenario_snapshot_version=scenario_snapshot_version,
                    source_propagation_id=None,
                    source_propagation_snapshot_version=None,
                    source_signal_ids=[],
                    graph_version=None,
                    context_version=None,
                    feature_snapshot_version=None,
                    recommendations=[],
                    total_candidates_generated=0,
                    total_candidates_after_dedup=0,
                    scoring_version="1.0.0",
                    ranking_version="1.0.0",
                    execution_time_ms=0.0,
                    warnings=warnings,
                ),
                success=False,
                warnings=warnings,
            ),
            feature_snapshot_version=None,
            context_snapshot_version=None,
            signal_snapshot_version=None,
            propagation_snapshot_version=None,
            scenario_snapshot_version=None,
            total_execution_time_ms=0.0,
            warnings=warnings,
        )
