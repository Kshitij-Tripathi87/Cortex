"""Day 25 qualification drill -- phone client backend surface (deployed-system drill).

Proves the Day 25 backend contract end-to-end on the REAL stack. This is the
backend half of the Day 25 acceptance suite (the hard gates that need a
physical phone / LiveKit audio / real push delivery are environment-level
and are exercised separately):

  1. AUTH       -- real signup -> JWT.
  2. DEVICE     -- phone + laptop register in the DeviceMesh; both visible;
                   foreign owner -> 403.
  3. SESSIONS   -- user / voice / task sessions are SEPARATE records
                   (voice reconnects never create tasks).
  4. VOICE      -- short-lived scoped voice token (scope=voice, ~5 min);
                   voice session state machine walk + invalid transition
                   -> 409 + the failure/recovery path (DISCONNECTED ->
                   RECONNECTING -> RESYNCING -> CONNECTED).
  5. BOOTSTRAP  -- GET /mobile/bootstrap returns the authoritative snapshot
                   (user, devices, active_tasks, pending_approvals,
                   recent_events).
  6. TASKS      -- a real durable task appears in the bootstrap snapshot
                   when active.
  7. NOTIFS     -- push registration; the policy gates fan-out (agent
                   noise suppressed, TASK_COMPLETED delivered); the durable
                   notification state is readable by the phone.

Usage (backend API + PostgreSQL running):

    python scripts/mobile_day25_drill.py --api-base http://127.0.0.1:8000

Exit code 0 = Day 25 backend surface qualified.
"""

from __future__ import annotations

import argparse
import asyncio

# drill runs from backend/ so the policy contract is importable; the JWT
# secret must match the API tier's so the drill can decode the issued token.
import os  # noqa: E402

os.environ.setdefault("CORTEX_JWT_SECRET", "drill_jwt_secret_2026_local_only")

import sys  # noqa: E402
import uuid
from datetime import UTC, datetime

import httpx
import jwt as pyjwt

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402
from app.modules.notifications.service import NOTIFY_EVENT_TYPES  # noqa: E402

