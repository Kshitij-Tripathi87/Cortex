"""Event Hashing — Pure Hash Utilities for the Event Kernel.

Program J (World State & Digital Twin) — invariant I2: hash-chained events.

This module is the single source of truth for:
- Canonicalizing a WorldEvent into a deterministic string
- Computing SHA-256 hashes
- Stable JSON encoding (sorted keys, no whitespace ambiguity)
- Per-event chain verification

Extracted from event_store.py so hashing is independently testable and
reusable by Twin (Layer 2), Simulation (Layer 3), and Knowledge (Layer 4).

Rules (per ADR-015):
✓ Pure functions — no DB, no I/O, no clock
✓ Canonical JSON (sort_keys=True, separators=(",", ":"))
✓ Excludes occurred_at and metadata so the hash is invariant to record-time
  and forward-compat metadata (same event semantics = same hash).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.modules.events.event_models import WorldEvent

HASH_ALGORITHM = "sha256"
HASH_HEX_LENGTH = 64


def stable_json(obj: Any) -> Any:
    """Convert dicts/lists to a JSON-safe form with stable key ordering.

    Recursively sorts dict keys. Lists preserve order. Primitive types pass
    through. Used to build deterministic canonical strings for hashing.
    """
    if isinstance(obj, dict):
        return {k: stable_json(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        return [stable_json(v) for v in obj]
    return obj


def canonicalize_event(event: WorldEvent, payload: dict[str, Any]) -> str:
    """Produce a canonical string representation of an event for hashing.

    Excludes occurred_at and metadata so the hash is invariant to the time
    the event was recorded and to forward-compatible metadata keys
    (experiment_id, policy_version, etc.). The hash represents event
    *semantics*, not transport metadata.
    """
    canonical = {
        "event_id": event.event_id,
        "world_id": event.world_id,
        "workspace_id": event.workspace_id,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "event_type": event.event_type.value,
        "payload": stable_json(payload),
        "caused_by_event_id": event.caused_by_event_id,
    }
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


def compute_event_hash(event: WorldEvent, payload: dict[str, Any]) -> str:
    """Compute the SHA-256 hex digest of a canonicalized event."""
    return hashlib.sha256(canonicalize_event(event, payload).encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Chain Verification (event_hash + prev_event_hash + sequence)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChainVerificationError:
    """Description of a chain-integrity failure.

    Returned (rather than raised) so a single verify() pass can report all
    failures, not just the first.
    """

    event_id: str
    error_code: str  # "hash_mismatch" | "chain_break" | "sequence_gap"
    expected: str | int | None
    actual: str | int | None


@dataclass(frozen=True)
class ChainVerificationResult:
    """Outcome of verifying a sequence of (event_hash, prev_event_hash, sequence) records."""

    is_valid: bool
    total_records: int
    verified_records: int
    errors: tuple[ChainVerificationError, ...]

    @property
    def first_error(self) -> ChainVerificationError | None:
        return self.errors[0] if self.errors else None


def verify_chain(
    records: list[tuple[str, str | None, int]],
) -> ChainVerificationResult:
    """Verify a list of (event_hash, prev_event_hash, sequence) triples.

    A pure function — no DB, no I/O. The caller supplies the stored hashes;
    this function checks the invariants:
    - sequence is strictly monotonic starting at 1
    - prev_event_hash of record N matches event_hash of record N-1
    - the first record has prev_event_hash == None
    """
    errors: list[ChainVerificationError] = []
    expected_sequence = 1
    prev_hash: str | None = None
    verified = 0

    for event_hash, prev_event_hash, sequence in records:
        event_id_marker = f"seq={sequence}" if event_hash == "" else f"hash={event_hash[:12]}"

        if prev_event_hash != prev_hash:
            errors.append(
                ChainVerificationError(
                    event_id=event_id_marker,
                    error_code="chain_break",
                    expected=prev_hash,
                    actual=prev_event_hash,
                )
            )
            return ChainVerificationResult(
                is_valid=False, total_records=len(records), verified_records=verified, errors=tuple(errors)
            )

        if sequence != expected_sequence:
            errors.append(
                ChainVerificationError(
                    event_id=event_id_marker,
                    error_code="sequence_gap",
                    expected=expected_sequence,
                    actual=sequence,
                )
            )
            return ChainVerificationResult(
                is_valid=False, total_records=len(records), verified_records=verified, errors=tuple(errors)
            )

        prev_hash = event_hash
        expected_sequence += 1
        verified += 1

    return ChainVerificationResult(
        is_valid=not errors,
        total_records=len(records),
        verified_records=verified,
        errors=tuple(errors),
    )
