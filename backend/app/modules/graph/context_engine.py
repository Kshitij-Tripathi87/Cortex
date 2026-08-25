"""Operational State Engine — loads, merges, and validates enterprise operational data.

The OperationalStateEngine:
  1. Loads operational state from repositories (ERP, WMS, TMS, MES data)
  2. Merges multiple sources for the same node (with conflict resolution)
  3. Validates freshness against policies
  4. Computes confidence scores based on source reliability and freshness
  5. Returns an immutable OperationalContextSnapshot

The engine NEVER performs graph reasoning — it only loads and validates
operational data. Graph features are loaded separately by FeatureEngine.

Downstream engines (Signal, Propagation, Scenario) consume the snapshot.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base
from app.modules.graph.context_models import (
    BusinessOperationalState,
    FreshnessPolicy,
    InventoryOperationalState,
    LogisticsOperationalState,
    NodeOperationalState,
    OperationalContextSnapshot,
    OrderOperationalState,
    ProductionOperationalState,
)


class ContextCache(Protocol):
    """Async cache for ``OperationalContextSnapshot`` keyed by workspace.

    Implementations must be safe to share across requests. The cache stores
    the full frozen snapshot; the ``OperationalStateEngine`` is responsible
    for invalidating it when new operational state is ingested.
    """

    async def get(self, workspace_id: str) -> OperationalContextSnapshot | None: ...
    async def set(
        self,
        workspace_id: str,
        snapshot: OperationalContextSnapshot,
        ttl: int = 3600,
    ) -> None: ...
    async def invalidate(self, workspace_id: str) -> None: ...


class NoOpContextCache:
    """Default context cache — does nothing. Use in tests and dev."""

    async def get(self, workspace_id: str) -> OperationalContextSnapshot | None:
        return None

    async def set(
        self,
        workspace_id: str,
        snapshot: OperationalContextSnapshot,
        ttl: int = 3600,
    ) -> None:
        pass

    async def invalidate(self, workspace_id: str) -> None:
        pass


class RedisContextCache:
    """Redis-backed context cache for staging/prod.

    Stores the ``OperationalContextSnapshot`` as JSON under
    ``cortex:context:{workspace_id}``. Handles serialization of the
    frozen dataclass via its ``__dict__``.
    """

    KEY_PREFIX = "cortex:context"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def _key(self, workspace_id: str) -> str:
        return f"{self.KEY_PREFIX}:{workspace_id}"

    async def get(self, workspace_id: str) -> OperationalContextSnapshot | None:
        raw = await self._redis.get(self._key(workspace_id))
        if raw is None:
            return None
        return _context_snapshot_from_dict(json.loads(raw))

    async def set(
        self,
        workspace_id: str,
        snapshot: OperationalContextSnapshot,
        ttl: int = 3600,
    ) -> None:
        await self._redis.set(
            self._key(workspace_id),
            json.dumps(_context_snapshot_to_dict(snapshot), default=str),
            ex=ttl,
        )

    async def invalidate(self, workspace_id: str) -> None:
        await self._redis.delete(self._key(workspace_id))


def _context_snapshot_to_dict(
    snapshot: OperationalContextSnapshot,
) -> dict[str, Any]:
    """Serialize an ``OperationalContextSnapshot`` to a plain dict."""
    return {
        "workspace_id": snapshot.workspace_id,
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_version": snapshot.snapshot_version,
        "snapshot_hash": snapshot.snapshot_hash,
        "by_node": {nid: _state_to_dict(s) for nid, s in snapshot.by_node.items()},
        "total_inventory_value": snapshot.total_inventory_value,
        "total_open_orders": snapshot.total_open_orders,
        "total_shipments_in_transit": snapshot.total_shipments_in_transit,
        "avg_utilization_pct": snapshot.avg_utilization_pct,
        "timestamp": snapshot.timestamp.isoformat() if snapshot.timestamp else None,
        "metadata": dict(snapshot.metadata),
    }


def _state_to_dict(state: NodeOperationalState) -> dict[str, Any]:
    """Serialize a node operational state to a plain dict.

    Uses ``dataclasses.asdict`` to recursively convert nested frozen
    dataclasses (``FreshnessPolicy``, ``Provenance``) to dicts.
    """
    from dataclasses import asdict, is_dataclass

    data: dict[str, Any] = {"_type": type(state).__name__}
    if is_dataclass(state):
        for k, v in asdict(state).items():
            if isinstance(v, dict):
                data[k] = {"_dataclass": True, **_jsonify(v)}
            elif isinstance(v, list):
                data[k] = [_jsonify(x) for x in v]
            elif isinstance(v, datetime):
                data[k] = v.isoformat()
            else:
                data[k] = v
    return data


def _jsonify(value: Any) -> Any:
    """Recursively JSON-ify a value for cache storage."""
    from dataclasses import asdict, is_dataclass

    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonify(x) for x in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {"_dataclass": True, **_jsonify(asdict(value))}
    return value


def _context_snapshot_from_dict(
    data: dict[str, Any],
) -> OperationalContextSnapshot:
    """Reconstruct an ``OperationalContextSnapshot`` from a dict."""
    by_node: dict[str, NodeOperationalState] = {}
    for nid, sdata in (data.get("by_node") or {}).items():
        state = _state_from_dict(sdata)
        if state is not None:
            by_node[nid] = state

    timestamp_str = data.get("timestamp")
    timestamp = datetime.fromisoformat(timestamp_str) if timestamp_str else None

    return OperationalContextSnapshot(
        workspace_id=data["workspace_id"],
        snapshot_id=data.get("snapshot_id"),
        snapshot_version=data.get("snapshot_version"),
        snapshot_hash=data.get("snapshot_hash"),
        by_node=by_node,
        total_inventory_value=data.get("total_inventory_value"),
        total_open_orders=data.get("total_open_orders"),
        total_shipments_in_transit=data.get("total_shipments_in_transit"),
        avg_utilization_pct=data.get("avg_utilization_pct"),
        timestamp=timestamp,
        metadata=dict(data.get("metadata") or {}),
    )


def _state_from_dict(data: dict[str, Any]) -> NodeOperationalState | None:
    """Reconstruct a typed ``NodeOperationalState`` subclass by name."""
    from app.modules.graph.context_models import (
        BusinessOperationalState as _B,
    )
    from app.modules.graph.context_models import (
        FreshnessPolicy as _FP,
    )
    from app.modules.graph.context_models import (
        InventoryOperationalState as _I,
    )
    from app.modules.graph.context_models import (
        LogisticsOperationalState as _L,
    )
    from app.modules.graph.context_models import (
        OrderOperationalState as _O,
    )
    from app.modules.graph.context_models import (
        ProductionOperationalState as _P,
    )
    from app.modules.graph.context_models import (
        Provenance as _Prov,
    )

    state_type = data.get("_type")
    cls_by_name = {
        "BusinessOperationalState": _B,
        "InventoryOperationalState": _I,
        "LogisticsOperationalState": _L,
        "OrderOperationalState": _O,
        "ProductionOperationalState": _P,
    }
    cls = cls_by_name.get(state_type) if isinstance(state_type, str) else None
    if cls is None:
        return None

    fields: dict[str, Any] = {}
    for k, v in data.items():
        if k == "_type":
            continue
        fields[k] = _reconstruct_field(k, v, _FP, _Prov)

    try:
        return cls(**fields)  # type: ignore[arg-type]
    except TypeError:
        return None


def _reconstruct_field(
    name: str,
    value: Any,
    freshness_cls: type,
    provenance_cls: type,
) -> Any:
    """Reconstruct nested dataclasses (``FreshnessPolicy``/``Provenance``)
    and ISO datetime strings back to their typed values."""
    if isinstance(value, str) and (name.endswith("_at") or name == "timestamp"):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, dict) and value.get("_dataclass") is True:
        clean = {k: v for k, v in value.items() if k != "_dataclass"}
        # Map known nested classes by field name + payload shape.
        if name == "freshness_policy":
            return _build_freshness_policy(clean, freshness_cls)
        if name == "provenance":
            return _build_provenance(clean, provenance_cls)
        # Unknown nested dataclass — return as plain dict.
        return clean
    return value


def _build_freshness_policy(
    clean: dict[str, Any],
    freshness_cls: type,
) -> Any:
    """Reconstruct a ``FreshnessPolicy`` from a clean dict."""
    try:
        return freshness_cls(**clean)
    except TypeError:
        return clean


def _build_provenance(
    clean: dict[str, Any],
    provenance_cls: type,
) -> Any:
    """Reconstruct a ``Provenance`` from a clean dict (rehydrating timestamps)."""
    for k in ("extracted_at", "transformed_at", "loaded_at"):
        v = clean.get(k)
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                clean[k] = datetime.fromisoformat(v)
    try:
        return provenance_cls(**clean)
    except TypeError:
        return clean


def create_context_cache(settings: Any | None = None) -> ContextCache:
    """Create appropriate context cache based on configuration.

    Returns ``RedisContextCache`` if Redis is configured, ``NoOpContextCache``
    otherwise.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    if not getattr(settings, "redis_url", None):
        return NoOpContextCache()

    try:
        from app.infrastructure.redis_client import get_redis_client

        redis_client = get_redis_client(settings)
        return RedisContextCache(redis_client)
    except Exception:
        # Redis unavailable, fall back to NoOp
        return NoOpContextCache()


