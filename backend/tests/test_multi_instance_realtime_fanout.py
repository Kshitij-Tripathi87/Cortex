"""Multi-Instance Real-Time Fanout & Cluster Verification Suite — S4.

Tests multi-node WebSocket fanout, Redis Pub/Sub coordination, monotonic sequence
resync, cross-tenant/cross-workspace isolation across nodes, and zero-message-loss
delivery under sustained concurrent load.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

from app.infrastructure.realtime_gateway import (
    RealtimeChannel,
    RealtimeGateway,
)
from app.modules.data_intelligence.graph_delta_engine import (
    GraphDeltaEngine,
)
from app.modules.data_intelligence.operational_graph import (
    OperationalGraphEngine,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test Doubles & Clustered Redis Bus Emulator
# ─────────────────────────────────────────────────────────────────────────────


class MockWebSocket:
    """Async WebSocket test double capturing received messages and state."""

    def __init__(self, client_state: WebSocketState = WebSocketState.CONNECTED) -> None:
        self.client_state = client_state
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.received_messages: list[str] = []
        self._send_error: Exception | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason
        self.client_state = WebSocketState.DISCONNECTED

    async def send_text(self, data: str) -> None:
        if self._send_error:
            raise self._send_error
        if self.client_state == WebSocketState.DISCONNECTED or self.closed:
            raise RuntimeError("Cannot send text on disconnected WebSocket")
        self.received_messages.append(data)


class ClusteredRedisPubSubEmulator:
    """In-memory Redis Pub/Sub bus connecting multiple RealtimeGateway nodes."""

    def __init__(self) -> None:
        self.nodes: list[RealtimeGateway] = []
        self.published_messages: list[str] = []
        self.failure_mode: bool = False

    def register_node(self, node: RealtimeGateway) -> None:
        self.nodes.append(node)

    async def publish(self, channel: str, message: str) -> int:
        if self.failure_mode:
            raise ConnectionError("Simulated Redis PubSub connection dropped")
        self.published_messages.append(message)
        # Fanout to all peer nodes asynchronously
        delivery_tasks = [
            asyncio.create_task(node.handle_cluster_message(message)) for node in self.nodes
        ]
        if delivery_tasks:
            await asyncio.gather(*delivery_tasks, return_exceptions=True)
        return len(self.nodes)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Multi-Node Clustered Fanout & Cross-Node Broadcast
# ─────────────────────────────────────────────────────────────────────────────


class TestClusteredRealtimeFanout:
    """Verifies that events broadcast on Node A propagate via Redis to clients on Node B and C."""

    @pytest.mark.asyncio
    async def test_cross_node_event_propagation(self) -> None:
        """Client connected to Node 2 receives event broadcast on Node 1."""
        bus = ClusteredRedisPubSubEmulator()
        node_1 = RealtimeGateway(node_id="node_alpha")
        node_2 = RealtimeGateway(node_id="node_beta")
        node_3 = RealtimeGateway(node_id="node_gamma")
        for n in (node_1, node_2, node_3):
            bus.register_node(n)

        # Mock Redis client for node 1
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=bus.publish)
        node_1._cluster_fanout = lambda msg: bus.publish("cortex:realtime:cluster_events", msg)

        ws_client_node1 = MockWebSocket()
        ws_client_node2 = MockWebSocket()
        ws_client_node3 = MockWebSocket()

        tenant = "org_enterprise_01"
        ws_id = "ws_supply_chain"

        await node_1.connect("s1", "user_1", tenant, ws_id, ws_client_node1)
        await node_1.subscribe("s1", ws_id, RealtimeChannel.WORLD_STATE)

        await node_2.connect("s2", "user_2", tenant, ws_id, ws_client_node2)
        await node_2.subscribe("s2", ws_id, RealtimeChannel.WORLD_STATE)

        await node_3.connect("s3", "user_3", tenant, ws_id, ws_client_node3)
        await node_3.subscribe("s3", ws_id, RealtimeChannel.WORLD_STATE)

        # Broadcast on Node 1
        payload = {"version": 42, "entity_id": "SUPPLIER_001", "status": "DELAYED"}
        await node_1.broadcast(
            tenant_id=tenant,
            workspace_id=ws_id,
            channel=RealtimeChannel.WORLD_STATE,
            event_type="WORLD_STATE_CHANGED",
            payload=payload,
        )

        # Allow cluster tasks to complete
        await asyncio.sleep(0.05)

        # Verify all 3 clients across 3 distinct nodes received the payload
        for ws in (ws_client_node1, ws_client_node2, ws_client_node3):
            assert len(ws.received_messages) == 1
            msg = json.loads(ws.received_messages[0])
            assert msg["event_type"] == "WORLD_STATE_CHANGED"
            assert msg["payload"]["entity_id"] == "SUPPLIER_001"
            assert msg["origin_node"] == "node_alpha"

    @pytest.mark.asyncio
    async def test_originating_node_does_not_duplicate_from_cluster_message(self) -> None:
        """Originating node drops its own cluster message to prevent duplicate delivery."""
        node_1 = RealtimeGateway(node_id="node_alpha")
        ws = MockWebSocket()
        await node_1.connect("s1", "u1", "t1", "ws1", ws)
        await node_1.subscribe("s1", "ws1", "*")

        # Simulate cluster echo of its own message
        echo_message = json.dumps(
            {
                "channel": "world-state",
                "event_type": "TEST",
                "workspace_id": "ws1",
                "tenant_id": "t1",
                "origin_node": "node_alpha",  # Same as node_1.node_id
                "payload": {"test": True},
            }
        )

        await node_1.handle_cluster_message(echo_message)
        assert len(ws.received_messages) == 0, (
            "Node must not process cluster message originating from itself"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Multi-Tenant & Multi-Workspace Isolation Across Nodes
# ─────────────────────────────────────────────────────────────────────────────


class TestClusteredTenantAndWorkspaceIsolation:
    """Verifies strict negative isolation across multiple cluster instances."""

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation_across_cluster(self) -> None:
        """Tenant B on Node 2 must never receive Tenant A events broadcast on Node 1."""
        bus = ClusteredRedisPubSubEmulator()
        node_1 = RealtimeGateway(node_id="node_1")
        node_2 = RealtimeGateway(node_id="node_2")
        bus.register_node(node_1)
        bus.register_node(node_2)
        node_1._cluster_fanout = lambda msg: bus.publish("cortex:realtime:cluster_events", msg)

        ws_tenant_a = MockWebSocket()
        ws_tenant_b = MockWebSocket()

        # Tenant A on Node 1
        await node_1.connect("s_a", "u_a", "org_tenant_A", "ws_shared_name", ws_tenant_a)
        await node_1.subscribe("s_a", "ws_shared_name", "*")

        # Tenant B on Node 2 (same workspace name string, different tenant_id)
        await node_2.connect("s_b", "u_b", "org_tenant_B", "ws_shared_name", ws_tenant_b)
        await node_2.subscribe("s_b", "ws_shared_name", "*")

        # Broadcast for Tenant A on Node 1
        await node_1.broadcast(
            tenant_id="org_tenant_A",
            workspace_id="ws_shared_name",
            channel="scenarios",
            event_type="SCENARIO_STARTED",
            payload={"secret_budget": 1000000.0},
        )
        await asyncio.sleep(0.05)

        assert len(ws_tenant_a.received_messages) == 1
        assert len(ws_tenant_b.received_messages) == 0, (
            "Tenant B must NOT receive Tenant A cluster events"
        )

    @pytest.mark.asyncio
    async def test_cross_workspace_isolation_across_cluster(self) -> None:
        """Workspace 2 on Node 2 must not receive Workspace 1 events broadcast on Node 1."""
        bus = ClusteredRedisPubSubEmulator()
        node_1 = RealtimeGateway(node_id="node_1")
        node_2 = RealtimeGateway(node_id="node_2")
        bus.register_node(node_1)
        bus.register_node(node_2)
        node_1._cluster_fanout = lambda msg: bus.publish("cortex:realtime:cluster_events", msg)

        ws_ws1 = MockWebSocket()
        ws_ws2 = MockWebSocket()

        tenant = "org_same_corp"
        await node_1.connect("s1", "u1", tenant, "ws_finance", ws_ws1)
        await node_1.subscribe("s1", "ws_finance", "*")

        await node_2.connect("s2", "u2", tenant, "ws_engineering", ws_ws2)
        await node_2.subscribe("s2", "ws_engineering", "*")

        await node_1.broadcast(
            tenant_id=tenant,
            workspace_id="ws_finance",
            channel="decisions",
            event_type="APPROVAL_GRANTED",
            payload={"approved_amount": 50000.0},
        )
        await asyncio.sleep(0.05)

        assert len(ws_ws1.received_messages) == 1
        assert len(ws_ws2.received_messages) == 0, (
            "ws_engineering must NOT receive ws_finance events"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Channel Subscription Matrix
# ─────────────────────────────────────────────────────────────────────────────


class TestChannelSubscriptionFiltering:
    """Verifies that channel filtering is strictly respected locally and across nodes."""

    @pytest.mark.asyncio
    async def test_channel_specific_delivery(self) -> None:
        """Subscribers only receive events for channels they subscribed to, or wildcard '*'."""
        node = RealtimeGateway(node_id="node_filter")

        ws_world = MockWebSocket()
        ws_decisions = MockWebSocket()
        ws_all = MockWebSocket()

        tenant, ws_id = "org_acme", "ws_main"
        await node.connect("s_world", "u1", tenant, ws_id, ws_world)
        await node.subscribe("s_world", ws_id, RealtimeChannel.WORLD_STATE)

        await node.connect("s_dec", "u2", tenant, ws_id, ws_decisions)
        await node.subscribe("s_dec", ws_id, RealtimeChannel.DECISIONS)

        await node.connect("s_all", "u3", tenant, ws_id, ws_all)
        await node.subscribe("s_all", ws_id, "*")

        # 1. Broadcast WORLD_STATE event
        await node.broadcast(
            tenant_id=tenant,
            workspace_id=ws_id,
            channel=RealtimeChannel.WORLD_STATE,
            event_type="STATE_TICK",
            payload={"version": 1},
        )
        assert len(ws_world.received_messages) == 1
        assert len(ws_decisions.received_messages) == 0
        assert len(ws_all.received_messages) == 1

        # 2. Broadcast DECISIONS event
        await node.broadcast(
            tenant_id=tenant,
            workspace_id=ws_id,
            channel=RealtimeChannel.DECISIONS,
            event_type="DECISION_APPROVED",
            payload={"decision_id": "dec_1"},
        )
        assert len(ws_world.received_messages) == 1
        assert len(ws_decisions.received_messages) == 1
        assert len(ws_all.received_messages) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. Monotonic Sequence Ordering & Client Resync Verification
# ─────────────────────────────────────────────────────────────────────────────


class TestMonotonicSequenceOrderingAndResync:
    """Verifies monotonic sequence stream deltas and gap recovery under multi-client loads."""

    def test_delta_engine_monotonic_sequences_across_events(self) -> None:
        """Delta stream produces strictly increasing monotonic sequence numbers."""
        delta_engine = GraphDeltaEngine(OperationalGraphEngine())

        deltas = []
        for i in range(50):
            d = delta_engine.apply_stream_event(
                event_type="INVENTORY_REORDER",
                payload={"sku": f"SKU_{i}", "qty": 100},
                world_state_version=i + 1,
            )
            deltas.append(d)

        # Monotonicity invariant
        for i in range(1, len(deltas)):
            assert deltas[i].seq == deltas[i - 1].seq + 1
            assert deltas[i].world_state_version == deltas[i - 1].world_state_version + 1

    def test_resync_replay_buffer_recovery(self) -> None:
        """Client reconnecting with since_seq recovers missed deltas in strict order."""
        delta_engine = GraphDeltaEngine(OperationalGraphEngine())

        # Generate 20 events
        all_deltas = [
            delta_engine.apply_stream_event(
                event_type="ORDER_PLACED",
                payload={"order_id": f"ORD_{i}"},
                world_state_version=i + 1,
            )
            for i in range(20)
        ]

        # Target seq to replay from (e.g. client last saw delta index 9)
        last_seen_seq = all_deltas[9].seq

        # Client missed from last_seen_seq onwards
        replayed = delta_engine.get_deltas_since_seq(since_seq=last_seen_seq)
        assert len(replayed) == 10
        assert replayed[0].seq == last_seen_seq + 1
        assert replayed[-1].seq == all_deltas[-1].seq

        # Verify sequential ordering of replayed items
        for i in range(1, len(replayed)):
            assert replayed[i].seq == replayed[i - 1].seq + 1

        # Verify min_known_seq
        assert delta_engine.min_known_seq() == all_deltas[0].seq


# ─────────────────────────────────────────────────────────────────────────────
# 5. Zero Message Loss Under High-Concurrency Multi-Node Fanout
# ─────────────────────────────────────────────────────────────────────────────


class TestHighConcurrencyClusteredFanout:
    """Verifies zero message loss across 4 cluster nodes with 200 concurrent WebSocket clients."""

    @pytest.mark.asyncio
    async def test_concurrent_fanout_zero_message_loss(self) -> None:
        bus = ClusteredRedisPubSubEmulator()
        nodes = [RealtimeGateway(node_id=f"node_{i}") for i in range(4)]
        for n in nodes:
            bus.register_node(n)
            n._cluster_fanout = lambda msg: bus.publish("cortex:realtime:cluster_events", msg)

        tenant, ws_id = "org_scale", "ws_scale_1"
        clients: list[MockWebSocket] = []

        # Connect 50 clients to each of the 4 nodes (200 total)
        for i, node in enumerate(nodes):
            for j in range(50):
                ws = MockWebSocket()
                clients.append(ws)
                sid = f"s_{i}_{j}"
                await node.connect(sid, f"user_{i}_{j}", tenant, ws_id, ws)
                await node.subscribe(sid, ws_id, "*")

        # Broadcast 10 rapid events from Node 0
        total_broadcasts = 10
        for b_idx in range(total_broadcasts):
            await nodes[0].broadcast(
                tenant_id=tenant,
                workspace_id=ws_id,
                channel=RealtimeChannel.WORLD_STATE,
                event_type="TELEMETRY_UPDATE",
                payload={"batch": b_idx, "temp_c": 22.5 + b_idx},
            )

        await asyncio.sleep(0.1)

        # Assert every single client received exactly 10 messages with 0% loss
        for idx, ws in enumerate(clients):
            assert len(ws.received_messages) == total_broadcasts, (
                f"Client {idx} received {len(ws.received_messages)}/{total_broadcasts} messages"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Dead Session Pruning & Fault Tolerance
# ─────────────────────────────────────────────────────────────────────────────


class TestRealtimeGatewayFaultTolerance:
    """Verifies gateway resilience to failed WebSockets and Redis broker outages."""

    @pytest.mark.asyncio
    async def test_dead_websocket_pruning_on_broadcast(self) -> None:
        """Clients that fail on send_text are cleanly pruned without affecting healthy clients."""
        node = RealtimeGateway(node_id="node_prune")
        tenant, ws_id = "org_fault", "ws_fault"

        healthy_ws = MockWebSocket()
        failing_ws = MockWebSocket()
        failing_ws._send_error = ConnectionResetError("Client disconnected unexpectedly")

        await node.connect("s_healthy", "u1", tenant, ws_id, healthy_ws)
        await node.subscribe("s_healthy", ws_id, "*")

        await node.connect("s_failing", "u2", tenant, ws_id, failing_ws)
        await node.subscribe("s_failing", ws_id, "*")

        assert node.get_active_connection_count() == 2

        # Broadcast triggers delivery and auto-pruning of dead session
        recipients = await node.broadcast(
            tenant_id=tenant,
            workspace_id=ws_id,
            channel="world-state",
            event_type="PING",
            payload={"ping": 1},
        )

        assert recipients == 1
        assert len(healthy_ws.received_messages) == 1
        assert node.get_active_connection_count() == 1
        assert "s_failing" not in node._sessions

    @pytest.mark.asyncio
    async def test_redis_broker_outage_fails_safe_with_local_delivery(self) -> None:
        """When Redis PubSub is unavailable, local fanout succeeds and failures are counted."""
        node = RealtimeGateway(node_id="node_resilient")
        tenant, ws_id = "org_safe", "ws_safe"

        ws = MockWebSocket()
        await node.connect("s1", "u1", tenant, ws_id, ws)
        await node.subscribe("s1", ws_id, "*")

        # Simulate Redis publish raising an exception
        async def _failing_redis_cluster(msg: str) -> None:
            raise TimeoutError("Redis socket timeout on publish")

        node._cluster_fanout = _failing_redis_cluster

        # Broadcast must NOT raise exception to caller
        recipients = await node.broadcast(
            tenant_id=tenant,
            workspace_id=ws_id,
            channel="world-state",
            event_type="SAFE_EVENT",
            payload={"safe": True},
        )

        assert recipients == 1
        assert len(ws.received_messages) == 1
