"""Observability drill -- controlled failures produce actionable signals
(launch-board observability gate, deployed-system drill).

Proves that deliberately induced failures are OBSERVABLE, not merely silent:

  1. BASELINE   -- /metrics scrape (outbox counters), /realtime/health healthy,
                   real API identity.
  2. REDIS OUTAGE -- stop Redis. A mutation MUST still commit (201). The
                   metrics MUST show the backlog (outbox_pending_count > 0,
                   outbox_publish_total{failure} incremented), /realtime/health
                   MUST degrade (redis unreachable), and the API log MUST
                   carry the failure with workspace/seq identifiers. Restore
                   Redis; the relay MUST drain (pending -> 0, health HEALTHY,
                   success counter incremented).
  3. FAIL-CLOSED STALE WRITE -- advance a decision against a stale
                   world_state_version. MUST 409, MUST durably mark the
                   decision STALE with a transition trail
                   (world_state_drift_detected_on_advance) + a
                   decision_invalidated outbox event served by replay.
  4. DENIAL AUDIT -- execute a decision without approval. MUST 409 (fail-
                   closed), MUST leave the decision unchanged, and the
                   denial MUST be durably audited (governance.transition_denied
                   with subject/actor/workspace identifiers).

Usage (backend API + PostgreSQL + Redis running; docker CLI on PATH):

    python scripts/observability_drill.py \\
        --api-base http://127.0.0.1:8000 \\
        --admin-dsn "postgresql://postgres:cortex_local_2026@localhost:5432/cortex" \\
        --redis-container cortex-redis-prod \\
        --api-log "C:\\path\\to\\uvicorn.log"

Exit code 0 = all failure signals actionable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import httpx

EMAIL_DOMAIN = "drill-observability.example.com"
PASSWORD = "Drillsecures1"  # noqa: S105 - drill credential, same convention as the e2e suite


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pg_conn_str(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def _docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - operator-controlled docker args (CLI)
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


def _read_log(path: str) -> str:
    """Read a log file with encoding auto-detection.

    PowerShell's ``*>`` redirect writes UTF-16LE (BOM); the drill must
    detect it or the UTF-8 decode turns the content into mojibake and the
    failure signatures are missed.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def _metric_value(metrics_text: str, name: str, labels: str | None = None) -> float:
    """Parse a Prometheus counter/gauge value (labels exact-match optional).

    A labeled counter that has never fired is absent from /metrics; an
    absent counter means 0 observations, so return 0.0.
    """
    pattern = (
        rf"^{re.escape(name)}\{{{re.escape(labels)}\}} ([\d.eE+]+)$"
        if labels is not None
        else rf"^{re.escape(name)} ([\d.eE+]+)$"
    )
    for line in metrics_text.splitlines():
        match = re.match(pattern, line)
        if match:
            return float(match.group(1))
    return 0.0


