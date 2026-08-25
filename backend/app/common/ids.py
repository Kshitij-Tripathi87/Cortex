"""UUID v7 generation — time-sortable identifiers per the architecture spec."""

from __future__ import annotations

import os
import time
import uuid

_last_ms: int = 0
_counter: int = 0


def uuid7() -> str:
    """Generate a UUIDv7-style time-sortable UUID as a string.

    Layout: 48-bit unix-ms timestamp | 12-bit counter | 4-bit version(7) | 62-bit random.
    This gives monotonic ordering within a process, which is sufficient
    for Cortex's time-sortable canonical ids.
    """
    global _last_ms, _counter

    now_ms = int(time.time() * 1000)
    if now_ms <= _last_ms:
        _counter += 1
    else:
        _counter = 0
        _last_ms = now_ms

    counter = _counter & 0xFFF
    rand_bits = os.urandom(8)
    rand_int = int.from_bytes(rand_bits, "big") & 0x3FFFFFFFFFFFFFFF

    uuid_int = (now_ms & 0xFFFFFFFFFFFF) << 80
    uuid_int |= counter << 68
    uuid_int |= 0x7 << 64  # version 7
    uuid_int |= rand_int

    h = f"{uuid_int:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def uuid7_uuid() -> uuid.UUID:
    """Variant of uuid7() that returns a uuid.UUID object instead of str.

    Used by MVP wedge tables whose columns are native PostgreSQL UUID
    (as_uuid=True) per ADR-0001. The string-typed uuid7() remains the
    default for existing tables that use String(36) PKs.
    """
    return uuid.UUID(uuid7())
