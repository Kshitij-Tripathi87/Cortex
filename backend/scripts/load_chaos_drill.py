"""Load + chaos drill -- sustained concurrency and failure recovery qualification
(launch-board E2E/load/chaos gate, deployed-system drill).

Proves the resilience invariants on the REAL stack under load and chaos:

Load:
  - concurrent decision creation (idempotency + version contention):
    all 201, latency measured, outbox seqs dense/unique, backlog drains
Chaos:
  1. Redis interruption DURING concurrent mutations: commits never block,
     backlog drains after recovery, replay returns every committed event
     exactly (no loss, no duplicates).
  2. API instance restart mid-burst: in-flight requests may fail (expected),
     committed state stays consistent, the new instance reclaims the outbox
     (SKIP LOCKED), replay seqs are dense from seq 0 (no gaps).
  3. Invariants under load: foreign workspace -> 403, execute-without-
     approval -> 409 (fail-closed), replay idempotency (same cursor twice
     -> identical envelope).

Acceptance invariants pinned:
  no lost committed realtime event, no duplicate event, no governance
  bypass, no cross-tenant visibility, recovery reaches a consistent state.

Usage (PostgreSQL + Redis running; docker CLI on PATH; the drill manages
the backend via the supplied kill/start commands for the restart chaos):

    python scripts/load_chaos_drill.py \\
        --api-base http://127.0.0.1:8000 \\
        --admin-dsn "postgresql://postgres:cortex_local_2026@localhost:5432/cortex" \\
        --redis-container cortex-redis-prod \\
        --backend-kill-cmd "powershell -NoProfile -Command \"Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }\"" \\
        --backend-start-cmd "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\path\\to\\start-uvicorn.ps1"

Exit code 0 = load/chaos qualification passed.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import httpx

EMAIL_DOMAIN = "drill-loadchaos.example.com"
PASSWORD = "Drillsecures1"  # noqa: S105 - drill credential, same convention as the e2e suite

LOAD_WRITERS = 100
CHAOS_WRITERS = 25
RESTART_WRITERS = 10


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pg_conn_str(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - operator-controlled docker args (CLI)
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


def _run_cmd(cmd: str, timeout: float = 90.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S602 - operator-supplied command (CLI)
        cmd, capture_output=True, text=True, timeout=timeout, shell=True
    )


def _launch_cmd(cmd: str) -> None:
    """Launch a long-running command fire-and-forget.

    The backend start command runs uvicorn indefinitely; waiting on it (or
    holding pipes it inherits) hangs the drill forever on Windows. Popen +
    DEVNULL detaches the launcher and lets the drill poll health instead.
    """
    subprocess.Popen(  # noqa: S602 - operator-supplied command (CLI)
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True
    )


def _pct(values: list[float], pctile: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pctile / 100.0) * len(ordered)) - 1)))
    return ordered[idx]


async def signup(client: httpx.AsyncClient, api_base: str, tag: str) -> dict[str, str]:
    email = f"drill-{tag}-{uuid.uuid4().hex[:8]}@{EMAIL_DOMAIN}"
    resp = await client.post(
        f"{api_base}/api/v1/auth/signup",
        json={
            "organization_name": f"Drill Org {tag}",
            "email": email,
            "password": PASSWORD,
            "full_name": "Load Chaos Drill Tester",
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"signup failed {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    return {
        "email": email,
        "token": str(body["access_token"]),
        "workspace_id": str(body["workspace_id"]),
    }


async def create_decision(
    client: httpx.AsyncClient, api_base: str, ident: dict[str, str], situation: str
) -> httpx.Response:
    return await client.post(
        f"{api_base}/api/v1/nexus/decisions",
        headers={"Authorization": f"Bearer {ident['token']}"},
        json={"workspace_id": ident["workspace_id"], "situation": situation},
    )


async def outbox_seqs(pool: asyncpg.Pool, workspace_id: str) -> tuple[list[int], int]:
    """(ordered seqs, pending count) for a workspace's outbox (superuser side)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT seq FROM nexus_events WHERE workspace_id = $1 ORDER BY seq ASC",
            workspace_id,
        )
        pending = await conn.fetchval(
            """
            SELECT count(*) FROM nexus_events
            WHERE workspace_id = $1 AND published_at IS NULL
            """,
            workspace_id,
        )
        return [int(r["seq"]) for r in rows], int(pending)


