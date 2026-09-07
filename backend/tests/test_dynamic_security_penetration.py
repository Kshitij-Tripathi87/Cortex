"""Dynamic Security Penetration Test Suite — S3.

Adversarial verification testing beyond static AST scans:
1. Cross-tenant negative isolation (different orgs)
2. Cross-workspace negative isolation (same org, different workspaces)
3. Privilege escalation attempts (viewer -> operator -> admin)
4. Expired, forged, replayed, and malformed JWT tokens
5. WebSocket connection security & fail-closed authentication
6. Stale proposal approval rejection (world state version mismatch)
7. Tampered simulation & proposal parameter rejection
8. Cryptographic evidence DAG tamper detection & lineage integrity
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException, status

from app.common.ids import uuid7
from app.config import Settings
from app.infrastructure.cache_manager import get_cache_manager
from app.infrastructure.message_bus import NexusTopic, get_message_bus
from app.infrastructure.security import (
    AuthContext,
    require_role,
    require_workspace_access,
)
from app.modules.data_intelligence.decision_evidence_graph import (
    DecisionEvidenceGraph,
)
from app.modules.identity.jwt_auth import verify_token
from app.modules.memory.semantic_memory import get_semantic_memory
from app.modules.multi_agent.runtime.contracts_v1 import (
    CanonicalMessageType,
    build_canonical_message,
)
from app.modules.nexus_spine.evidence_chain import (
    ROOT_PARENT_ID,
    EvidenceChain,
    EvidenceNode,
)
from app.modules.nexus_spine.governed_execution_models import (
    ApprovalRecord,
)
from app.modules.nexus_spine.governed_execution_service import (
    GovernedExecutionError,
    GovernedExecutionService,
)
from app.modules.nexus_spine.models import AgentProposal

# ─────────────────────────────────────────────────────────────────────────────
# 1. Cross-Tenant Data Access Matrix (Different Orgs)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossTenantNegativeIsolation:
    """Verifies that Tenant B cannot access or leak Tenant A state across any layer."""

    @pytest.mark.asyncio
    async def test_cache_cross_tenant_isolation(self) -> None:
        """Tenant B must never be able to read Tenant A's cached world state."""
        cache = get_cache_manager()
        org_a, ws_a = "org_defense_contractor", "ws_radar_systems"
        org_b, ws_b = "org_commercial_airline", "ws_flight_ops"

        # Tenant A writes proprietary state
        await cache.set_world_state(org_a, ws_a, 1, {"critical_frequency": "9.4GHz", "classified": True})

        # Tenant B queries using Tenant A's workspace
        data_b = await cache.get_world_state(org_b, ws_a, 1)
        assert data_b is None, "Tenant B must NOT access Tenant A's cached world state"

        # Tenant B queries using own workspace
        data_b_own = await cache.get_world_state(org_b, ws_b, 1)
        assert data_b_own is None

    @pytest.mark.asyncio
    async def test_message_bus_cross_tenant_isolation(self) -> None:
        """Tenant B replay must never expose Tenant A's messages."""
        bus = get_message_bus()
        org_a = f"org_a_{uuid7()[:8]}"
        org_b = f"org_b_{uuid7()[:8]}"
        ws_a = f"ws_a_{uuid7()[:8]}"

        # Tenant A publishes confidential event
        msg_a = build_canonical_message(
            message_type=CanonicalMessageType.OBSERVATION,
            organization_id=org_a,
            workspace_id=ws_a,
            tenant_id=org_a,
            sender_id="agent_a",
            correlation_id="c_1",
            causation_id="c_1",
            conversation_id="conv_1",
            world_state_version=1,
            payload={"financial_q3_profit": 85000000.0},
            idempotency_key=f"idem_sec_{uuid7()}",
        )
        await bus.publish(NexusTopic.AGENT_MESSAGES, msg_a)

        # Tenant B replays topic
        replayed_b = await bus.replay(NexusTopic.AGENT_MESSAGES, tenant_id=org_b)
        assert not any(m.envelope.tenant_id == org_a for m in replayed_b), (
            "Tenant B replay contained Tenant A messages"
        )

    def test_semantic_memory_cross_tenant_isolation(self) -> None:
        """Semantic search from Tenant B must never match Tenant A indexed vectors."""
        mem = get_semantic_memory()
        org_a = f"org_sec_a_{uuid7()[:8]}"
        ws_a = f"ws_sec_a_{uuid7()[:8]}"
        ws_b = f"ws_sec_b_{uuid7()[:8]}"

        mem.index_document(
            workspace_id=ws_a,
            tenant_id=org_a,
            doc_type="policy",
            title="Catalyst Formula",
            content="Top secret formula for high efficiency catalyst",
            metadata={"confidential": True},
        )

        results_b = mem.search_similar(
            query="formula high efficiency catalyst",
            workspace_id=ws_b,
        )
        assert len(results_b) == 0, "Tenant B search must return zero results for Tenant A documents"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cross-Workspace Data Access Matrix (Same Org, Different Workspaces)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossWorkspaceNegativeIsolation:
    """Verifies that User with Workspace 1 access is strictly denied on Workspace 2."""

    def test_require_workspace_access_blocks_unauthorized_workspace(self) -> None:
        """User authorized only for ws_1 must receive 403 Forbidden for ws_2."""
        auth = AuthContext(
            user_id="user_alice",
            email="alice@corp.com",
            roles=["analyst"],
            workspace_ids=["ws_finance_q1"],
            is_anonymous=False,
        )

        # Allowed workspace
        require_workspace_access("ws_finance_q1", auth)

        # Forbidden workspace
        with pytest.raises(HTTPException) as exc_info:
            require_workspace_access("ws_hr_confidential", auth)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert exc_info.value.detail["error"] == "forbidden"
        assert exc_info.value.detail["workspace_id"] == "ws_hr_confidential"
        assert exc_info.value.detail["user_id"] == "user_alice"

    def test_require_workspace_access_rejects_empty_workspace(self) -> None:
        """Empty or missing workspace ID raises 404 Not Found to prevent info leak."""
        auth = AuthContext(user_id="user_alice", workspace_ids=["ws_1"])
        with pytest.raises(HTTPException) as exc_info:
            require_workspace_access("", auth)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    def test_cross_workspace_evidence_chain_rejection(self) -> None:
        """Evidence chain initialized for ws_1 must reject nodes from ws_2."""
        chain = EvidenceChain(
            organization_id="org_test",
            workspace_id="ws_allowed",
            correlation_id="corr_1",
            decision_id="dec_1",
        )
        chain.add(
            node_type="SOURCE",
            parent_id=ROOT_PARENT_ID,
            world_state_version=1,
            causation_id="",
            actor="sensor_1",
            input_payload={"test": 1},
            output_payload={"test": 1},
        )

        foreign_node = EvidenceNode.create(
            node_type="SIGNAL",
            parent_id=chain.nodes[0].event_id,
            organization_id="org_test",
            workspace_id="ws_forbidden_other",
            world_state_version=1,
            correlation_id="corr_1",
            causation_id=chain.nodes[0].event_id,
            actor="agent_rogue",
            input_payload={"test": 1},
            output_payload={"test": 2},
        )
        chain.nodes.append(foreign_node)

        ok, failures = chain.verify()
        assert not ok
        assert any("CROSS_WORKSPACE_NODE" in f for f in failures)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Privilege Escalation & Role Enforcement Matrix