class OperationalStateRepository(Protocol):
    """Protocol for loading operational state from data sources."""

    async def load_inventory_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> InventoryOperationalState | None:
        """Load inventory state for a node."""
        ...

    async def load_order_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> OrderOperationalState | None:
        """Load order state for a node."""
        ...

    async def load_logistics_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> LogisticsOperationalState | None:
        """Load logistics state for a node."""
        ...

    async def load_production_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> ProductionOperationalState | None:
        """Load production state for a node."""
        ...

    async def load_business_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> BusinessOperationalState | None:
        """Load business state for a node."""
        ...

    async def list_node_ids(self, workspace_id: str) -> list[str]:
        """List all node IDs with operational state in a workspace."""
        ...


@dataclass(frozen=True)
class StateLoadResult:
    """Result of loading operational state for a workspace."""

    snapshot: OperationalContextSnapshot
    load_time_ms: float
    nodes_loaded: int
    nodes_stale: int
    nodes_missing: int
    warnings: list[str]


class OperationalStateEngine:
    """Loads and validates operational state for a workspace.

    Usage:
        engine = OperationalStateEngine(repository)
        result = await engine.load_operational_state(workspace_id)
        snapshot = result.snapshot

    The engine is stateless and deterministic. Same data → same snapshot.

    An optional ``context_cache`` may be provided. When present, the engine
    caches the loaded ``OperationalContextSnapshot`` per workspace so
    repeated signal/propagation runs within a request avoid re-loading
    state from the repository. Cache should be invalidated when new
    operational state is ingested (e.g., on a new compile).
    """

    def __init__(
        self,
        repository: OperationalStateRepository,
        *,
        default_freshness_policies: dict[str, FreshnessPolicy] | None = None,
        context_cache: ContextCache | None = None,
    ) -> None:
        self._repository = repository
        self._default_policies = default_freshness_policies or _default_policies()
        self._context_cache = context_cache

    async def load_operational_state(
        self,
        workspace_id: str,
        *,
        as_of: datetime | None = None,
        require_freshness: bool = False,
        use_cache: bool = True,
    ) -> StateLoadResult:
        """Load operational state for all nodes in a workspace.

        If require_freshness is True, stale nodes are excluded and warnings raised.

        If a ``context_cache`` was supplied and ``use_cache=True``, the engine
        first checks the cache for a valid ``OperationalContextSnapshot`` for
        this workspace. Cache hits skip the repository load entirely.

        Note: ``require_freshness=True`` forces a cache bypass — stale cached
        state would defeat the freshness guarantee.
        """
        start_time = time.perf_counter()
        as_of = as_of or datetime.now(UTC)

        # Cache fast-path: only when freshness is not required
        if use_cache and not require_freshness and self._context_cache is not None:
            cached = await self._context_cache.get(workspace_id)
            if cached is not None:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return StateLoadResult(
                    snapshot=cached,
                    load_time_ms=round(elapsed_ms, 2),
                    nodes_loaded=len(cached.by_node),
                    nodes_stale=0,
                    nodes_missing=0,
                    warnings=["context_cache_hit"],
                )

        # Get all node IDs
        node_ids = await self._repository.list_node_ids(workspace_id)

        # Load state for each node
        by_node: dict[str, NodeOperationalState] = {}
        nodes_stale = 0
        nodes_missing = 0
        warnings: list[str] = []

        for node_id in node_ids:
            # Try loading each state type (first non-None wins)
            state: NodeOperationalState | None = None

            inventory = await self._repository.load_inventory_state(workspace_id, node_id)
            if inventory is not None:
                state = inventory

            if state is None:
                orders = await self._repository.load_order_state(workspace_id, node_id)
                if orders is not None:
                    state = orders

            if state is None:
                logistics = await self._repository.load_logistics_state(workspace_id, node_id)
                if logistics is not None:
                    state = logistics

            if state is None:
                production = await self._repository.load_production_state(workspace_id, node_id)
                if production is not None:
                    state = production

            if state is None:
                business = await self._repository.load_business_state(workspace_id, node_id)
                if business is not None:
                    state = business

            if state is None:
                nodes_missing += 1
                continue

            # Check freshness
            if require_freshness and state.is_stale(as_of):
                nodes_stale += 1
                warnings.append(
                    f"Node {node_id}: operational state is stale "
                    f"(age={state.freshness_seconds:.0f}s, "
                    f"source={state.source})"
                )
                continue

            # Apply default freshness policy if not set
            if state.freshness_policy is None:
                policy = self._default_policies.get(state.entity_type)
                if policy is not None:
                    # Create new state with policy (frozen, so use replace)
                    state = _replace_freshness_policy(state, policy)

            by_node[node_id] = state

        # Compute aggregates
        total_inventory_value = _compute_inventory_value(by_node)
        total_open_orders = _compute_open_orders(by_node)
        total_shipments = _compute_shipments_in_transit(by_node)
        avg_utilization = _compute_avg_utilization(by_node)

        # Build snapshot
        # Get latest snapshot version from repository
        snapshot_version = await self._repository.get_next_snapshot_version(workspace_id)
        snapshot_hash = _compute_snapshot_hash(by_node, snapshot_version)

        snapshot = OperationalContextSnapshot(
            workspace_id=workspace_id,
            snapshot_id=None,
            snapshot_version=snapshot_version,
            snapshot_hash=snapshot_hash,
            by_node=by_node,
            total_inventory_value=total_inventory_value,
            total_open_orders=total_open_orders,
            total_shipments_in_transit=total_shipments,
            avg_utilization_pct=avg_utilization,
            timestamp=as_of,
            metadata={
                "nodes_loaded": len(by_node),
                "nodes_stale": nodes_stale,
                "nodes_missing": nodes_missing,
                "require_freshness": require_freshness,
            },
        )

        # Populate cache (if configured) so subsequent loads skip the repository.
        # We don't cache when freshness is required — stale cached state would
        # defeat the purpose of require_freshness=True.
        if use_cache and not require_freshness and self._context_cache is not None:
            await self._context_cache.set(workspace_id, snapshot)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        return StateLoadResult(
            snapshot=snapshot,
            load_time_ms=round(elapsed_ms, 2),
            nodes_loaded=len(by_node),
            nodes_stale=nodes_stale,
            nodes_missing=nodes_missing,
            warnings=warnings,
        )

    async def invalidate_context_cache(self, workspace_id: str) -> None:
        """Invalidate cached operational state for a workspace.

        Call this when new operational state is ingested (e.g., a new
        compile) so subsequent reads reload from the repository.
        """
        if self._context_cache is not None:
            await self._context_cache.invalidate(workspace_id)


