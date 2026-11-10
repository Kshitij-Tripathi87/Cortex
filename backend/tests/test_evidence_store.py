"""S3-compatible evidence store qualification — upload, integrity, tenant isolation.

Run against a live S3-compatible endpoint (MinIO in CI provides
``CORTEX_S3_ENDPOINT``/``CORTEX_S3_BUCKET``/credentials). Skipped locally
unless ``CORTEX_TEST_S3_ENDPOINT`` (or ``CORTEX_S3_ENDPOINT`` pointing at a
reachable MinIO) is set — CI's minio service satisfies this automatically.

Qualification targets (staging security matrix, object-storage row):
  * Upload / download round-trip integrity (SHA-256 verified)
  * Tampering detection (content modified → digest mismatch)
  * Tenant isolation: guessed or leaked foreign object keys are denied
  * Path safety: traversal and unsafe identifiers rejected
"""

from __future__ import annotations

import os
import socket

import pytest

from app.modules.workflo_backend.evidence_store import (
    EvidenceStore,
    EvidenceStoreError,
    assert_tenant_key,
    digest_bytes,
    tenant_key,
)
from app.modules.workflo_backend.infrastructure.storage_client import ObjectStorageClient


def _endpoint_reachable(url: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 443 if parsed.scheme == "https" else parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _storage_available() -> bool:
    endpoint = os.environ.get("CORTEX_TEST_S3_ENDPOINT") or os.environ.get("CORTEX_S3_ENDPOINT")
    if not endpoint:
        return False
    return _endpoint_reachable(endpoint)


@pytest.fixture()
def evidence_store() -> EvidenceStore:
    if not _storage_available():
        pytest.skip(
            "no reachable S3-compatible endpoint (start MinIO or set CORTEX_TEST_S3_ENDPOINT)"
        )
    from app.config import get_settings

    settings = get_settings()
    if os.environ.get("CORTEX_TEST_S3_ENDPOINT"):
        settings.s3_endpoint = os.environ["CORTEX_TEST_S3_ENDPOINT"]
    storage = ObjectStorageClient(settings)
    return EvidenceStore(storage)


@pytest.fixture()
def bucket_prefix() -> str:
    """Unique per-test prefix so parallel runs never collide."""
    import uuid

    return f"evtest-{uuid.uuid4().hex[:12]}"


class TestEvidenceStoreQualification:
    def test_receipt_round_trip_integrity(self, evidence_store, bucket_prefix) -> None:
        receipt = {
            "receipt_version": "wp1",
            "run_spec_id": f"{bucket_prefix}-run1",
            "policy_digest": "a" * 64,
            "signature": "f" * 128,
        }
        key, sha = evidence_store.store_receipt(bucket_prefix, "run1", receipt)
        assert key == f"workflo/{bucket_prefix}/runs/run1/receipt.json"
        assert len(sha) == 64

        loaded = evidence_store.load_receipt(bucket_prefix, "run1")
        assert loaded is not None
        assert loaded["run_spec_id"] == receipt["run_spec_id"]
        assert loaded["policy_digest"] == receipt["policy_digest"]
        assert evidence_store.verify_integrity(bucket_prefix, "run1", "receipt.json", sha)

    def test_artifact_round_trip_and_digest(self, evidence_store, bucket_prefix) -> None:
        content = b"pytest result: 42 passed, 0 failed" * 100
        key, sha = evidence_store.store_artifact(bucket_prefix, "run2", "report.md", content)
        assert key.endswith("/artifacts/report.md")

        loaded, loaded_sha = evidence_store.load_artifact(bucket_prefix, "run2", "report.md")
        assert loaded == content
        assert loaded_sha == sha == digest_bytes(content)

    def test_tampered_content_detected(self, evidence_store, bucket_prefix) -> None:
        evidence_store.store_artifact(bucket_prefix, "run3", "evidence.txt", b"original")
        original_sha = digest_bytes(b"original")

        # Simulate tampering: overwrite the object with different content.
        tampered_key = tenant_key(bucket_prefix, "run3", "artifacts/evidence.txt")
        evidence_store._storage.put_object(tampered_key, b"tampered-content")

        assert not evidence_store.verify_integrity(
            bucket_prefix, "run3", "artifacts/evidence.txt", original_sha
        )

    def test_guessed_foreign_key_denied(self, evidence_store, bucket_prefix) -> None:
        """Tenant A stores evidence; tenant B tries to read it with the
        guessed (correctly-shaped) key — denied by the tenant guard."""
        evidence_store.store_artifact(
            "tenant-a-workspace", f"{bucket_prefix}-run", "secret.txt", b"tenant a evidence"
        )
        foreign_key = tenant_key(
            "tenant-a-workspace", f"{bucket_prefix}-run", "artifacts/secret.txt"
        )

        with pytest.raises(EvidenceStoreError) as excinfo:
            assert_tenant_key("tenant-b-workspace", foreign_key)
        assert "CROSS_TENANT_EVIDENCE_DENIED" in str(excinfo.value)

        # Tenant B's own namespace simply has nothing there.
        assert evidence_store.load_receipt("tenant-b-workspace", f"{bucket_prefix}-run") is None

    def test_path_traversal_rejected(self, evidence_store, bucket_prefix) -> None:
        with pytest.raises(EvidenceStoreError, match="UNSAFE_EVIDENCE_IDENTIFIER"):
            tenant_key(bucket_prefix, "run4", "artifacts/../../other-tenant/secrets")
        with pytest.raises(EvidenceStoreError, match="UNSAFE_EVIDENCE_IDENTIFIER"):
            tenant_key("../escape", "run4", "receipt.json")
        with pytest.raises(EvidenceStoreError, match="UNSAFE_EVIDENCE_IDENTIFIER"):
            evidence_store.store_artifact(bucket_prefix, "run4", "..\\..\\x", b"data")

    def test_load_missing_receipt_returns_none(self, evidence_store, bucket_prefix) -> None:
        assert evidence_store.load_receipt(bucket_prefix, "never-created") is None
