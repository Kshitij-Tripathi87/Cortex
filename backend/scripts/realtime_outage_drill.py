"""Realtime outage drill -- Redis interruption + outbox relay recovery qualification
(B4 launch-reliability gate, deployed-system drill).

Proves the durable-realtime failure contract end-to-end on the REAL stack:

    PG commit --> outbox --> relay --> Redis --> SSE/WS --> sequence gate

Phases:

  A. NORMAL   -- signup via the real API, create a decision (governed write),
                 verify the outbox drains (``published_at IS NULL`` count -> 0).
  B. OUTAGE   -- stop Redis. Make more decision mutations. Each MUST still
                 commit to PostgreSQL (201) because mutations never depend on
                 the relay; the outbox rows accumulate unpublished while the
                 committed state stays intact (dense seqs, no corruption).
  C. RECOVERY -- start Redis. The relay's retry/backoff must reconnect and
                 drain the backlog (pending -> 0). Measure the drain time.
  D. VERIFY   -- durable replay from the pre-outage cursor returns the missed
                 events with contiguous seqs; /realtime/health is healthy; the
                 final outbox is fully published.

Usage (backend API + PostgreSQL + Redis running; docker CLI on PATH):

    python scripts/realtime_outage_drill.py \\
        --api-base http://127.0.0.1:8000 \\
        --admin-dsn "postgresql://postgres:cortex_local_2026@localhost:5432/cortex" \\
        --redis-container cortex-redis-prod

Exit code 0 = drill passed (no loss, drain complete, replay exact).
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

EMAIL_DOMAIN = "drill-outage.example.com"
PASSWORD = "Drillsecures1"  # noqa: S105 - drill credential, same convention as the e2e suite


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pg_conn_str(dsn: str) -> str:
    """postgresql://user:pw@host:port/db (asyncpg accepts this form directly)."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - operator-controlled docker args (CLI)
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


async def outbox_stats(pool: asyncpg.Pool, workspace_id: str) -> tuple[int, int, int | None]:
    """(total, pending, latest_seq) for a workspace's outbox rows.

    Runs as the PostgreSQL superuser: this is the observability side of the
    drill, which must see every row regardless of tenant RLS.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE published_at IS NULL) AS pending,
                   max(seq) AS latest_seq
            FROM nexus_events
            WHERE workspace_id = $1
            """,
            workspace_id,
        )
        return (
            int(row["total"]),
            int(row["pending"]),
            (int(row["latest_seq"]) if row["latest_seq"] is not None else None),
        )