def _default_policies() -> dict[str, FreshnessPolicy]:
    """Default freshness policies by entity type."""
    return {
        "Part": FreshnessPolicy(
            max_age_seconds=86400,  # 24h
            degraded_age_seconds=43200,  # 12h
            stale_age_seconds=172800,  # 48h
            expiration_policy="degrade",
            required_for_signal=False,
        ),
        "Product": FreshnessPolicy(
            max_age_seconds=86400,
            degraded_age_seconds=43200,
            stale_age_seconds=172800,
            expiration_policy="degrade",
            required_for_signal=False,
        ),
        "PurchaseOrder": FreshnessPolicy(
            max_age_seconds=21600,  # 6h
            degraded_age_seconds=10800,  # 3h
            stale_age_seconds=43200,  # 12h
            expiration_policy="block",
            required_for_signal=True,
        ),
        "Shipment": FreshnessPolicy(
            max_age_seconds=21600,  # 6h
            degraded_age_seconds=10800,
            stale_age_seconds=86400,  # 24h
            expiration_policy="degrade",
            required_for_signal=False,
        ),
        "Facility": FreshnessPolicy(
            max_age_seconds=43200,  # 12h
            degraded_age_seconds=21600,  # 6h
            stale_age_seconds=86400,  # 24h
            expiration_policy="degrade",
            required_for_signal=False,
        ),
        "Customer": FreshnessPolicy(
            max_age_seconds=86400,  # 24h
            degraded_age_seconds=43200,
            stale_age_seconds=604800,  # 7 days
            expiration_policy="ignore",
            required_for_signal=False,
        ),
        "Supplier": FreshnessPolicy(
            max_age_seconds=86400,
            degraded_age_seconds=43200,
            stale_age_seconds=604800,
            expiration_policy="ignore",
            required_for_signal=False,
        ),
    }


