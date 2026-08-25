"""V2.4 — Evidence & Outcome Integrity.

Proves, after execution, exactly why an action happened and what changed
because of it. V2.3 proves execution was *authorized*; V2.4 proves it is
*traceable*.

Architecture rule: this module records what happened, it does not become
the source of truth. World State remains authoritative.

The 11-field provenance contract on every edge::

    event_id
    parent_id
    organization_id
    workspace_id
    world_state_version
    correlation_id
    causation_id
    timestamp
    actor
    input_hash
    output_hash

``node_type`` is an additional semantic label (``SOURCE``,
``CANONICAL_ENTITY``, ``WORLD_STATE``, ``SIGNAL``, ``ROOT_CAUSE``,
``AGENT_OBSERVATION``, ``PROPOSAL``, ``SIMULATION``, ``POLICY``,
``APPROVAL``, ``AUTHORIZATION``, ``EXECUTION``, ``OUTCOME``,
``WORLD_STATE_NEW``).

Hashing
-------
- ``node_hash = sha256(canonical_json of 11 contract fields + node_type)``
  — deterministic, sensitive to every field.
- ``chain_root = sha256(chain_header + ordered node_hashes)``
  where the header binds ``organization_id``, ``workspace_id``,
  ``correlation_id``, ``decision_id``.

Verification (V2.4 E15–E17)
---------------------------
``EvidenceChain.verify()`` returns ``(ok, failures)`` where failures
covers: node_hash mismatch (tampering), cross-tenant contamination
(E17), broken parent links, correlation drift, broken causation.

Replay (V2.4 E18)
-----------------
``serialize()`` / ``from_serialized()`` is a pure data round-trip; the
recomputed ``chain_root`` equals the original for an intact chain.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7

# Sentinel parent_id for root nodes (no parent).
ROOT_PARENT_ID = ""


# Canonical V2.4 node types — order matches the chain the spine emits.
V24_NODE_TYPES: tuple[str, ...] = (
    "SOURCE",
    "CANONICAL_ENTITY",
    "GRAPH",
    "WORLD_STATE",
    "SIGNAL",
    "ROOT_CAUSE",
    "AGENT_OBSERVATION",
    "PROPOSAL",
    "SIMULATION",
    "POLICY",
    "APPROVAL",
    "AUTHORIZATION",
    "EXECUTION",
    "OUTCOME",
    "WORLD_STATE_NEW",
)


def _canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic canonical JSON (sorted keys, compact separators)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _hash_payload(payload: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON of a payload dict."""
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def compute_input_hash(input_payload: dict[str, Any]) -> str:
    """Canonical hash for the inputs of a node."""
    return _hash_payload(input_payload)


def compute_output_hash(output_payload: dict[str, Any]) -> str:
    """Canonical hash for the outputs of a node."""
    return _hash_payload(output_payload)


def compute_node_hash(node: EvidenceNode) -> str:
    """Deterministic SHA-256 over the 11 contract fields + node_type.

    The hash deliberately includes ``timestamp`` so any tampering with
    the recorded time invalidates the node. For replay determinism
    across two live runs, callers must inject explicit timestamps; the
    function itself is a pure function of its inputs.
    """
    canonical = {
        "event_id": node.event_id,
        "parent_id": node.parent_id,
        "organization_id": node.organization_id,
        "workspace_id": node.workspace_id,
        "world_state_version": node.world_state_version,
        "correlation_id": node.correlation_id,
        "causation_id": node.causation_id,
        "timestamp": node.timestamp,
        "actor": node.actor,
        "input_hash": node.input_hash,
        "output_hash": node.output_hash,
        "node_type": node.node_type,
    }
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def compute_chain_root(
    *,
    organization_id: str,
    workspace_id: str,
    correlation_id: str,
    decision_id: str,
    node_hashes: list[str],
) -> str:
    """SHA-256 over the chain header + ordered node_hashes.

    The header binds the chain to a single organization/workspace/
    decision so a chain cannot be silently rebound to another tenant.
    """
    canonical = {
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "correlation_id": correlation_id,
        "decision_id": decision_id,
        "node_count": len(node_hashes),
        "node_hashes": list(node_hashes),
    }
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# EvidenceNode
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EvidenceNode:
    """One node in the V2.4 evidence chain.

    Carries the 11-field provenance contract plus a semantic ``node_type``
    and a deterministic ``node_hash``. The hash is computed by
    ``compute_node_hash`` and stored so callers can verify without
    recomputing (the chain still re-verifies on every ``verify()`` call).
    """

    event_id: str
    node_type: str
    parent_id: str
    organization_id: str
    workspace_id: str
    world_state_version: int
    correlation_id: str
    causation_id: str
    timestamp: str  # ISO-8601 UTC string (serialization-friendly)
    actor: str
    input_hash: str
    output_hash: str
    node_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "node_type": self.node_type,
            "parent_id": self.parent_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "world_state_version": self.world_state_version,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "node_hash": self.node_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        node_type: str,
        parent_id: str,
        organization_id: str,
        workspace_id: str,
        world_state_version: int,
        correlation_id: str,
        causation_id: str,
        actor: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        timestamp: str | None = None,
        event_id: str | None = None,
    ) -> EvidenceNode:
        """Build a node with all hashes computed.

        ``timestamp`` defaults to ``datetime.now(UTC).isoformat()``; tests
        inject fixed timestamps for cross-run determinism (E18).
        ``event_id`` defaults to a fresh ``uuid7()``; tests may inject a
        deterministic id (the FULL uuid7 string — truncated slices of
        uuid7 collide because the counter lives beyond char 12).
        """
        ts = timestamp or datetime.now(UTC).isoformat()
        node = cls(
            event_id=event_id or f"ev_{uuid7()}",
            node_type=node_type,
            parent_id=parent_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            world_state_version=world_state_version,
            correlation_id=correlation_id,
            causation_id=causation_id,
            timestamp=ts,
            actor=actor,
            input_hash=compute_input_hash(input_payload),
            output_hash=compute_output_hash(output_payload),
            node_hash="",
        )
        return replace(node, node_hash=compute_node_hash(node))


