"""Source storage — content-addressed immutable file blobs.

Files are stored by content hash (SHA-256), making them immutable and
deduplicated by nature. The storage key is deterministic:
    tenants/{tenant_id}/workspaces/{workspace_id}/uploads/{checksum}

Raw files are NEVER modified after storage. Corrections arrive as new uploads.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.infrastructure.storage_client import ObjectStorageClient


def compute_checksum(data: bytes) -> str:
    """Compute SHA-256 checksum of file bytes."""
    return hashlib.sha256(data).hexdigest()


def build_storage_key(workspace_id: str, checksum: str) -> str:
    """Deterministic, safe storage key — no user-controlled path components."""
    # Checksum is hex (a-f0-9), workspace_id is a UUID — both path-safe.
    return f"workspaces/{workspace_id}/uploads/{checksum}"


@dataclass(frozen=True)
class StoredFile:
    """Result of a successful immutable storage operation."""

    storage_key: str
    checksum: str
    size: int
    is_duplicate: bool


class SourceStorage:
    """Content-addressed immutable file storage. No overwrite path."""

    def __init__(self, storage_client: ObjectStorageClient) -> None:
        self._client = storage_client

    def put(
        self,
        workspace_id: str,
        data: bytes,
    ) -> StoredFile:
        """Store bytes immutably. Returns storage metadata. Deduplicates by checksum."""
        checksum = compute_checksum(data)
        key = build_storage_key(workspace_id, checksum)
        size = len(data)

        if self._client.object_exists(key):
            return StoredFile(storage_key=key, checksum=checksum, size=size, is_duplicate=True)

        self._client.put_object(key, data, content_type="application/octet-stream")
        return StoredFile(storage_key=key, checksum=checksum, size=size, is_duplicate=False)

    def get(self, workspace_id: str, checksum: str) -> bytes:
        """Retrieve file bytes by checksum. Raises KeyError if not found."""
        key = build_storage_key(workspace_id, checksum)
        if not self._client.object_exists(key):
            raise KeyError(f"No stored file for checksum {checksum}")
        return self._client.get_object(key)

    def exists(self, workspace_id: str, checksum: str) -> bool:
        """Check if a content-addressed file already exists."""
        return self._client.object_exists(build_storage_key(workspace_id, checksum))