def _replace_freshness_policy(
    state: NodeOperationalState,
    policy: FreshnessPolicy,
) -> NodeOperationalState:
    """Create a new state with updated freshness policy (frozen dataclass)."""
    return state.__class__(
        node_id=state.node_id,
        entity_id=state.entity_id,
        entity_type=state.entity_type,
        **{
            k: v
            for k, v in state.__dict__.items()
            if k not in ("node_id", "entity_id", "entity_type", "freshness_policy")
        },
        freshness_policy=policy,
    )


def _compute_inventory_value(by_node: dict[str, NodeOperationalState]) -> float | None:
    """Compute total inventory value across all nodes."""
    total = 0.0
    found = False
    for state in by_node.values():
        if isinstance(state, InventoryOperationalState) and state.on_hand_units is not None:
            # TODO: multiply by unit cost when available
            total += state.on_hand_units
            found = True
    return total if found else None


def _compute_open_orders(by_node: dict[str, NodeOperationalState]) -> int | None:
    """Compute total open orders across all nodes."""
    total = 0
    found = False
    for state in by_node.values():
        if isinstance(state, OrderOperationalState) and state.open_orders_count is not None:
            total += state.open_orders_count
            found = True
    return total if found else None


def _compute_shipments_in_transit(by_node: dict[str, NodeOperationalState]) -> int | None:
    """Compute total shipments in transit."""
    total = 0
    found = False
    for state in by_node.values():
        if isinstance(state, LogisticsOperationalState) and state.shipments_in_transit is not None:
            total += state.shipments_in_transit
            found = True
    return total if found else None