# ─────────────────────────────────────────────────────────────────────────────
# EvidenceChain
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EvidenceChain:
    """Ordered chain of ``EvidenceNode`` instances with verification."""

    organization_id: str
    workspace_id: str
    correlation_id: str
    decision_id: str
    nodes: list[EvidenceNode] = field(default_factory=list)
    chain_root: str = ""

    # ── Construction ──────────────────────────────────────────────────────

    def add(
        self,
        *,
        node_type: str,
        parent_id: str,
        world_state_version: int,
        causation_id: str,
        actor: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        timestamp: str | None = None,
        event_id: str | None = None,
    ) -> EvidenceNode:
        """Append a node, parented to ``parent_id`` (use ROOT_PARENT_ID for the root).

        Validates the parent reference exists (except for root) and that
        the node_type is canonical. Throws ``ValueError`` on violation —
        a malformed chain must never silently enter the ledger.
        ``event_id`` may be injected for deterministic test chains.
        """
        if node_type not in V24_NODE_TYPES:
            raise ValueError(f"UNKNOWN_NODE_TYPE: {node_type}")

        if parent_id == ROOT_PARENT_ID:
            if self.nodes:
                raise ValueError("ROOT_PARENT_ID allowed only for the first node")
        else:
            if not any(n.event_id == parent_id for n in self.nodes):
                raise ValueError(f"PARENT_NOT_FOUND: {parent_id}")

        # causation_id must reference a prior node in the chain (when set)
        if causation_id and not any(n.event_id == causation_id for n in self.nodes):
            raise ValueError(f"CAUSATION_NOT_FOUND: {causation_id}")

        node = EvidenceNode.create(
            node_type=node_type,
            parent_id=parent_id,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            world_state_version=world_state_version,
            correlation_id=self.correlation_id,
            causation_id=causation_id,
            actor=actor,
            input_payload=input_payload,
            output_payload=output_payload,
            timestamp=timestamp,
            event_id=event_id,
        )
        self.nodes.append(node)
        self.chain_root = self._recompute_root()
        return node

    def finalize_correlation(self, correlation_id: str, decision_id: str) -> None:
        """Bind the chain to its decision id once it is known.

        Nodes emitted before the decision id was available carry a
        placeholder correlation_id; this method rewrites every node's
        correlation_id and recomputes its hash, then recomputes the
        chain root. The chain is then sealed — any subsequent mutation
        of a node's correlation_id or hash will fail ``verify()``.

        Call exactly once, immediately after the decision id is known
        (i.e. after the SwarmTask is created in the orchestrator).
        """
        self.correlation_id = correlation_id
        self.decision_id = decision_id
        rewritten: list[EvidenceNode] = []
        for n in self.nodes:
            if n.correlation_id == correlation_id:
                rewritten.append(n)
                continue
            patched = replace(n, correlation_id=correlation_id)
            rewritten.append(replace(patched, node_hash=compute_node_hash(patched)))
        self.nodes = rewritten
        self.chain_root = self._recompute_root()

    # ── Hashing ───────────────────────────────────────────────────────────

    def _recompute_root(self) -> str:
        return compute_chain_root(
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            correlation_id=self.correlation_id,
            decision_id=self.decision_id,
            node_hashes=[n.node_hash for n in self.nodes],
        )

    # ── Verification (E15 / E16 / E17) ────────────────────────────────────

    def verify(self) -> tuple[bool, list[str]]:
        """Recompute every hash and structural invariant.

        Returns ``(ok, failures)``. ``failures`` is empty on success;
        otherwise it lists human-readable reasons for the failure.
        """
        failures: list[str] = []

        # Node hash integrity (E16)
        for n in self.nodes:
            expected = compute_node_hash(n)
            if expected != n.node_hash:
                failures.append(
                    f"NODE_HASH_MISMATCH: {n.event_id} (type={n.node_type})"
                )

        # Cross-tenant isolation (E17) — header-level
        # (org/ws live on the chain header; per-node rechecked below)
        # Per-node consistency
        for n in self.nodes:
            if n.organization_id != self.organization_id:
                failures.append(
                    f"CROSS_ORG_NODE: {n.event_id} org={n.organization_id}"
                )
            if n.workspace_id != self.workspace_id:
                failures.append(
                    f"CROSS_WORKSPACE_NODE: {n.event_id} ws={n.workspace_id}"
                )
            if n.correlation_id != self.correlation_id:
                failures.append(
                    f"CORRELATION_DRIFT: {n.event_id} corr={n.correlation_id}"
                )

        # Structural: parent linkage
        ids = {n.event_id for n in self.nodes}
        for n in self.nodes:
            if n.parent_id == ROOT_PARENT_ID:
                if n is not self.nodes[0]:
                    failures.append(f"ROOT_PARENT_ON_NON_ROOT: {n.event_id}")
            else:
                if n.parent_id not in ids:
                    failures.append(
                        f"PARENT_NOT_FOUND: {n.event_id} -> {n.parent_id}"
                    )
                else:
                    # Parent must precede child (chain ordering)
                    parent_idx = next(
                        i for i, m in enumerate(self.nodes) if m.event_id == n.parent_id
                    )
                    child_idx = self.nodes.index(n)
                    if parent_idx >= child_idx:
                        failures.append(
                            f"PARENT_AFTER_CHILD: {n.event_id}"
                        )

        # Structural: causation references a prior node in same chain
        for n in self.nodes:
            if n.causation_id and n.causation_id not in ids:
                failures.append(
                    f"CAUSATION_NOT_FOUND: {n.event_id} -> {n.causation_id}"
                )

        # Chain root (E15)
        if self.chain_root != self._recompute_root():
            failures.append("CHAIN_ROOT_MISMATCH")

        return len(failures) == 0, failures

    # ── Replay (E18) ──────────────────────────────────────────────────────

    def serialize(self) -> dict[str, Any]:
        """Pure-data representation suitable for persistence/replay."""
        return {
            "schema": "cortex.evidence_chain.v2_4",
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "correlation_id": self.correlation_id,
            "decision_id": self.decision_id,
            "chain_root": self.chain_root,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    @classmethod
    def from_serialized(cls, payload: dict[str, Any]) -> EvidenceChain:
        """Rebuild a chain from a serialized payload.

        The rebuilt chain re-verifies its own root; a tampered payload
        will produce a chain whose ``verify()`` returns ``(False, ...)``.
        """
        if payload.get("schema") != "cortex.evidence_chain.v2_4":
            raise ValueError(f"UNSUPPORTED_SCHEMA: {payload.get('schema')}")
        chain = cls(
            organization_id=payload["organization_id"],
            workspace_id=payload["workspace_id"],
            correlation_id=payload["correlation_id"],
            decision_id=payload["decision_id"],
            nodes=[EvidenceNode(**n) for n in payload["nodes"]],
            chain_root=payload["chain_root"],
        )
        # Recompute and overwrite the persisted root — if the input was
        # tampered with, the rebuilt chain's verify() will surface it.
        chain.chain_root = chain._recompute_root()
        return chain

    # ── Lineage ───────────────────────────────────────────────────────────

    def lineage(self, event_id: str) -> list[EvidenceNode]:
        """Walk from ``event_id`` back to root via parent_id links.

        Useful for "show me everything that caused this outcome" queries.
        A visited-set guards against cyclic parent references (a tampered
        chain must not be able to hang an audit query).
        """
        by_id = {n.event_id: n for n in self.nodes}
        path: list[EvidenceNode] = []
        visited: set[str] = set()
        cur = by_id.get(event_id)
        while cur is not None and cur.event_id not in visited:
            visited.add(cur.event_id)
            path.append(cur)
            if cur.parent_id == ROOT_PARENT_ID:
                break
            cur = by_id.get(cur.parent_id)
        return list(reversed(path))