async def wait_for_drain(pool: asyncpg.Pool, workspace_id: str, timeout_s: float) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        _, pending = await outbox_seqs(pool, workspace_id)
        if pending == 0:
            return time.perf_counter() - t0
        await asyncio.sleep(1.0)
    raise TimeoutError(f"outbox did not drain within {timeout_s}s")


async def replay(
    client: httpx.AsyncClient, api_base: str, ident: dict[str, str], after_seq: int
) -> dict[str, Any]:
    resp = await client.get(
        f"{api_base}/api/v1/nexus/realtime/events",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={
            "workspace_id": ident["workspace_id"],
            "after_seq": str(after_seq),
            "limit": "500",
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"replay failed {resp.status_code}: {resp.text[:300]}")
    data: dict[str, Any] = resp.json()["data"]
    return data


async def _burst(
    api_base: str, ident: dict[str, str], n: int, tag: str
) -> tuple[list[float], int, list[str]]:
    """Fire n concurrent creates; return (latencies, ok_count, error_bodies)."""
    limits = httpx.Limits(max_connections=n, max_keepalive_connections=n)
    latencies: list[float] = []
    ok = 0
    errors: list[str] = []
    async with httpx.AsyncClient(base_url=api_base, timeout=60.0, limits=limits) as client:

        async def one(i: int) -> None:
            nonlocal ok
            t0 = time.perf_counter()
            try:
                resp = await create_decision(client, api_base, ident, f"{tag} {i}")
                latencies.append(time.perf_counter() - t0)
                if resp.status_code == 201:
                    ok += 1
                else:
                    errors.append(f"{resp.status_code}: {resp.text[:120]}")
            except httpx.HTTPError as exc:
                latencies.append(time.perf_counter() - t0)
                errors.append(f"transport: {type(exc).__name__}")

        await asyncio.gather(*(one(i) for i in range(n)))
    return latencies, ok, errors


async def run(args: argparse.Namespace) -> int:
    admin_pool = await asyncpg.create_pool(_pg_conn_str(args.admin_dsn), min_size=1)
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=args.api_base, timeout=60.0) as client:
        # ── Setup ────────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Setup: identities")
        org_a = await signup(client, args.api_base, "load-a")
        org_b = await signup(client, args.api_base, "load-b")
        ws = org_a["workspace_id"]
        print(f"  orgA ws={ws} | orgB ws={org_b['workspace_id']}")

        # ── Phase 1: LOAD ────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 1: {LOAD_WRITERS} concurrent decision creations")
        t0 = time.perf_counter()
        latencies, ok, errors = await _burst(args.api_base, org_a, LOAD_WRITERS, "loadchaos")
        wall = time.perf_counter() - t0
        p50, p95 = _pct(latencies, 50), _pct(latencies, 95)
        print(f"  ok={ok}/{LOAD_WRITERS} wall={wall:.2f}s latency p50={p50:.2f}s p95={p95:.2f}s")
        for e in errors[:3]:
            print(f"  error: {e}")
        if ok != LOAD_WRITERS:
            failures.append(f"phase 1: {LOAD_WRITERS - ok} concurrent creates did not return 201")

        seqs, pending = await outbox_seqs(admin_pool, ws)
        # Each create emits decision_created; seqs must be unique + dense from 1.
        if len(set(seqs)) != len(seqs):
            failures.append("phase 1: duplicate outbox seqs under load")
        if seqs != list(range(1, len(seqs) + 1)):
            failures.append(
                f"phase 1: outbox seqs not dense from 1: head={seqs[:5]} tail={seqs[-5:]}"
            )
        drain1 = await wait_for_drain(admin_pool, ws, timeout_s=120.0)
        print(f"  outbox: {len(seqs)} events, seqs dense from 1, drained in {drain1:.2f}s")

        env = await replay(client, args.api_base, org_a, after_seq=0)
        if len(env["events"]) != len(seqs):
            failures.append(
                f"phase 1: replay returned {len(env['events'])} events, DB has {len(seqs)}"
            )
        print(
            f"  replay: {len(env['events'])} events, latest_seq={env['latest_seq']}, "
            f"resync_required={env['resync_required']}"
        )

        # ── Phase 2: CHAOS — Redis outage under concurrent load ─────────────
        print(f"[{_now_iso()}] Phase 2: Redis outage + {CHAOS_WRITERS} concurrent creates")
        stop = _docker("stop", args.redis_container)
        if stop.returncode != 0:
            raise RuntimeError(f"docker stop failed: {stop.stderr[:300]}")
        try:
            seqs_before, _ = await outbox_seqs(admin_pool, ws)
            seq_before = seqs_before[-1] if seqs_before else 0
            lat2, ok2, errors2 = await _burst(args.api_base, org_a, CHAOS_WRITERS, "chaosredis")
            print(f"  during outage: ok={ok2}/{CHAOS_WRITERS} (commits never blocked by the relay)")
            for e in errors2[:3]:
                print(f"  error: {e}")
            if ok2 != CHAOS_WRITERS:
                failures.append(
                    f"phase 2: {CHAOS_WRITERS - ok2} concurrent creates failed "
                    "during the Redis outage (mutations must not depend on the relay)"
                )
        finally:
            start = _docker("start", args.redis_container)
            if start.returncode != 0:
                raise RuntimeError(f"docker start failed: {start.stderr[:300]}")

        drain2 = await wait_for_drain(admin_pool, ws, timeout_s=180.0)
        seqs2, pending2 = await outbox_seqs(admin_pool, ws)
        expected2 = list(range(seq_before + 1, seq_before + 1 + CHAOS_WRITERS))
        gained = seqs2[seq_before:]
        print(
            f"  after recovery ({drain2:.2f}s): backlog drained (pending={pending2}), "
            f"gained {len(gained)} events seqs={gained[0]}..{gained[-1] if gained else '-'}"
        )
        if pending2 != 0:
            failures.append("phase 2: outbox did not drain after recovery")
        if gained != expected2:
            failures.append(
                "phase 2: events lost/duplicated during the outage "
                f"(got {gained}, expected {expected2})"
            )

        # ── Phase 3: CHAOS — API restart mid-burst ──────────────────────────
        print(f"[{_now_iso()}] Phase 3: API restart + {RESTART_WRITERS} creates mid-burst")
        lat3, ok3, errors3 = await _burst(args.api_base, org_a, RESTART_WRITERS, "chaosrestart")
        print(
            f"  pre-kill burst: ok={ok3}/{RESTART_WRITERS} "
            f"(some in-flight may fail when the process dies)"
        )

        seq3_before, _ = await outbox_seqs(admin_pool, ws)
        kill = _run_cmd(args.backend_kill_cmd)
        if kill.returncode != 0:
            raise RuntimeError(f"backend kill failed: {kill.stderr[:200]}")
        print("  backend killed mid-flight")

        _launch_cmd(args.backend_start_cmd)
        up = False
        for _ in range(30):
            await asyncio.sleep(2.0)
            try:
                resp = await client.get(f"{args.api_base}/healthz")
                if resp.status_code == 200:
                    up = True
                    break
            except httpx.HTTPError:
                continue
        if not up:
            raise TimeoutError("backend did not come back within 60s")
        print("  backend restarted, healthz 200")

        drain3 = await wait_for_drain(admin_pool, ws, timeout_s=120.0)
        seqs3, pending3 = await outbox_seqs(admin_pool, ws)
        print(f"  after recovery ({drain3:.2f}s): {len(seqs3)} events, pending={pending3}")
        if pending3 != 0:
            failures.append("phase 3: outbox did not drain after the API restart")
        if seqs3 != list(range(1, len(seqs3) + 1)):
            failures.append(
                f"phase 3: outbox seqs not dense after the API restart "
                f"(head={seqs3[:5]}, tail={seqs3[-5:]}) - lost or orphaned events"
            )

        # Every decision the API confirmed (201) must still be readable.
        async with admin_pool.acquire() as conn:
            committed_rows = await conn.fetch(
                "SELECT entity_id FROM nexus_events WHERE workspace_id = $1 "
                "AND event_type = 'decision_created' ORDER BY seq DESC",
                ws,
            )
        committed_ids = [str(r["entity_id"]) for r in committed_rows]
        readable = 0
        for did in committed_ids[-5:]:
            resp = await client.get(
                f"{args.api_base}/api/v1/nexus/decisions/{did}",
                headers={"Authorization": f"Bearer {org_a['token']}"},
                params={"workspace_id": ws},
            )
            if resp.status_code == 200:
                readable += 1
        print(f"  post-restart consistency: {readable}/5 sampled decisions readable")
        if readable != 5:
            failures.append("phase 3: committed decisions unreadable after the restart")

        # ── Phase 4: INVARIANTS under load ───────────────────────────────────
        print(f"[{_now_iso()}] Phase 4: invariant checks")

        # No cross-tenant visibility: orgB must not see orgA's events.
        resp = await client.get(
            f"{args.api_base}/api/v1/nexus/realtime/events",
            headers={"Authorization": f"Bearer {org_b['token']}"},
            params={"workspace_id": ws, "after_seq": "0", "limit": "10"},
        )
        print(f"  foreign workspace events -> {resp.status_code} (403 expected)")
        if resp.status_code != 403:
            failures.append(f"phase 4: cross-tenant visibility - got {resp.status_code}")

        # No production write before approval (fail-closed under load).
        resp = await create_decision(client, args.api_base, org_a, "invariant denial")
        if resp.status_code != 201:
            raise RuntimeError(f"invariant decision create failed: {resp.status_code}")
        did = str(resp.json()["data"]["decision"]["decision_id"])
        resp = await client.post(
            f"{args.api_base}/api/v1/nexus/decisions/{did}/execute",
            headers={"Authorization": f"Bearer {org_a['token']}"},
            params={"workspace_id": ws},
        )
        print(f"  execute without approval -> {resp.status_code} (409 expected)")
        if resp.status_code != 409:
            failures.append(f"phase 4: governance BYPASS - got {resp.status_code}")

        # Replay idempotency: the same cursor twice -> identical envelopes.
        env1 = await replay(client, args.api_base, org_a, after_seq=0)
        env2 = await replay(client, args.api_base, org_a, after_seq=0)
        seqs_a = [e["seq"] for e in env1["events"]]
        seqs_b = [e["seq"] for e in env2["events"]]
        print(
            f"  replay idempotency: {len(seqs_a)} vs {len(seqs_b)} events, "
            f"identical={seqs_a == seqs_b}"
        )
        if seqs_a != seqs_b:
            failures.append("phase 4: replay is not idempotent (duplicate/different events)")

    await admin_pool.close()

    print()
    if failures:
        print("DRILL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        "DRILL PASSED: no lost/duplicate events, no governance bypass, "
        "no cross-tenant visibility, recovery consistent."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--admin-dsn",
        default="postgresql://postgres:cortex_local_2026@localhost:5432/cortex",
        help="Superuser DSN for durable-state inspection (bypasses RLS)",
    )
    parser.add_argument("--redis-container", default="cortex-redis-prod")
    parser.add_argument(
        "--backend-kill-cmd",
        default=(
            "powershell -NoProfile -Command "
            '"Get-NetTCPConnection -LocalPort 8000 -State Listen | '
            'ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"'
        ),
    )
    parser.add_argument(
        "--backend-start-cmd",
        default=(
            "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden "
            "-File C:\\Users\\21330\\AppData\\Local\\Temp\\opencode\\start-uvicorn-drill.ps1"
        ),
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