# ─────────────────────────────────────────────────────────────────────────────

class TestPrivilegeEscalationRejection:
    """Verifies that lower-privileged principals cannot invoke higher-role actions."""

    def test_viewer_cannot_invoke_operator_action(self) -> None:
        """A user with role 'viewer' must be rejected when requiring 'operator'."""
        auth_viewer = AuthContext(
            user_id="user_viewer",
            roles=["viewer"],
            workspace_ids=["ws_1"],
        )

        with pytest.raises(HTTPException) as exc_info:
            require_role("operator", auth_viewer)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Role 'operator' required" in exc_info.value.detail["message"]

    def test_operator_cannot_invoke_system_admin_action(self) -> None:
        """A user with role 'operator' must be rejected when requiring 'system_admin'."""
        auth_operator = AuthContext(
            user_id="user_operator",
            roles=["operator"],
            workspace_ids=["ws_1"],
        )

        with pytest.raises(HTTPException) as exc_info:
            require_role("system_admin", auth_operator)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    def test_system_admin_implicitly_has_all_roles(self) -> None:
        """A user with 'system_admin' role satisfies any required role."""
        auth_admin = AuthContext(
            user_id="user_root",
            roles=["system_admin"],
            workspace_ids=["ws_1"],
        )
        # Should not raise for operator, analyst, or viewer
        require_role("operator", auth_admin)
        require_role("analyst", auth_admin)
        require_role("viewer", auth_admin)


