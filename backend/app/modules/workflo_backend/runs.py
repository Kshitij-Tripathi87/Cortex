"""Workflo run store Ã¢â‚¬â€ run records, event streams, and reports.

A run is an auditable sequence: discover Ã¢â€ â€™ plan Ã¢â€ â€™ sandbox Ã¢â€ â€™ execute Ã¢â€ â€™ observe Ã¢â€ â€™
diagnose Ã¢â€ â€™ report. Every state transition appends an immutable, timestamped,
hash-chained event. Events are fanned out to SSE subscribers in real time.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.common.ids import uuid7


class RunNotFound(Exception):
    pass


@dataclass
class RunEvent:
    seq: int
    type: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    prev_hash: str = ""
    hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "message": self.message,
            "data": self.data,
            "ts": self.ts,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


@dataclass
class Run:
    id: str
    workspace_id: str
    name: str
    intent: str
    status: str = "created"
    sandbox_id: str | None = None
    plan: dict[str, Any] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    events: list[RunEvent] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    # Signed production receipt (dict form) — None for unresolved/legacy runs
    # and for policy-blocked runs (denials are audited, never receipted).
    receipt: dict[str, Any] | None = None
    _subscribers: list[asyncio.Queue[RunEvent]] = field(default_factory=list)

    def to_dict(self, include_events: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "intent": self.intent,
            "status": self.status,
            "sandbox_id": self.sandbox_id,
            "plan": self.plan,
            "findings": self.findings,
            "artifact_count": len(self.artifacts),
            "event_count": len(self.events),
            "created_at": self.created_at,
            "receipt": self.receipt,
        }
        if include_events:
            d["events"] = [e.to_dict() for e in self.events]
        return d


def _hash_event(prev: str, ev: RunEvent) -> str:
    payload = json.dumps(
        {
            "seq": ev.seq,
            "type": ev.type,
            "message": ev.message,
            "data": ev.data,
            "ts": ev.ts,
            "prev_hash": prev,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, workspace_id: str, name: str, intent: str) -> Run:
        run = Run(id=f"run_{uuid7()}", workspace_id=workspace_id, name=name, intent=intent)
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFound(f"run '{run_id}' not found")
        return run

    def append_event(
        self, run_id: str, type_: str, message: str, data: dict[str, Any] | None = None
    ) -> RunEvent:
        run = self.get(run_id)
        prev = run.events[-1].hash if run.events else ""
        ev = RunEvent(
            seq=len(run.events),
            type=type_,
            message=message,
            data=data or {},
            prev_hash=prev,
        )
        ev.hash = _hash_event(prev, ev)
        run.events.append(ev)
        for q in list(run._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)
        return ev

    async def subscribe(self, run_id: str) -> asyncio.Queue[RunEvent]:
        run = self.get(run_id)
        q: asyncio.Queue[RunEvent] = asyncio.Queue(maxsize=256)
        for ev in run.events:
            q.put_nowait(ev)
        run._subscribers.append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue[RunEvent]) -> None:
        run = self._runs.get(run_id)
        if run and q in run._subscribers:
            run._subscribers.remove(q)

    def set_artifacts(self, run_id: str, artifacts: list[dict[str, Any]]) -> None:
        self.get(run_id).artifacts = artifacts


def find_event(run: Run, type_: str) -> RunEvent | None:
    """Return the most recent event of ``type_`` in a run's hash-chained stream."""
    for ev in reversed(run.events):
        if ev.type == type_:
            return ev
    return None


def verify_event_chain(run: Run) -> tuple[bool, list[str]]:
    """Recompute the full hash chain across a run's lifecycle events.

    Each event's ``hash`` is recomputed from its own fields plus the previous
    event's hash; sequence continuity and linkage are checked. Tampering with
    any recorded message, payload, or timestamp breaks every subsequent link.
    """
    failures: list[str] = []
    prev = ""
    for index, ev in enumerate(run.events):
        if ev.seq != index:
            failures.append(f"EVENT_SEQ_GAP: recorded seq={ev.seq} at position {index}")
        if ev.prev_hash != prev:
            failures.append(f"EVENT_PREV_HASH_MISMATCH: seq={ev.seq}")
        expected = _hash_event(prev, ev)
        if ev.hash != expected:
            failures.append(f"EVENT_HASH_MISMATCH: seq={ev.seq} type={ev.type}")
        prev = ev.hash
    return len(failures) == 0, failures


_run_store: RunStore | None = None


def get_run_store() -> RunStore:
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store
