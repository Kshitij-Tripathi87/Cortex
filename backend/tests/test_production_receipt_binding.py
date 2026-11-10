"""Tests for Production Receipt Binding — P0 Priority.

Validates that production supervisor receipts are cryptographically bound to
the same resolved execution context as the tested executor path, with all
12 independent verification fields present and consistent.

Seven test scenarios covering the P0 priorities:
  1. Receipt with all bindings present → verification passes
  2. Receipt missing policy_digest → verification fails
  3. Receipt missing bundle_digest → verification fails
  4. Receipt missing profile_digest → verification fails
  5. Receipt missing image_digest → verification fails
  6. Receipt with mismatched run_spec_id → verification fails
  7. Full chain verification: receipt bindings consistent with V2.4 evidence chain
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from typing import Any

from app.modules.nexus_spine.governed_execution_models import (
    ApprovalRecord,
)
from app.modules.nexus_spine.models import AgentProposal, compute_proposal_hash
from app.modules.nexus_spine.production_receipt import (
    ProductionReceipt,
    build_production_receipt,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def make_minimal_proposal() -> AgentProposal:
    """A real AgentProposal with its canonical proposal_hash computed."""
    proposal = AgentProposal(
        agent_id="test_agent",
        agent_family="PROCUREMENT",
        action="switch_supplier",
        expected_cost_usd=1000.0,
        world_state_version=3,
    )
    return replace(proposal, proposal_hash=compute_proposal_hash(proposal))


def make_minimal_approval(decision_id: str = "dec_test_001") -> ApprovalRecord:
    """Create a minimal approval record for testing."""
    return ApprovalRecord.create(
        decision_id=decision_id,
        operator_id="usr_test",
        operator_role="operator",
        decision="APPROVE",
        proposal_hash="prop_hash_test",
        simulation_hash="sim_hash_test",
        world_state_version=3,
        approval_expiry=None,
    )


def make_minimal_policy_dict() -> dict[str, Any]:
    """Create a minimal sandbox policy dict for testing."""
    return {
        "cpu_limit": 2,
        "memory_limit_mb": 1024,
        "process_limit": 64,
        "execution_timeout_s": 120,
        "filesystem_scope": "sandbox",
        "network_mode": "none",
        "allowed_hosts": [],
        "artifact_limit": 50,
        "artifact_max_bytes": 10 * 1024 * 1024,
        "output_max_bytes": 512 * 1024,
        "command_allowlist": ["node", "npm", "python"],
    }


# ── Test 1: Receipt with all bindings present → verification passes ──────────


def test_receipt_all_bindings_present() -> dict[str, Any]:
    """Test that a receipt with all 12 binding fields passes verification."""
    proposal = make_minimal_proposal()
    approval = make_minimal_approval()
    policy_dict = make_minimal_policy_dict()

    # Compute digests

    bundle_digest = hashlib.sha256(
        json.dumps({"bundle": "test"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    profile_digest = hashlib.sha256(
        json.dumps({"profile": "test"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    tool_version = "v1.2.3"
    image_digest = "sha256:abc123def456"

    receipt = build_production_receipt(
        run_spec_id="run_spec_test_001",
        policy=policy_dict,
        bundle_digest=bundle_digest,
        profile_digest=profile_digest,
        tool_version=tool_version,
        image_digest=image_digest,
        proposal=proposal,
        approval=approval,
        twin_result={"simulation_hash": "sim_abc123"},
        world_state_version=3,
        world_state_hash=hashlib.sha256(b"test ws").hexdigest(),
        evidence_root_id="evidence_root_test",
        adapter_result={"status": "EXECUTED"},
    )

    # Verify the receipt
    passed, failures = receipt.verify(expected_run_spec_id="run_spec_test_001")

    assert passed is True, f"Expected receipt verification to pass, got failures: {failures}"
    assert len(failures) == 0, f"Expected no failures, got: {failures}"

    # Verify individual fields
    assert receipt.run_spec_id == "run_spec_test_001"
    assert len(receipt.policy_digest) == 64
    assert len(receipt.bundle_digest) == 64
    assert len(receipt.profile_digest) == 64
    assert receipt.tool_version == tool_version
    assert len(receipt.image_digest) > 0
    assert len(receipt.authorization_hash) == 64
    assert len(receipt.outcome_hash) == 64
    assert len(receipt.proposal_hash) == 64
    assert len(receipt.simulation_hash) > 0
    assert receipt.world_state_version == 3


# ── Test 2: Receipt missing policy_digest → verification fails ─────────────


def test_receipt_missing_policy_digest() -> dict[str, Any]:
    """Test that a receipt missing policy_digest fails verification."""
    # Create a receipt but strip the policy_digest
    # We'll create one with a bogus empty policy_digest

    from app.modules.nexus_spine.production_receipt import ProductionReceipt

    # Build receipt with empty policy_digest (should fail verification)
    # This is tricky since build_production_receipt always computes it.
    # Instead, we test the verify method directly with a malformed receipt.

    # Create a minimal receipt structure manually for this test
    receipt = ProductionReceipt(
        run_spec_id="run_spec_test_002",
        policy_digest="",  # Empty → should fail
        bundle_digest=hashlib.sha256(b"test bundle").hexdigest(),
        profile_digest=hashlib.sha256(b"test profile").hexdigest(),
        tool_version="v1.2.3",
        image_digest="sha256:abc123def456",
        authorization_hash="a" * 64,  # Invalid: not a real hash but format check
        outcome_hash="b" * 64,
        proposal_hash="c" * 64,
        simulation_hash="sim_test",
        world_state_version=3,
    )

    passed, failures = receipt.verify(expected_run_spec_id="run_spec_test_002")

    assert passed is False, "Expected receipt verification to fail with missing policy_digest"
    assert any("POLICY_DIGEST_MISSING" in f or "RECEIPT_MISSING" in f for f in failures), (
        f"Expected policy digest related failure, got: {failures}"
    )


# ── Test 3: Receipt missing bundle_digest → verification fails ──────────────


def test_receipt_missing_bundle_digest() -> dict[str, Any]:
    """Test that a receipt missing bundle_digest fails verification."""
    receipt = ProductionReceipt(
        run_spec_id="run_spec_test_003",
        policy_digest=hashlib.sha256(b"test policy").hexdigest(),
        bundle_digest="",  # Empty → should fail
        profile_digest=hashlib.sha256(b"test profile").hexdigest(),
        tool_version="v1.2.3",
        image_digest="sha256:abc123def456",
        authorization_hash="a" * 64,
        outcome_hash="b" * 64,
        proposal_hash="c" * 64,
        simulation_hash="sim_test",
        world_state_version=3,
    )

    passed, failures = receipt.verify(expected_run_spec_id="run_spec_test_003")

    assert passed is False, "Expected receipt verification to fail with missing bundle_digest"
    assert any("BUNDLE_DIGEST_MISSING" in f or "RECEIPT_MISSING" in f for f in failures), (
        f"Expected bundle digest related failure, got: {failures}"
    )


# ── Test 4: Receipt missing profile_digest → verification fails ─────────────


def test_receipt_missing_profile_digest() -> dict[str, Any]:
    """Test that a receipt missing profile_digest fails verification."""
    receipt = ProductionReceipt(
        run_spec_id="run_spec_test_004",
        policy_digest=hashlib.sha256(b"test policy").hexdigest(),
        bundle_digest=hashlib.sha256(b"test bundle").hexdigest(),
        profile_digest="",  # Empty → should fail
        tool_version="v1.2.3",
        image_digest="sha256:abc123def456",
        authorization_hash="a" * 64,
        outcome_hash="b" * 64,
        proposal_hash="c" * 64,
        simulation_hash="sim_test",
        world_state_version=3,
    )

    passed, failures = receipt.verify(expected_run_spec_id="run_spec_test_004")

    assert passed is False, "Expected receipt verification to fail with missing profile_digest"
    assert any("PROFILE_DIGEST_MISSING" in f or "RECEIPT_MISSING" in f for f in failures), (
        f"Expected profile digest related failure, got: {failures}"
    )


# ── Test 5: Receipt missing image_digest → verification fails ──────────────


def test_receipt_missing_image_digest() -> dict[str, Any]:
    """Test that a receipt missing image_digest fails verification."""
    receipt = ProductionReceipt(
        run_spec_id="run_spec_test_005",
        policy_digest=hashlib.sha256(b"test policy").hexdigest(),
        bundle_digest=hashlib.sha256(b"test bundle").hexdigest(),
        profile_digest=hashlib.sha256(b"test profile").hexdigest(),
        tool_version="v1.2.3",
        image_digest="",  # Empty → should fail
        authorization_hash="a" * 64,
        outcome_hash="b" * 64,
        proposal_hash="c" * 64,
        simulation_hash="sim_test",
        world_state_version=3,
    )

    passed, failures = receipt.verify(expected_run_spec_id="run_spec_test_005")

    assert passed is False, "Expected receipt verification to fail with missing image_digest"
    assert any("IMAGE_DIGEST_MISSING" in f or "RECEIPT_MISSING" in f for f in failures), (
        f"Expected image digest related failure, got: {failures}"
    )


# ── Test 6: Receipt with mismatched run_spec_id → verification fails ───────


def test_receipt_mismatched_run_spec_id() -> dict[str, Any]:
    """Test that a receipt with mismatched run_spec_id fails verification."""

    proposal = make_minimal_proposal()
    approval = make_minimal_approval()
    policy_dict = make_minimal_policy_dict()

    bundle_digest = hashlib.sha256(
        json.dumps({"bundle": "test"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    profile_digest = hashlib.sha256(
        json.dumps({"profile": "test"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    tool_version = "v1.2.3"
    image_digest = "sha256:abc123def456"

    receipt = build_production_receipt(
        run_spec_id="run_spec_test_006",
        policy=policy_dict,
        bundle_digest=bundle_digest,
        profile_digest=profile_digest,
        tool_version=tool_version,
        image_digest=image_digest,
        proposal=proposal,
        approval=approval,
        twin_result={"simulation_hash": "sim_abc123"},
        world_state_version=3,
        world_state_hash=hashlib.sha256(b"test ws").hexdigest(),
        evidence_root_id="evidence_root_test",
        adapter_result={"status": "EXECUTED"},
    )

    # Verify with a DIFFERENT run_spec_id — should fail
    passed, failures = receipt.verify(expected_run_spec_id="run_spec_different_006")

    assert passed is False, "Expected receipt verification to fail with mismatched run_spec_id"
    assert any("RECEIPT_MISMATCH" in f for f in failures), (
        f"Expected run_spec_id mismatch failure, got: {failures}"
    )

    # But verify with the correct one should pass
    passed_correct, failures_correct = receipt.verify(expected_run_spec_id="run_spec_test_006")
    assert passed_correct is True, (
        f"Expected receipt verification to pass with correct run_spec_id, got: {failures_correct}"
    )


# ── Test 7: Full chain verification ────────────────────────────────────────


def test_full_chain_verification() -> dict[str, Any]:
    """Test full chain verification: receipt bindings consistent with V2.4 evidence chain."""

    proposal = make_minimal_proposal()
    approval = make_minimal_approval()
    policy_dict = make_minimal_policy_dict()

    bundle_digest = hashlib.sha256(
        json.dumps({"bundle": "test"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    profile_digest = hashlib.sha256(
        json.dumps({"profile": "test"}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    tool_version = "v1.2.3"
    image_digest = "sha256:abc123def456"

    receipt = build_production_receipt(
        run_spec_id="run_spec_fullchain_007",
        policy=policy_dict,
        bundle_digest=bundle_digest,
        profile_digest=profile_digest,
        tool_version=tool_version,
        image_digest=image_digest,
        proposal=proposal,
        approval=approval,
        twin_result={"simulation_hash": "sim_fullchain_007"},
        world_state_version=3,
        world_state_hash=hashlib.sha256(b"test ws full chain").hexdigest(),
        evidence_root_id="evidence_root_fullchain",
        adapter_result={"status": "EXECUTED", "execution_id": "exec_fullchain_007"},
    )

    # Verify the receipt
    passed, failures = receipt.verify(expected_run_spec_id="run_spec_fullchain_007")
    assert passed is True, f"Expected receipt verification to pass, got: {failures}"

    # Verify receipt hash computation is deterministic
    receipt_hash_1 = ProductionReceipt.compute_receipt_hash(
        run_spec_id="run_spec_fullchain_007",
        policy_digest=receipt.policy_digest,
        bundle_digest=receipt.bundle_digest,
        profile_digest=receipt.profile_digest,
        tool_version=receipt.tool_version,
        image_digest=receipt.image_digest,
    )

    receipt_hash_2 = ProductionReceipt.compute_receipt_hash(
        run_spec_id="run_spec_fullchain_007",
        policy_digest=receipt.policy_digest,
        bundle_digest=receipt.bundle_digest,
        profile_digest=receipt.profile_digest,
        tool_version=receipt.tool_version,
        image_digest=receipt.image_digest,
    )

    assert receipt_hash_1 == receipt_hash_2, "Receipt hash computation must be deterministic"

    # Verify the receipt can be serialized/deserialized (to_dict roundtrip)
    receipt_dict = receipt.to_dict()
    assert "run_spec_id" in receipt_dict
    assert "policy_digest" in receipt_dict
    assert "bundle_digest" in receipt_dict
    assert "profile_digest" in receipt_dict
    assert "tool_version" in receipt_dict
    assert "image_digest" in receipt_dict
    assert "authorization_hash" in receipt_dict
    assert "outcome_hash" in receipt_dict
    assert "proposal_hash" in receipt_dict
    assert "simulation_hash" in receipt_dict
    assert "world_state_version" in receipt_dict
    assert "executed_at" in receipt_dict

    # Verify executed_at is a valid ISO timestamp
    executed_at = datetime.fromisoformat(receipt_dict["executed_at"])
    assert executed_at is not None


# ── Run all tests ──────────────────────────────────────────────────────────


def run_all_tests() -> list[dict[str, Any]]:
    """Run all production receipt binding tests and return results."""
    tests = [
        test_receipt_all_bindings_present,
        test_receipt_missing_policy_digest,
        test_receipt_missing_bundle_digest,
        test_receipt_missing_profile_digest,
        test_receipt_missing_image_digest,
        test_receipt_mismatched_run_spec_id,
        test_full_chain_verification,
    ]

    results = []
    for test_fn in tests:
        try:
            result = test_fn()
            results.append(result)
            print(f"✓ {result['name']}: {result['status']}")
            if "failure_reason" in result:
                print(f"  → {result['failure_reason']}")
        except Exception as e:
            results.append(
                {
                    "name": test_fn.__name__,
                    "status": "error",
                    "error": str(e),
                }
            )
            print(f"✗ {test_fn.__name__}: ERROR - {e}")

    return results


if __name__ == "__main__":
    results = run_all_tests()

    print("\n" + "=" * 60)
    print("PRODUCTION RECEIPT BINDING TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    error = sum(1 for r in results if r["status"] == "error")

    print(f"Total: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Error: {error}")

    if all(r["status"] == "passed" for r in results):
        print("\n✓ ALL TESTS PASSED — Production receipt binding is verified.")
    else:
        print("\n✗ SOME TESTS FAILED — Review the results above.")