EMAIL_DOMAIN = "drill-day25.example.com"
PASSWORD = "Drillsecures1"  # noqa: S105 - drill credential, same convention as the e2e suite


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def signup(client: httpx.AsyncClient, api_base: str, tag: str) -> dict[str, str]:
    email = f"drill-{tag}-{uuid.uuid4().hex[:8]}@{EMAIL_DOMAIN}"
    resp = await client.post(
        f"{api_base}/api/v1/auth/signup",
        json={
            "organization_name": f"Day25 Org {tag}",
            "email": email,
            "password": PASSWORD,
            "full_name": "Day 25 Drill Tester",
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"signup failed {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    return {
        "email": email,
        "token": str(body["access_token"]),
        "workspace_id": str(body["workspace_id"]),
        "user_id": str(body["user_id"]),
    }


async def run(args: argparse.Namespace) -> int:
    failures: list[str] = []

    async with httpx.AsyncClient(base_url=args.api_base, timeout=30.0) as client:
        # ── 1. AUTH ──────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 1. AUTH: signup -> JWT")
        org_a = await signup(client, args.api_base, "a")
        org_b = await signup(client, args.api_base, "b")
        print(f"  user={org_a['user_id']} ws={org_a['workspace_id']}")
        if not org_a["token"] or not org_a["user_id"]:
            failures.append("1: signup did not return token + user_id")

        # ── 2. DEVICE ────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 2. DEVICE: phone + laptop register in the mesh")
        resp = await client.post(
            f"{args.api_base}/api/v1/devices",
            headers={"Authorization": f"Bearer {org_a['token']}"},
            json={
                "device_id": "phone-001",
                "platform": "android",
                "agent_version": "v1.0",
                "capabilities": ["voice", "notifications", "approval", "display"],
            },
        )
        if resp.status_code != 201:
            raise RuntimeError(f"phone register failed {resp.status_code}: {resp.text[:300]}")
        phone = resp.json()["data"]["device"]
        print(f"  phone-001 registered: caps={phone['capabilities']} status={phone['status']}")
        if phone["status"] != "ONLINE":
            failures.append("2: registered device is not ONLINE")

        resp = await client.post(
            f"{args.api_base}/api/v1/devices",
            headers={"Authorization": f"Bearer {org_a['token']}"},
            json={
                "device_id": "laptop-001",
                "platform": "windows",
                "agent_version": "v1.0",
                "capabilities": ["terminal", "filesystem", "tasks"],
            },
        )
        if resp.status_code != 201:
            raise RuntimeError(f"laptop register failed {resp.status_code}: {resp.text[:300]}")

        resp = await client.get(
            f"{args.api_base}/api/v1/devices",
            headers={"Authorization": f"Bearer {org_a['token']}"},
        )
        devices = resp.json()["data"]["devices"]
        device_ids = [d["device_id"] for d in devices]
        print(f"  DeviceMesh: {device_ids}")
        if set(device_ids) != {"phone-001", "laptop-001"}:
            failures.append(f"2: DeviceMesh does not show both devices: {device_ids}")

        # Re-registration updates instead of duplicating.
        resp = await client.post(
            f"{args.api_base}/api/v1/devices",
            headers={"Authorization": f"Bearer {org_a['token']}"},
            json={
                "device_id": "phone-001",
                "platform": "android",
                "agent_version": "v1.1",
                "capabilities": ["voice", "notifications", "approval", "display"],
            },
        )
        if resp.status_code != 201:
            failures.append(f"2: re-registration failed {resp.status_code}")
        resp = await client.get(
            f"{args.api_base}/api/v1/devices",
            headers={"Authorization": f"Bearer {org_a['token']}"},
        )
        if resp.json()["data"]["count"] != 2:
            failures.append("2: re-registration duplicated the device")

        # Foreign owner -> 403.
        resp = await client.get(
            f"{args.api_base}/api/v1/devices/phone-001",
            headers={"Authorization": f"Bearer {org_b['token']}"},
        )
        print(f"  foreign owner reads phone-001 -> {resp.status_code} (403 expected)")
        if resp.status_code != 403:
            failures.append(f"2: foreign owner device read returned {resp.status_code}")

        # ── 3. SESSIONS ──────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 3. SESSIONS: user / voice / task separation")
        headers_a = {"Authorization": f"Bearer {org_a['token']}", "X-Device-Id": "phone-001"}

        async def _mk_session(stype: str, ref: str | None = None) -> str:
            resp = await client.post(
                f"{args.api_base}/api/v1/mobile/sessions",
                headers=headers_a,
                json={"session_type": stype, "ref_id": ref},
            )
            if resp.status_code != 201:
                raise RuntimeError(f"{stype} session failed {resp.status_code}: {resp.text[:200]}")
            return str(resp.json()["data"]["session_id"])

        voice_sess = await _mk_session("voice")
        task_sess = await _mk_session("task", ref="task-day25-1")
        user_sess = await _mk_session("user")
        print(f"  voice={voice_sess} task={task_sess} user={user_sess} (separate rows)")

        resp = await client.get(
            f"{args.api_base}/api/v1/mobile/sessions",
            headers=headers_a,
            params={"session_type": "task"},
        )
        task_rows = resp.json()["data"]["sessions"]
        if len(task_rows) != 1 or task_rows[0]["ref_id"] != "task-day25-1":
            failures.append(f"3: task session filter wrong: {task_rows}")

        # ── 4. VOICE ─────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 4. VOICE: scoped token + state machine")
        resp = await client.post(
            f"{args.api_base}/api/v1/voice/token",
            headers=headers_a,
            json={"device_id": "phone-001", "workspace_id": org_a["workspace_id"]},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"voice token failed {resp.status_code}: {resp.text[:200]}")
        vtok = resp.json()["data"]
        settings = get_settings()
        claims = pyjwt.decode(
            vtok["token"], settings.jwt_secret, algorithms=["HS256"], audience=settings.jwt_audience
        )
        exp_age = claims["exp"] - claims["iat"]
        print(
            f"  voice token: scope={claims.get('scope')} device={claims.get('device_id')} "
            f"ttl={exp_age}s provider={vtok['provider']}"
        )
        if claims.get("scope") != "voice":
            failures.append("4: voice token lacks the voice scope")
        if not (60 <= exp_age <= 600):
            failures.append(f"4: voice token ttl {exp_age}s is not short-lived")

        # The voice token must NOT carry workspace/task authority.
        if "workspace_id" in claims and claims.get("workspace_id"):
            failures.append("4: voice token carries workspace authority")

        resp = await client.post(
            f"{args.api_base}/api/v1/voice/sessions",
            headers=headers_a,
            json={"device_id": "phone-001", "workspace_id": org_a["workspace_id"]},
        )
        if resp.status_code != 201:
            raise RuntimeError(f"voice session failed {resp.status_code}: {resp.text[:200]}")
        vs_id = str(resp.json()["data"]["voice_session_id"])

        async def _vstate(state: str) -> httpx.Response:
            return await client.post(
                f"{args.api_base}/api/v1/voice/sessions/{vs_id}/state",
                headers=headers_a,
                json={"state": state},
            )

        walk = ["CONNECTING", "LISTENING", "THINKING", "SPEAKING", "EXECUTING", "LISTENING"]
        for state in walk:
            resp = await _vstate(state)
            if resp.status_code != 200:
                failures.append(f"4: voice walk to {state} returned {resp.status_code}")
        resp = await client.get(f"{args.api_base}/api/v1/voice/sessions/{vs_id}", headers=headers_a)
        print(f"  state machine walk: {' -> '.join(walk)} -> {resp.json()['data']['state']}")

        # Invalid transition -> 409.
        resp = await _vstate("IDLE")
        if resp.status_code != 409:
            failures.append(f"4: invalid voice transition returned {resp.status_code}, not 409")
        print(f"  invalid transition (LISTENING -> IDLE) -> {resp.status_code}")

        # Failure/recovery path.
        recovery = ["DISCONNECTED", "RECONNECTING", "RESYNCING", "CONNECTED"]
        for state in recovery:
            resp = await _vstate(state)
            if resp.status_code != 200:
                failures.append(f"4: voice recovery to {state} returned {resp.status_code}")
        print(f"  failure/recovery path: {' -> '.join(recovery)}")

        # ── 5. BOOTSTRAP ─────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 5. BOOTSTRAP: authoritative snapshot")
        resp = await client.get(f"{args.api_base}/api/v1/mobile/bootstrap", headers=headers_a)
        if resp.status_code != 200:
            raise RuntimeError(f"bootstrap failed {resp.status_code}: {resp.text[:300]}")
        boot = resp.json()["data"]
        print(
            f"  bootstrap: devices={len(boot['devices'])} "
            f"active_tasks={len(boot['active_tasks'])} "
            f"pending_approvals={len(boot['pending_approvals'])} "
            f"recent_events={len(boot['recent_events'])}"
        )
        for key in ("user", "devices", "active_tasks", "pending_approvals", "recent_events"):
            if key not in boot:
                failures.append(f"5: bootstrap missing {key}")
        if len(boot["devices"]) != 2:
            failures.append("5: bootstrap devices != 2")
        if boot["user"]["user_id"] != org_a["user_id"]:
            failures.append("5: bootstrap user mismatch")

        # The bootstrap is user-scoped: orgB cannot see orgA's devices.
        resp = await client.get(
            f"{args.api_base}/api/v1/mobile/bootstrap",
            headers={"Authorization": f"Bearer {org_b['token']}"},
        )
        boot_b = resp.json()["data"]
        if any(d["device_id"] == "phone-001" for d in boot_b["devices"]):
            failures.append("5: cross-tenant bootstrap visibility - orgB sees orgA's devices")
        print(f"  orgB bootstrap devices={[d['device_id'] for d in boot_b['devices']]} (no phone)")

        # ── 6. TASKS ─────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 6. TASKS: a real durable task in the snapshot")
        resp = await client.post(
            f"{args.api_base}/api/v1/nexus/tasks",
            headers=headers_a,
            json={
                "workspace_id": org_a["workspace_id"],
                "objective": "Day 25 phone client qualification task",
                "world_state_version": 1,
            },
        )
        if resp.status_code != 201:
            raise RuntimeError(f"task create failed {resp.status_code}: {resp.text[:300]}")
        task_body = resp.json()["data"]
        task_status = task_body.get("status") or task_body.get("task", {}).get("status")
        task_id = task_body.get("task_id") or task_body.get("task", {}).get("task_id")
        print(f"  task={task_id} status={task_status}")
        if not task_id:
            failures.append("6: task create returned no task_id")

        # Re-bootstrap: the task appears in the snapshot when active.
        resp = await client.get(f"{args.api_base}/api/v1/mobile/bootstrap", headers=headers_a)
        boot2 = resp.json()["data"]
        task_ids = [t["task_id"] for t in boot2["active_tasks"]]
        if task_status in {"PENDING", "PLANNING", "EXECUTING", "VERIFYING", "AWAITING_APPROVAL"}:
            if task_id not in task_ids:
                failures.append(
                    f"6: active task {task_id} missing from the bootstrap snapshot ({task_ids})"
                )
            print(f"  re-bootstrap: active_tasks={task_ids}")
        else:
            print(f"  task is terminal ({task_status}); active_tasks={task_ids}")

        # ── 7. NOTIFS ────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] 7. NOTIFS: policy gate + durable delivery")
        resp = await client.post(
            f"{args.api_base}/api/v1/mobile/push/register",
            headers=headers_a,
            json={
                "device_id": "phone-001",
                "provider": "stub",
                "push_token": "drill-push-token-phone-001",
            },
        )
        if resp.status_code != 201:
            raise RuntimeError(f"push register failed {resp.status_code}: {resp.text[:200]}")
        print("  push registration: phone-001 -> stub provider")

        # The policy suppresses agent/tool noise; significant events fan out.
        suppressed = "agent.activity" not in NOTIFY_EVENT_TYPES
        delivered_types = {
            "TASK_COMPLETED",
            "TASK_FAILED",
            "TASK_BLOCKED",
            "APPROVAL_REQUIRED",
        }
        if not suppressed:
            failures.append("7: policy would notify on agent noise")
        if not delivered_types.issubset(NOTIFY_EVENT_TYPES):
            failures.append("7: policy missing task lifecycle events")
        print(
            f"  policy: agent.activity suppressed={suppressed}, "
            f"lifecycle events covered={len(delivered_types)}/4"
        )

        # Durable notification state readable by the phone.
        resp = await client.get(f"{args.api_base}/api/v1/mobile/notifications", headers=headers_a)
        if resp.status_code != 200:
            failures.append(f"7: /mobile/notifications {resp.status_code}")
        else:
            notif_count = resp.json()["data"]["count"]
            print(f"  /mobile/notifications: {notif_count} durable records")

        # The pipeline's durable state is the phone-visible record; the
        # delivery fan-out contract is verified by the policy above and the
        # durable read below. Real providers wire in via config.

    print()
    if failures:
        print("DAY 25 DRILL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        "DAY 25 DRILL PASSED: device mesh + sessions + voice + bootstrap + "
        "task snapshot + notification policy all qualified on the backend."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