def _compute_avg_utilization(by_node: dict[str, NodeOperationalState]) -> float | None:
    """Compute average utilization across production nodes."""
    values: list[float] = []
    for state in by_node.values():
        if isinstance(state, ProductionOperationalState) and state.utilization_pct is not None:
            values.append(state.utilization_pct)
    return sum(values) / len(values) if values else None


def _compute_snapshot_hash(
    by_node: dict[str, NodeOperationalState],
    version: int,
) -> str:
    """Compute deterministic hash of operational state snapshot."""
    # Sort by node_id for determinism
    items = sorted(by_node.items())
    hasher = hashlib.sha256()
    hasher.update(f"v{version}".encode())
    for node_id, state in items:
        hasher.update(node_id.encode())
        hasher.update(state.entity_id.encode())
        hasher.update(state.entity_type.encode())
        hasher.update(state.timestamp.isoformat().encode())
        hasher.update(f"{state.confidence}".encode())
    return hasher.hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Repository (for testing and development)
# ─────────────────────────────────────────────────────────────────────────────


class InMemoryOperationalStateRepository:
    """In-memory implementation of OperationalStateRepository for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, NodeOperationalState]] = {}

    def add_state(
        self,
        workspace_id: str,
        node_id: str,
        state: NodeOperationalState,
    ) -> None:
        """Add operational state for a node."""
        if workspace_id not in self._data:
            self._data[workspace_id] = {}
        self._data[workspace_id][node_id] = state

    async def load_inventory_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> InventoryOperationalState | None:
        state = self._data.get(workspace_id, {}).get(node_id)
        if isinstance(state, InventoryOperationalState):
            return state
        return None

    async def load_order_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> OrderOperationalState | None:
        state = self._data.get(workspace_id, {}).get(node_id)
        if isinstance(state, OrderOperationalState):
            return state
        return None

    async def load_logistics_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> LogisticsOperationalState | None:
        state = self._data.get(workspace_id, {}).get(node_id)
        if isinstance(state, LogisticsOperationalState):
            return state
        return None

    async def load_production_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> ProductionOperationalState | None:
        state = self._data.get(workspace_id, {}).get(node_id)
        if isinstance(state, ProductionOperationalState):
            return state
        return None

    async def load_business_state(
        self,
        workspace_id: str,
        node_id: str,
    ) -> BusinessOperationalState | None:
        state = self._data.get(workspace_id, {}).get(node_id)
        if isinstance(state, BusinessOperationalState):
            return state
        return None

    async def list_node_ids(self, workspace_id: str) -> list[str]:
        return list(self._data.get(workspace_id, {}).keys())

    async def get_next_snapshot_version(self, workspace_id: str) -> int:
        """Get the next snapshot version number for a workspace.

        Returns the highest version + 1, or 1 if no snapshots exist.
        """
        # For in-memory, just return 1 as there's no persistent snapshot tracking
        return 1


class OperationalStateRecord(Base):
    """Persisted operational state payload for a workspace/node pair."""

    __tablename__ = "operational_state_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "node_id", name="uq_operational_state_workspace_node"),
    )

    record_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    state_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SqlOperationalStateRepository:
    """SQL-backed operational-state repository used by API request paths."""

    def __init__(self, db: AsyncSession, context_cache: ContextCache | None = None) -> None:
        self._db = db
        self._context_cache = context_cache

    async def upsert_state(self, workspace_id: str, state: NodeOperationalState) -> None:
        stmt = select(OperationalStateRecord).where(
            OperationalStateRecord.workspace_id == workspace_id,
            OperationalStateRecord.node_id == state.node_id,
        )
        record = (await self._db.execute(stmt)).scalar_one_or_none()
        state_data = json.loads(json.dumps(_state_to_dict(state), default=str))
        if record is None:
            self._db.add(
                OperationalStateRecord(
                    workspace_id=workspace_id,
                    node_id=state.node_id,
                    state_type=type(state).__name__,
                    state_data=state_data,
                    observed_at=state.timestamp,
                )
            )
        else:
            record.state_type = type(state).__name__
            record.state_data = state_data
            record.observed_at = state.timestamp
        await self._db.flush()
        if self._context_cache is not None:
            await self._context_cache.invalidate(workspace_id)

    async def _load(self, workspace_id: str, node_id: str, expected: type) -> Any | None:
        stmt = select(OperationalStateRecord).where(
            OperationalStateRecord.workspace_id == workspace_id,
            OperationalStateRecord.node_id == node_id,
        )
        record = (await self._db.execute(stmt)).scalar_one_or_none()
        if record is None or record.state_type != expected.__name__:
            return None
        return _state_from_dict(record.state_data)

    async def load_inventory_state(
        self, workspace_id: str, node_id: str
    ) -> InventoryOperationalState | None:
        return await self._load(workspace_id, node_id, InventoryOperationalState)

    async def load_order_state(
        self, workspace_id: str, node_id: str
    ) -> OrderOperationalState | None:
        return await self._load(workspace_id, node_id, OrderOperationalState)

    async def load_logistics_state(
        self, workspace_id: str, node_id: str
    ) -> LogisticsOperationalState | None:
        return await self._load(workspace_id, node_id, LogisticsOperationalState)

    async def load_production_state(
        self, workspace_id: str, node_id: str
    ) -> ProductionOperationalState | None:
        return await self._load(workspace_id, node_id, ProductionOperationalState)

    async def load_business_state(
        self, workspace_id: str, node_id: str
    ) -> BusinessOperationalState | None:
        return await self._load(workspace_id, node_id, BusinessOperationalState)

    async def list_node_ids(self, workspace_id: str) -> list[str]:
        stmt = select(OperationalStateRecord.node_id).where(
            OperationalStateRecord.workspace_id == workspace_id
        )
        return list((await self._db.execute(stmt)).scalars().all())