async def wait_for_drain(pool: asyncpg.Pool, workspace_id: str, timeout_s: float) -> float:
    """Poll until pending == 0; return elapsed seconds. Raises on timeout."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        _, pending, _ = await outbox_stats(pool, workspace_id)
        if pending == 0:
            return time.perf_counter() - t0
        await asyncio.sleep(1.0)
    raise TimeoutError(f"outbox did not drain within {timeout_s}s")


async def signup(client: httpx.AsyncClient, api_base: str, tag: str) -> dict[str, str]:
    email = f"drill-{tag}-{uuid.uuid4().hex[:8]}@{EMAIL_DOMAIN}"
    resp = await client.post(
        f"{api_base}/api/v1/auth/signup",
        json={
            "organization_name": f"Drill Org {tag}",
            "email": email,
            "password": PASSWORD,
            "full_name": "Outage Drill Tester",
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
) -> str:
    resp = await client.post(
        f"{api_base}/api/v1/nexus/decisions",
        headers={"Authorization": f"Bearer {ident['token']}"},
        json={"workspace_id": ident["workspace_id"], "situation": situation},
    )
    if resp.status_code != 201:
        raise RuntimeError(f"decision create failed {resp.status_code}: {resp.text[:300]}")
    decision_id = str(resp.json()["data"]["decision"]["decision_id"])
    if not decision_id:
        raise RuntimeError("decision create returned no decision_id")
    return decision_id


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


# ─────────────────────────────────────────────────────────────────────────────
# Drill
# ─────────────────────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> int:
    admin_pool = await asyncpg.create_pool(_pg_conn_str(args.admin_dsn), min_size=1)
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=args.api_base, timeout=30.0) as client:
        # ── Phase A: NORMAL ──────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase A: normal operations")
        ident = await signup(client, args.api_base, "outage")
        ws = ident["workspace_id"]
        d1 = await create_decision(client, args.api_base, ident, "drill D1 (normal)")
        drain_a = await wait_for_drain(admin_pool, ws, timeout_s=30.0)
        total_a, pending_a, latest_a = await outbox_stats(admin_pool, ws)
        print(
            f"  decision D1={d1} | outbox total={total_a} pending={pending_a} "
            f"latest_seq={latest_a} | drained in {drain_a:.2f}s"
        )
        if pending_a != 0:
            failures.append(f"phase A: outbox not drained (pending={pending_a})")
        assert latest_a is not None, "phase A: no outbox rows for the workspace"

        # ── Phase B: OUTAGE ──────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase B: stopping Redis ({args.redis_container})")
        t_outage = time.perf_counter()
        stop = _docker("stop", args.redis_container)
        if stop.returncode != 0:
            raise RuntimeError(f"docker stop failed: {stop.stderr[:300]}")
        print(f"  Redis stopped ({time.perf_counter() - t_outage:.2f}s)")

        outage_dids: list[str] = []
        for i in range(2, 4):
            did = await create_decision(client, args.api_base, ident, f"drill D{i} (during outage)")
            outage_dids.append(did)
            print(f"  decision D{i}={did} -> 201 (mutation committed without relay)")

        total_b, pending_b, latest_b = await outbox_stats(admin_pool, ws)
        print(
            f"  outbox during outage: total={total_b} pending={pending_b} "
            f"latest_seq={latest_b} (unpublished backlog = {pending_b})"
        )
        if pending_b != 2:
            failures.append(f"phase B: expected 2 unpublished outbox rows, got {pending_b}")
        if latest_b is None or latest_b != latest_a + 2:
            failures.append(
                f"phase B: seq not dense after outage (before={latest_a}, after={latest_b})"
            )

        # Committed state must be intact: decisions readable via the API.
        for did in outage_dids:
            resp = await client.get(
                f"{args.api_base}/api/v1/nexus/decisions/{did}",
                headers={"Authorization": f"Bearer {ident['token']}"},
                params={"workspace_id": ident["workspace_id"]},
            )
            if resp.status_code != 200:
                failures.append(
                    f"phase B: committed decision {did} unreadable ({resp.status_code})"
                )
        print(f"  committed PostgreSQL state intact: {len(outage_dids)} decisions readable")

        # ── Phase C: RECOVERY ────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase C: restarting Redis")
        t_recover = time.perf_counter()
        start = _docker("start", args.redis_container)
        if start.returncode != 0:
            raise RuntimeError(f"docker start failed: {start.stderr[:300]}")
        drain_c = await wait_for_drain(admin_pool, ws, timeout_s=90.0)
        print(
            f"  Redis restarted ({time.perf_counter() - t_recover:.2f}s); "
            f"backlog drained in {drain_c:.2f}s"
        )

        total_c, pending_c, latest_c = await outbox_stats(admin_pool, ws)
        print(f"  outbox after recovery: total={total_c} pending={pending_c} latest_seq={latest_c}")
        if pending_c != 0:
            failures.append(f"phase C: outbox not drained after recovery (pending={pending_c})")
        assert latest_c is not None, "phase C: no outbox rows after recovery"

        # ── Phase D: VERIFY replay/resync ────────────────────────────────────
        print(f"[{_now_iso()}] Phase D: durable replay from the pre-outage cursor")
        env = await replay(client, args.api_base, ident, after_seq=latest_a)
        events = env["events"]
        seqs = [e["seq"] for e in events]
        types = [e.get("event_type") or e.get("type") for e in events]
        print(
            f"  replayed {len(events)} events seqs={seqs} types={types} "
            f"latest_seq={env['latest_seq']} resync_required={env['resync_required']}"
        )
        if seqs != list(range(latest_a + 1, latest_c + 1)):
            failures.append(
                f"phase D: replay seqs not contiguous/complete: {seqs} "
                f"(expected {list(range(latest_a + 1, latest_c + 1))})"
            )
        if env["resync_required"]:
            failures.append("phase D: replay demanded a resync for a small gap")
        if env["latest_seq"] != latest_c:
            failures.append(f"phase D: replay latest_seq {env['latest_seq']} != DB {latest_c}")

        # Relay health must be healthy after recovery.
        resp = await client.get(
            f"{args.api_base}/api/v1/nexus/realtime/health",
            headers={"Authorization": f"Bearer {ident['token']}"},
        )
        health = resp.json().get("data", {}) if resp.status_code == 200 else {}
        print(f"  /realtime/health: {resp.status_code} {health}")
        if resp.status_code != 200:
            failures.append(f"phase D: /realtime/health {resp.status_code}")

    await admin_pool.close()

    print()
    if failures:
        print("DRILL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("DRILL PASSED: no loss, drain complete, replay exact.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--admin-dsn",
        default="postgresql://postgres:cortex_local_2026@localhost:5432/cortex",
        help="Superuser DSN for outbox inspection (sees all rows, bypasses RLS)",
    )
    parser.add_argument("--redis-container", default="cortex-redis-prod")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