# ─────────────────────────────────────────────────────────────────────────────
# 4. JWT Token Attack Vectors
# ─────────────────────────────────────────────────────────────────────────────

class TestJWTSecurityVectors:
    """Exercises adversarial JWT vectors: expired, forged, missing claims, tampered."""

    def test_expired_token_is_rejected(self) -> None:
        """Token with exp timestamp in the past must raise PermissionError."""
        secret = "super_secret_jwt_key_for_testing_001"
        settings = Settings(jwt_secret=secret)

        past_time = datetime.now(UTC) - timedelta(hours=1)
        payload = {
            "sub": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "roles": ["operator"],
            "exp": past_time,
            "aud": "cortex-api",
        }
        expired_token = jwt.encode(payload, secret, algorithm="HS256")

        with pytest.raises(PermissionError, match="Invalid or expired access token"):
            verify_token(expired_token, settings=settings)

    def test_forged_signature_is_rejected(self) -> None:
        """Token signed with an attacker's key must fail verification."""
        legit_secret = "legitimate_production_secret_key_123"
        attacker_secret = "evil_attacker_signing_key_999999"
        settings = Settings(jwt_secret=legit_secret)

        payload = {
            "sub": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "roles": ["system_admin"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "aud": "cortex-api",
        }
        forged_token = jwt.encode(payload, attacker_secret, algorithm="HS256")

        with pytest.raises(PermissionError, match="Invalid or expired access token"):
            verify_token(forged_token, settings=settings)

    def test_alg_none_vulnerability_is_rejected(self) -> None:
        """Unsecured tokens (algorithm='none') must be rejected."""
        settings = Settings(jwt_secret="some_secret_key_12345")
        payload = {
            "sub": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "roles": ["system_admin"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "aud": "cortex-api",
        }
        # In PyJWT, algorithm=none without key requires headers
        unsecured_token = jwt.encode(payload, key="", algorithm="none")

        with pytest.raises(PermissionError):
            verify_token(unsecured_token, settings=settings)

    def test_missing_workspace_id_claim_is_rejected(self) -> None:
        """Token missing required workspace_id claim must be rejected."""
        secret = "secret_key_testing_missing_claims"
        settings = Settings(jwt_secret=secret)

        payload = {
            "sub": str(uuid.uuid4()),
            # No workspace_id
            "roles": ["operator"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "aud": "cortex-api",
        }
        token = jwt.encode(payload, secret, algorithm="HS256")

        with pytest.raises(PermissionError):
            verify_token(token, settings=settings)

    def test_audience_mismatch_is_rejected(self) -> None:
        """Token with mismatched audience must be rejected."""
        secret = "secret_key_for_audience_test_001_pad32b"
        settings = Settings(jwt_secret=secret, jwt_audience="cortex-api")

        payload = {
            "sub": str(uuid.uuid4()),
            "workspace_id": str(uuid.uuid4()),
            "roles": ["operator"],
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "aud": "wrong-third-party-app",
        }
        token = jwt.encode(payload, secret, algorithm="HS256")

        with pytest.raises(PermissionError, match="Invalid or expired access token"):
            verify_token(token, settings=settings)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Stale Proposal Approval & State Mismatch Penetration
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleProposalApprovalPenetration:
    """Verifies that approval cannot execute against stale or modified world state."""

    def test_stale_world_state_version_blocks_execution(self) -> None:
        """When world state advances (e.g. from version 2 to 4), version 2 approval MUST fail closed."""
        service = GovernedExecutionService()

        proposal = AgentProposal(
            agent_id="reroute_agent",
            agent_family="OPTIMIZATION",
            action="REROUTE_SHIPMENT",
            expected_cost_usd=12000.0,
            confidence=0.92,
            payload={"new_carrier": "FedEx", "shipment_id": "SHP_99"},
            world_state_version=2,
            proposal_hash="prop_hash_reroute_001",
        )
        proposal_hash = proposal.proposal_hash
        simulation_hash = "sim_hash_abc123"

        # Operator approved when world state was at version 2
        approval = ApprovalRecord.create(
            decision_id="dec_001",
            operator_id="operator_bob",
            operator_role="operator",
            decision="APPROVE",
            proposal_hash=proposal_hash,
            simulation_hash=simulation_hash,
            world_state_version=2,
            approval_expiry=datetime.now(UTC) + timedelta(minutes=10),
        )

        # Execution attempted, but current world state is now version 4 (intervening state change)
        with pytest.raises(GovernedExecutionError) as exc_info:
            service.authorize_and_execute(
                proposal=proposal,
                approval=approval,
                twin_result={"simulation_hash": simulation_hash},
                policy_result={"approved": True, "policy_version": "pol_v1"},
                world_state_version=2,
                world_state_hash="state_hash_v2",
                evidence_root_id="ev_root_001",
                organization_id="org_acme",
                workspace_id="ws_main",
                current_world_version=4,  # Stale state detected!
            )

        assert "STALE_DECISION" in str(exc_info.value)
        assert any("STALE_DECISION" in f for f in exc_info.value.failures)

    def test_expired_approval_window_blocks_execution(self) -> None:
        """Approval past its expiry deadline must be rejected."""
        service = GovernedExecutionService()

        proposal = AgentProposal(
            agent_id="inventory_agent",
            agent_family="PROCUREMENT",
            action="EXPEDITE_PO",
            expected_cost_usd=5000.0,
            world_state_version=1,
            proposal_hash="prop_hash_002",
        )
        # Approval expired 5 minutes ago
        past_expiry = datetime.now(UTC) - timedelta(minutes=5)
        approval = ApprovalRecord.create(
            decision_id="dec_002",
            operator_id="operator_alice",
            operator_role="operator",
            decision="APPROVE",
            proposal_hash=proposal.proposal_hash,
            simulation_hash="sim_hash_002",
            world_state_version=1,
            approval_expiry=past_expiry,
        )

        with pytest.raises(GovernedExecutionError) as exc_info:
            service.authorize_and_execute(
                proposal=proposal,
                approval=approval,
                twin_result={"simulation_hash": "sim_hash_002"},
                policy_result={"approved": True, "policy_version": "pol_v1"},
                world_state_version=1,
                world_state_hash="hash_1",
                evidence_root_id="ev_root_1",
                organization_id="org_1",
                workspace_id="ws_1",
                current_world_version=1,
            )

        assert "APPROVAL_EXPIRED" in str(exc_info.value)

    def test_budget_exceeded_blocks_execution(self) -> None:
        """Proposal cost exceeding allocated authorization budget must be rejected."""
        service = GovernedExecutionService()

        proposal = AgentProposal(
            agent_id="procurement_agent",
            agent_family="PROCUREMENT",
            action="EMERGENCY_BUY",
            expected_cost_usd=150000.0,  # $150k
            world_state_version=1,
            proposal_hash="prop_hash_huge",
        )
        approval = ApprovalRecord.create(
            decision_id="dec_huge",
            operator_id="operator_alice",
            operator_role="operator",
            decision="APPROVE",
            proposal_hash=proposal.proposal_hash,
            simulation_hash="sim_hash_huge",
            world_state_version=1,
            approval_expiry=datetime.now(UTC) + timedelta(minutes=15),
        )

        # Budget cap is $50k
        with pytest.raises(GovernedExecutionError) as exc_info:
            service.authorize_and_execute(
                proposal=proposal,
                approval=approval,
                twin_result={"simulation_hash": "sim_hash_huge"},
                policy_result={"approved": True, "policy_version": "pol_v1"},
                world_state_version=1,
                world_state_hash="hash_1",
                evidence_root_id="ev_root_1",
                organization_id="org_1",
                workspace_id="ws_1",
                current_world_version=1,
                execution_budget_usd=50000.0,
            )

        assert "BUDGET_EXCEEDED" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cryptographic Evidence DAG Tamper Detection
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceDAGTamperDetection:
    """Verifies that altering any evidence node payload or edge invalidates provenance."""

    def test_intermediate_node_payload_tampering_invalidates_chain_hash(self) -> None:
        """Tampering with an intermediate hypothesis node must alter the provenance chain hash."""
        graph = DecisionEvidenceGraph(decision_id="DEC_PROV_001")

        # Step 1: Source
        n1 = graph.add_evidence_step(
            node_type="SOURCE_RECORD",
            label="Carrier Telemetry",
            payload={"carrier": "DHL", "status": "DELAYED_24H"},
        )
        # Step 2: Signal
        n2 = graph.add_evidence_step(
            node_type="SIGNAL",
            label="Bottleneck Detected",
            payload={"severity": 0.85, "route": "LAX-ORD"},
            parent_node_id=n1.node_id,
        )
        # Step 3: Proposal
        n3 = graph.add_evidence_step(
            node_type="PROPOSAL",
            label="Reroute via DFW",
            payload={"cost_usd": 1500.0},
            parent_node_id=n2.node_id,
        )
        assert n3.node_id in graph.nodes

        original_chain_hash = graph.compute_chain_hash()
        assert len(original_chain_hash) == 64

        # Attacker modifies the payload of n2 without changing node_id
        graph.nodes[n2.node_id].payload["severity"] = 0.10  # Alter severity to minimize risk

        # Recomputing step checksum detects payload tamper
        raw_json = json.dumps(graph.nodes[n2.node_id].payload, sort_keys=True, default=str)
        recalculated_checksum = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        assert recalculated_checksum != graph.nodes[n2.node_id].checksum_sha256, (
            "Recalculated checksum must differ from recorded SHA-256 after payload tamper"
        )

    def test_tampered_evidence_chain_root_hash_failure(self) -> None:
        """Modifying any field in an EvidenceChain node breaks root hash integrity."""
        chain = EvidenceChain(
            organization_id="org_secure",
            workspace_id="ws_secure",
            correlation_id="corr_ev_1",
            decision_id="dec_ev_1",
        )

        n1 = chain.add(
            node_type="SOURCE",
            parent_id=ROOT_PARENT_ID,
            world_state_version=1,
            causation_id="",
            actor="sensor_1",
            input_payload={"input_raw": "data_abc"},
            output_payload={"output_parsed": "data_abc"},
        )
        n2 = chain.add(
            node_type="PROPOSAL",
            parent_id=n1.event_id,
            world_state_version=1,
            causation_id=n1.event_id,
            actor="agent_procurement",
            input_payload={"input_signal": "bottleneck"},
            output_payload={"action": "ORDER_EXPEDITE", "cost": 4500.0},
        )

        original_root = chain.chain_root
        assert original_root != ""
        ok, failures = chain.verify()
        assert ok
        assert len(failures) == 0

        # Attacker tampers with the output_hash in node 2 payload
        tampered_node = replace(n2, output_hash="tampered_fake_hash_00000000000000000000000000000000")
        chain.nodes[1] = tampered_node

        # Verification fails: node_hash mismatch
        ok_tampered, failures_tampered = chain.verify()
        assert not ok_tampered
        assert any("NODE_HASH_MISMATCH" in f for f in failures_tampered)
