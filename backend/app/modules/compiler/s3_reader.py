"""S3 raw-byte streaming reader for the graph compiler.

The compiler historically reconstructed source files from profiler output
(``SourceColumnProfile.sample_values``). That works for small uploads but:
  - loses fidelity on large files (>100MB),
  - round-trips through text manipulation that can subtly alter bytes,
  - prevents content-addressed verification via true file hashes.

This module exposes ``S3RawByteReader`` — an async iterator over the raw
object bytes stored in S3/MinIO. The compiler uses it instead of the
profiler-based path so that:

  - memory usage is constant regardless of file size (chunked streaming),
  - file integrity can be verified via the SHA-256 computed on the fly,
  - large file uploads (up to the configured ``upload_max_bytes``) succeed.

Usage::

    reader = S3RawByteReader(storage, object_key, max_bytes=200 * 1024 * 1024)
    async for chunk in reader:
        process(chunk)
    digest = reader.sha256_hex()
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.infrastructure.storage_client import ObjectStorageClient


@dataclass(frozen=True)
class S3ReadResult:
    """Summary of a streaming S3 read."""

    object_key: str
    bytes_read: int
    sha256_hex: str


class S3RawByteReader:
    """Async iterator over raw object bytes stored in S3-compatible storage.

    The reader:
      - streams bytes in fixed-size chunks (default 64 KiB),
      - enforces an upper bound on total bytes read (``max_bytes``),
      - computes a SHA-256 digest on the fly for content-addressed
        verification,
      - exposes ``sha256_hex()`` after the iterator is exhausted.

    The reader is intentionally synchronous over the boto3 streaming
    response. ``ObjectStorageClient.stream_object()`` returns a blocking
    iterator; this class wraps it in an ``AsyncIterator`` so callers can
    ``async for chunk in reader`` without blocking the event loop on the
    GIL-bound boto3 calls.
    """

    DEFAULT_CHUNK_SIZE = 64 * 1024  # 64 KiB
    DEFAULT_MAX_BYTES = 200 * 1024 * 1024  # 200 MiB (matches upload limit)

    def __init__(
        self,
        storage: ObjectStorageClient,
        object_key: str,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self._storage = storage
        self._object_key = object_key
        self._chunk_size = max(1, chunk_size)
        self._max_bytes = max(1, max_bytes)
        self._hasher = hashlib.sha256()
        self._bytes_read = 0
        self._exhausted = False

    @property
    def object_key(self) -> str:
        return self._object_key

    @property
    def bytes_read(self) -> int:
        return self._bytes_read

    def sha256_hex(self) -> str:
        """Return the SHA-256 hex digest of the bytes streamed so far."""
        return self._hasher.hexdigest()

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self

    async def __anext__(self) -> bytes:
        if self._exhausted:
            raise StopAsyncIteration

        # Lazily open the streaming response on first call. We do this
        # inside __anext__ rather than __init__ so creating the reader
        # is side-effect free and tests can construct readers without
        # an S3 connection.
        if not hasattr(self, "_stream"):
            self._stream = iter(
                await asyncio.to_thread(
                    self._storage.stream_object, self._object_key, self._chunk_size
                )
            )

        exhausted, chunk = await asyncio.to_thread(_next_chunk, self._stream)
        if exhausted:
            self._exhausted = True
            raise StopAsyncIteration

        if not isinstance(chunk, (bytes, bytearray)):
            # Some boto3 versions yield str when ``decode_responses`` is
            # enabled — coerce defensively to bytes.
            chunk = bytes(chunk)

        chunk = bytes(chunk)
        if not chunk:
            self._exhausted = True
            raise StopAsyncIteration

        # Enforce max_bytes — trims the final chunk if it would exceed.
        remaining = self._max_bytes - self._bytes_read
        if remaining <= 0:
            self._exhausted = True
            raise StopAsyncIteration
        if len(chunk) > remaining:
            chunk = chunk[:remaining]

        self._hasher.update(chunk)
        self._bytes_read += len(chunk)
        return chunk

    def read_result(self) -> S3ReadResult:
        """Build a ``S3ReadResult`` summary after iteration completes."""
        return S3ReadResult(
            object_key=self._object_key,
            bytes_read=self._bytes_read,
            sha256_hex=self.sha256_hex(),
        )


def _next_chunk(stream: Any) -> tuple[bool, Any]:
    """Advance a blocking boto3 iterator outside the event loop."""
    try:
        return False, next(stream)
    except StopIteration:
        return True, None


def _next_chunk(stream: Any) -> tuple[bool, Any]:
    """Advance a blocking boto3 iterator outside the event loop."""
    try:
        return False, next(stream)
    except StopIteration:
        return True, None


async def stream_to_digest(
    storage: ObjectStorageClient,
    object_key: str,
    *,
    max_bytes: int = S3RawByteReader.DEFAULT_MAX_BYTES,
) -> S3ReadResult:
    """Stream an S3 object to completion and return its read summary.

    Convenience wrapper for the common case where the caller only wants
    the SHA-256 and total byte count, not the per-chunk data.
    """
    reader = S3RawByteReader(storage, object_key, max_bytes=max_bytes)
    async for _ in reader:
        pass
    return reader.read_result()


__all__ = [
    "S3ReadResult",
    "S3RawByteReader",
    "stream_to_digest",
    "Any",
]
