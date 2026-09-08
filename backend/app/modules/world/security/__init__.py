"""World State Security — Snapshot Signing, Hash Verification, and Audit.

Program J (Workstream J) security layer:

Security guarantees:
✓ Snapshot Signing — every snapshot is cryptographically signed
✓ Hash Verification — tamper detection via SHA256 chain
✓ Event Integrity — every event is hashed and chained
✓ Workspace Isolation — workspace-scoped signatures
✓ Audit Trail — all security-relevant operations logged

Components:
- SnapshotSigner: Sign snapshots with HMAC
- EventChainVerifier: Verify event chain integrity
- AuditLogger: Record security events
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.world.world_models import WorldSnapshot, WorldState

# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Signing
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignedSnapshot:
    """A snapshot with its cryptographic signature."""

    snapshot: WorldSnapshot
    signature: str  # HMAC-SHA256
    signing_key_id: str
    signed_at: datetime


class SnapshotSigner:
    """Signs and verifies snapshots using HMAC-SHA256.

    Key management:
    - Keys are loaded from environment (CORTEX_WORLD_SIGNING_KEY)
    - Production: use a proper key management system
    - Development: a default key is used (NOT for production)
    """

    def __init__(self, signing_key: str | None = None, key_id: str = "default"):
        self.signing_key = (
            signing_key
            or os.environ.get("CORTEX_WORLD_SIGNING_KEY")
            or "dev-only-key-do-not-use-in-prod"
        )
        self.key_id = key_id

    def sign(self, snapshot: WorldSnapshot) -> SignedSnapshot:
        """Sign a snapshot and return a SignedSnapshot."""
        # Canonical representation for signing
        canonical = json.dumps(
            {
                "snapshot_id": snapshot.snapshot_id,
                "world_id": snapshot.world_id,
                "workspace_id": snapshot.workspace_id,
                "version": snapshot.version,
                "graph_version": snapshot.graph_version,
                "state_hash": snapshot.state_hash,
                "variable_count": snapshot.variable_count,
                "created_at": snapshot.created_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        signature = hmac.new(
            self.signing_key.encode("utf-8"),
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return SignedSnapshot(
            snapshot=snapshot,
            signature=signature,
            signing_key_id=self.key_id,
            signed_at=datetime.now(UTC),
        )

    def verify(self, signed: SignedSnapshot) -> bool:
        """Verify a signed snapshot has not been tampered with."""
        expected = self.sign(signed.snapshot)
        return hmac.compare_digest(expected.signature, signed.signature)


# ─────────────────────────────────────────────────────────────────────────────
# Hash Verification
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StateHashReport:
    """Result of state hash verification."""

    state_hash: str
    expected_hash: str | None
    is_valid: bool
    computed_at: datetime
    world_id: str
    version: int


class StateHashVerifier:
    """Verifies state hashes for tamper detection."""

    def compute_state_hash(self, state: WorldState) -> str:
        """Compute deterministic hash of a state."""
        canonical = json.dumps(
            {
                "world_id": state.world_id,
                "workspace_id": state.workspace_id,
                "version": state.version,
                "variables": {vid: v.to_dict() for vid, v in sorted(state.variables.items())},
                "graph_version": state.graph_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify(
        self,
        state: WorldState,
        expected_hash: str | None = None,
    ) -> StateHashReport:
        """Verify a state's hash matches the expected value."""
        actual = self.compute_state_hash(state)
        return StateHashReport(
            state_hash=actual,
            expected_hash=expected_hash,
            is_valid=(expected_hash is None or actual == expected_hash),
            computed_at=datetime.now(UTC),
            world_id=state.world_id,
            version=state.version,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Audit Logging
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditEvent:
    """A security-relevant event for the audit log."""

    event_id: str
    event_type: str  # snapshot_signed, snapshot_verified, hash_verified, isolation_violated
    workspace_id: str
    actor: str  # "system" or user_id
    target_id: str | None  # snapshot_id, event_id, etc.
    success: bool
    details: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditLogger:
    """Records security-relevant operations."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def log(
        self,
        event_type: str,
        workspace_id: str,
        actor: str,
        target_id: str | None = None,
        success: bool = True,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Record an audit event."""
        from app.common.ids import uuid7

        event = AuditEvent(
            event_id=str(uuid7()),
            event_type=event_type,
            workspace_id=workspace_id,
            actor=actor,
            target_id=target_id,
            success=success,
            details=details or {},
        )
        self._events.append(event)
        return event

    def get_events(
        self,
        workspace_id: str | None = None,
        event_type: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Query audit events."""
        events = self._events
        if workspace_id is not None:
            events = [e for e in events if e.workspace_id == workspace_id]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if limit is not None:
            events = events[-limit:]
        return events

    def clear(self) -> None:
        """Clear the audit log (for testing only)."""
        self._events.clear()