async def signup(client: httpx.AsyncClient, api_base: str, tag: str) -> dict[str, str]:
    email = f"drill-{tag}-{uuid.uuid4().hex[:8]}@{EMAIL_DOMAIN}"
    resp = await client.post(
        f"{api_base}/api/v1/auth/signup",
        json={
            "organization_name": f"Drill Org {tag}",
            "email": email,
            "password": PASSWORD,
            "full_name": "Observability Drill Tester",
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
    return str(resp.json()["data"]["decision"]["decision_id"])


async def get_decision(
    client: httpx.AsyncClient, api_base: str, ident: dict[str, str], decision_id: str
) -> dict[str, Any]:
    resp = await client.get(
        f"{api_base}/api/v1/nexus/decisions/{decision_id}",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={"workspace_id": ident["workspace_id"]},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"decision read failed {resp.status_code}: {resp.text[:300]}")
    decision: dict[str, Any] = resp.json()["data"]["decision"]
    return decision


async def realtime_health(
    client: httpx.AsyncClient, api_base: str, ident: dict[str, str]
) -> dict[str, Any]:
    resp = await client.get(
        f"{api_base}/api/v1/nexus/realtime/health",
        headers={"Authorization": f"Bearer {ident['token']}"},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"/realtime/health failed {resp.status_code}")
    data: dict[str, Any] = resp.json()["data"]
    return data


async def wait_for_drain(pool: asyncpg.Pool, workspace_id: str, timeout_s: float) -> float:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        async with pool.acquire() as conn:
            pending = await conn.fetchval(
                """
                SELECT count(*) FROM nexus_events
                WHERE workspace_id = $1 AND published_at IS NULL
                """,
                workspace_id,
            )
        if int(pending) == 0:
            return time.perf_counter() - t0
        await asyncio.sleep(1.0)
    raise TimeoutError(f"outbox did not drain within {timeout_s}s")


async def run(args: argparse.Namespace) -> int:
    admin_pool = await asyncpg.create_pool(_pg_conn_str(args.admin_dsn), min_size=1)
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=args.api_base, timeout=30.0) as client:
        # ── Phase 1: BASELINE ────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 1: baseline signals")
        ident = await signup(client, args.api_base, "obs")
        ws = ident["workspace_id"]
        m0 = (await client.get(f"{args.api_base}/metrics")).text
        succ0 = _metric_value(m0, "cortex_outbox_publish_total", 'result="success"')
        fail0 = _metric_value(m0, "cortex_outbox_publish_total", 'result="failure"')
        pending0 = _metric_value(m0, "cortex_outbox_pending_count")
        health0 = await realtime_health(client, args.api_base, ident)
        print(
            f"  metrics: publish_success={succ0:.0f} publish_failure={fail0:.0f} "
            f"pending={pending0:.0f} | health: outbox={health0['outbox']['status']} "
            f"redis={health0['redis']['status']}"
        )
        if pending0 != 0:
            failures.append(f"phase 1: outbox not drained at baseline (pending={pending0:.0f})")
        if health0["outbox"]["status"] != "HEALTHY":
            failures.append("phase 1: outbox health not HEALTHY at baseline")

        # ── Phase 2: REDIS OUTAGE ────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 2: Redis outage -- failure signals")
        stop = _docker("stop", args.redis_container)
        if stop.returncode != 0:
            raise RuntimeError(f"docker stop failed: {stop.stderr[:300]}")
        try:
            d1 = await create_decision(client, args.api_base, ident, "obs drill D1 (outage)")
            print(f"  mutation during outage -> 201 (D1={d1}, commit not blocked by relay)")

            # Let the relay attempt + fail, the sweep update the gauge, and the
            # health check notice the outage before scraping the signals.
            await asyncio.sleep(5.0)

            m1 = (await client.get(f"{args.api_base}/metrics")).text
            succ1 = _metric_value(m1, "cortex_outbox_publish_total", 'result="success"')
            fail1 = _metric_value(m1, "cortex_outbox_publish_total", 'result="failure"')
            pending1 = _metric_value(m1, "cortex_outbox_pending_count")
            print(
                f"  metrics under failure: pending={pending1:.0f} (>0 expected), "
                f"publish_failure={fail1:.0f} (was {fail0:.0f})"
            )
            if pending1 <= 0:
                failures.append("phase 2: outbox_pending_count did NOT rise during outage")
            if fail1 <= fail0:
                failures.append(
                    "phase 2: outbox_publish_total{failure} did NOT increment during outage"
                )

            # The Redis health probe caches "up" for 30s by design (ping-spam
            # avoidance) — wait past the cache window before expecting the
            # health endpoint to reflect the outage.
            await asyncio.sleep(32.0)

            health1 = await realtime_health(client, args.api_base, ident)
            print(
                f"  /realtime/health under failure: redis={health1['redis']['status']} "
                f"detail={health1['redis'].get('detail')}"
            )
            if health1["redis"]["status"] == "HEALTHY":
                failures.append("phase 2: redis health did NOT degrade during outage")

            if args.api_log:
                log_text = ""
                for _ in range(15):
                    await asyncio.sleep(2.0)
                    try:
                        log_text = _read_log(args.api_log)
                    except OSError:
                        continue
                    if "outbox publish failed" in log_text:
                        break
                has_ids = bool(re.search(r"outbox publish failed.*ws=" + re.escape(ws), log_text))
                print(f"  api log carries 'outbox publish failed' with ws id: {has_ids}")
                if "outbox publish failed" not in log_text:
                    failures.append("phase 2: api log does not carry the relay failure")
                elif not has_ids:
                    failures.append("phase 2: relay failure log lacks the workspace identifier")
        finally:
            start = _docker("start", args.redis_container)
            if start.returncode != 0:
                raise RuntimeError(f"docker start failed: {start.stderr[:300]}")

        drain2 = await wait_for_drain(admin_pool, ws, timeout_s=90.0)
        m2 = (await client.get(f"{args.api_base}/metrics")).text
        succ2 = _metric_value(m2, "cortex_outbox_publish_total", 'result="success"')
        pending2 = _metric_value(m2, "cortex_outbox_pending_count")
        health2 = await realtime_health(client, args.api_base, ident)
        print(
            f"  after recovery ({drain2:.2f}s): pending={pending2:.0f} "
            f"publish_success={succ2:.0f} (was {succ1:.0f}) | "
            f"redis={health2['redis']['status']} outbox={health2['outbox']['status']}"
        )
        if pending2 != 0:
            failures.append("phase 2: outbox did not drain after recovery")
        if succ2 <= succ1:
            failures.append(
                "phase 2: outbox_publish_total{success} did NOT increment after recovery"
            )
        if health2["redis"]["status"] != "HEALTHY" or health2["outbox"]["status"] != "HEALTHY":
            failures.append("phase 2: health not HEALTHY after recovery")

        # ── Phase 3: FAIL-CLOSED STALE WRITE ─────────────────────────────────
        print(f"[{_now_iso()}] Phase 3: fail-closed governed write (stale world state)")
        d2 = await create_decision(client, args.api_base, ident, "obs drill D2 (stale)")
        dec2 = await get_decision(client, args.api_base, ident, d2)
        print(f"  D2={d2} phase={dec2.get('phase')} ws_v={dec2.get('world_state_version')}")

        # Walk the governance lifecycle to AWAITING_APPROVAL — the staleness
        # guard applies to APPROVED/AUTHORIZED/EXECUTING targets, so the
        # stale advance must target "approved". Phase values are lowercase.
        async def _advance(target: str) -> httpx.Response:
            return await client.post(
                f"{args.api_base}/api/v1/nexus/decisions/{d2}/advance",
                headers={"Authorization": f"Bearer {ident['token']}"},
                params={"workspace_id": ident["workspace_id"]},
                json={"target_phase": target, "reason": "obs drill lifecycle walk"},
            )

        for step in ("simulated", "policy_checked", "awaiting_approval"):
            resp = await _advance(step)
            if resp.status_code != 200:
                failures.append(
                    f"phase 3: lifecycle walk to {step} returned {resp.status_code} "
                    f"(detail: {resp.text[:150]})"
                )
        dec_walked = await get_decision(client, args.api_base, ident, d2)
        print(f"  walked to phase: {dec_walked.get('phase')} (awaiting_approval expected)")

        resp = await client.post(
            f"{args.api_base}/api/v1/nexus/decisions/{d2}/advance",
            headers={"Authorization": f"Bearer {ident['token']}"},
            params={"workspace_id": ident["workspace_id"]},
            json={
                "target_phase": "approved",
                "reason": "obs drill: stale advance",
                "expected_world_state_version": 999,
                "expected_world_state_hash": "drill-stale-hash",
            },
        )
        print(f"  stale advance -> {resp.status_code} (409 expected)")
        if resp.status_code != 409:
            failures.append(
                f"phase 3: stale advance returned {resp.status_code}, not 409 "
                f"(detail: {resp.text[:200]})"
            )

        dec2b = await get_decision(client, args.api_base, ident, d2)
        print(f"  D2 phase after denial: {dec2b.get('phase')} (stale expected)")
        if dec2b.get("phase") != "stale":
            failures.append(
                f"phase 3: decision not durably marked stale (phase={dec2b.get('phase')})"
            )

        async with admin_pool.acquire() as conn:
            transition = await conn.fetchrow(
                """
                SELECT from_phase, to_phase, reason FROM nexus_decision_transitions
                WHERE decision_id = $1 AND reason = 'world_state_drift_detected_on_advance'
                """,
                d2,
            )
            invalidated = await conn.fetchval(
                """
                SELECT count(*) FROM nexus_events
                WHERE workspace_id = $1 AND event_type = 'decision_invalidated'
                  AND entity_id = $2
                """,
                ws,
                d2,
            )
        print(
            f"  durable transition trail: {dict(transition) if transition else None} | "
            f"decision_invalidated events: {invalidated}"
        )
        if transition is None:
            failures.append("phase 3: no durable STALE transition trail")
        if int(invalidated) < 1:
            failures.append("phase 3: no decision_invalidated outbox event")

        # ── Phase 4: DENIAL AUDIT ────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 4: governed denial audit (execute without approval)")
        d3 = await create_decision(client, args.api_base, ident, "obs drill D3 (denial)")
        resp = await client.post(
            f"{args.api_base}/api/v1/nexus/decisions/{d3}/execute",
            headers={"Authorization": f"Bearer {ident['token']}"},
            params={"workspace_id": ident["workspace_id"]},
        )
        print(f"  execute without approval -> {resp.status_code} (409 expected)")
        if resp.status_code != 409:
            failures.append(
                f"phase 4: execute-without-approval returned {resp.status_code}, not 409"
            )

        dec3 = await get_decision(client, args.api_base, ident, d3)
        print(f"  D3 phase after denial: {dec3.get('phase')} (unchanged expected)")
        if dec3.get("phase") == "EXECUTED":
            failures.append("phase 4: governance BYPASS - decision executed without approval")

        await asyncio.sleep(1.5)
        async with admin_pool.acquire() as conn:
            audit_row = await conn.fetchrow(
                """
                SELECT event_type, actor_id, subject_type, subject_id, workspace_id, payload
                FROM audit_events
                WHERE event_type = 'governance.transition_denied'
                  AND subject_id = $1
                ORDER BY occurred_at DESC
                LIMIT 1
                """,
                d3,
            )
        if audit_row is None:
            failures.append(
                "phase 4: governed denial NOT durably audited (no governance.transition_denied row)"
            )
        else:
            print(
                f"  denial audited: {audit_row['event_type']} actor={audit_row['actor_id']} "
                f"subject={audit_row['subject_id']} ws={audit_row['workspace_id']} "
                f"payload={json.dumps(audit_row['payload'])[:120]}"
            )

    await admin_pool.close()

    print()
    if failures:
        print("DRILL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("DRILL PASSED: all induced failures produced actionable, durable signals.")
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
        "--api-log",
        default=None,
        help="Path to the uvicorn log file (relay failure log check)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
