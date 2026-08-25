"""SignalEngine — orchestrator that detects signals from enriched snapshots.

The engine:
  1. Loads the FeatureSnapshot for a workspace (via FeatureEngine)
  2. Loads the OperationalContextSnapshot (via OperationalStateEngine)
  3. Fuses both into EnrichedSnapshot (via ContextFusion)
  4. Iterates over all SignalDefinitions in the registry
  5. Calls the corresponding detector function for each definition
  6. Aggregates all detected signals
  7. Deduplicates by (signal_name, affected_node_ids) — keeps highest severity
  8. Returns a SignalSnapshot with metadata

The engine is stateless and deterministic. Same features + context → same signals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.modules.graph.context_engine import OperationalStateEngine, StateLoadResult
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.context_models import OperationalContextSnapshot
from app.modules.graph.detectors import get_detector
from app.modules.graph.feature_engine import FeatureComputationResult, FeatureEngine
from app.modules.graph.feature_models import FeatureSnapshot
from app.modules.graph.signal_models import SignalInstance, SignalSnapshot
from app.modules.graph.signal_registry import SIGNAL_REGISTRY


@dataclass(frozen=True)
class SignalComputationResult:
    """Return value from SignalEngine.detect_signals()."""

    snapshot: SignalSnapshot
    feature_cache_hit: bool
    context_cache_hit: bool
    computation_time_ms: float


class SignalEngine:
    """Detects operational signals from enriched graph features.

    Usage:
        engine = SignalEngine(feature_engine, context_engine)
        result = await engine.detect_signals(workspace_id)
        signals = result.snapshot.signals

    The engine depends only on FeatureEngine and OperationalStateEngine —
    never on the repository or graph directly. This keeps Programs D, E, F
    cleanly layered.
    """

    def __init__(
        self,
        feature_engine: FeatureEngine,
        context_engine: OperationalStateEngine,
    ) -> None:
        self._feature_engine = feature_engine
        self._context_engine = context_engine

    async def detect_signals(
        self,
        workspace_id: str,
        *,
        use_feature_cache: bool = True,
        use_context_cache: bool = True,
        signal_names: list[str] | None = None,  # None = all signals in registry
        require_fresh_context: bool = False,
    ) -> SignalComputationResult:
        """Detect all signals for a workspace.

        If signal_names is provided, only those signal types are computed.
        Otherwise, all signals in SIGNAL_REGISTRY are evaluated.

        If require_fresh_context is True, stale operational state is excluded.

        Returns SignalComputationResult(snapshot, feature_cache_hit, context_cache_hit, computation_time_ms).
        """
        start_time = time.perf_counter()

        # Load features
        feature_result: FeatureComputationResult = await self._feature_engine.compute_features(
            workspace_id, use_cache=use_feature_cache
        )
        features: FeatureSnapshot = feature_result.snapshot

        # Load operational context
        context_result: StateLoadResult | None = None
        context_snapshot: OperationalContextSnapshot | None = None
        context_cache_hit = False

        try:
            context_result = await self._context_engine.load_operational_state(
                workspace_id,
                require_freshness=require_fresh_context,
                use_cache=use_context_cache,
            )
            context_snapshot = context_result.snapshot
            # The engine signals a cache hit by appending
            # "context_cache_hit" to its warnings list.
            context_cache_hit = bool(context_result.warnings) and any(
                w == "context_cache_hit" for w in context_result.warnings
            )
        except Exception as exc:
            # Context loading is optional — continue with features only
            import logging

            logging.getLogger("cortex.signal_engine").exception(
                "Context loading failed; continuing with features only"
            )
            _ = exc

        # Fuse features + context
        enriched = EnrichedSnapshot.fuse(features, context_snapshot)

        # Determine which signals to compute
        signals_to_compute = (
            signal_names if signal_names is not None else list(SIGNAL_REGISTRY.keys())
        )

        # Detect signals
        all_signals: list[SignalInstance] = []
        for signal_name in signals_to_compute:
            defn = SIGNAL_REGISTRY.get(signal_name)
            if defn is None:
                continue
            detector = get_detector(signal_name)
            if detector is None:
                continue
            detected = detector(enriched, defn)
            all_signals.extend(detected)

        # Deduplicate: keep highest severity per (signal_name, node_id)
        deduped = _deduplicate_signals(all_signals)

        # Build snapshot
        snapshot = SignalSnapshot(
            workspace_id=workspace_id,
            snapshot_version=features.snapshot_version,
            snapshot_hash=features.snapshot_hash,
            signals=deduped,
            metadata={
                "signals_computed": len(signals_to_compute),
                "total_signals_detected": len(all_signals),
                "after_dedup": len(deduped),
                "feature_cache_hit": feature_result.cache_hit,
                "context_loaded": context_snapshot is not None,
                "context_nodes": len(context_snapshot.by_node) if context_snapshot else 0,
            },
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return SignalComputationResult(
            snapshot=snapshot,
            feature_cache_hit=feature_result.cache_hit,
            context_cache_hit=context_cache_hit,
            computation_time_ms=round(elapsed_ms, 2),
        )


def _deduplicate_signals(signals: list[SignalInstance]) -> list[SignalInstance]:
    """Deduplicate signals by (signal_name, node_id), keeping highest severity."""
    from collections import defaultdict

    # Group by (signal_name, node_id)
    grouped: dict[tuple[str, str], list[SignalInstance]] = defaultdict(list)
    for sig in signals:
        for node_id in sig.affected_node_ids:
            key = (sig.signal_name, node_id)
            grouped[key].append(sig)

    # Keep highest severity per group
    severity_order = {
        "info": 0,
        "warning": 1,
        "critical": 2,
        "blocking": 3,
    }
    deduped: list[SignalInstance] = []
    seen_keys: set[tuple[str, str]] = set()

    for key, sig_list in grouped.items():
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # Sort by severity descending, then confidence descending
        best = max(sig_list, key=lambda s: (severity_order.get(s.severity.value, 0), s.confidence))
        deduped.append(best)

    # Sort final list by severity (highest first), then signal_name
    deduped.sort(key=lambda s: (-severity_order.get(s.severity.value, 0), s.signal_name))

    return deduped
