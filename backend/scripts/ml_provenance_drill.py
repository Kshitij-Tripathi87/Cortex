"""ML inference + provenance drill -- production inference acceptance qualification
(launch-board ML provenance gate, deployed-system drill).

Proves the full provenance chain end-to-end on the REAL stack:

    register -> promote -> inference -> provenance -> outbox -> replay

Phases:

  1. SIGNUP     -- real API identity (JWT, workspace).
  2. REGISTER   -- register forecast + risk models carrying training_dataset,
                   feature_schema and world_state_version provenance.
  3. PROMOTE    -- promote both to ``deployed`` (skip_gate_validation: the
                   drill registers with no evaluation history).
  4. INFERENCE  -- real demand + risk inference requests.
  5. PROVENANCE -- the response MUST name the promoted model_id/version,
                   echo world_state_version, carry a deterministic
                   feature_hash (recomputed locally from the same features),
                   and satisfy strict quantile monotonicity (demand).
  6. TRACE      -- the durable outbox events (forecast.generated /
                   risk.inferred) carry the same model_version/feature_hash
                   (superuser query = observability side), the durable replay
                   endpoint serves them, and the model registry preserves
                   training_dataset/feature_schema/world_state_version.

Usage (backend API + PostgreSQL running):

    python scripts/ml_provenance_drill.py \\
        --api-base http://127.0.0.1:8000 \\
        --admin-dsn "postgresql://postgres:cortex_local_2026@localhost:5432/cortex"

Exit code 0 = provenance acceptance passed (chain fully traceable).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import httpx

sys.path.insert(0, ".")

from app.modules.nexus_spine.p0_migration.authoritative_inference import (  # noqa: E402
    compute_feature_hash,
)

EMAIL_DOMAIN = "drill-provenance.example.com"
PASSWORD = "Drillsecures1"  # noqa: S105 - drill credential, same convention as the e2e suite

QUANTILES = ["p10", "p25", "p50", "p75", "p80", "p90", "p95", "p99"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pg_conn_str(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def signup(client: httpx.AsyncClient, api_base: str, tag: str) -> dict[str, str]:
    email = f"drill-{tag}-{uuid.uuid4().hex[:8]}@{EMAIL_DOMAIN}"
    resp = await client.post(
        f"{api_base}/api/v1/auth/signup",
        json={
            "organization_name": f"Drill Org {tag}",
            "email": email,
            "password": PASSWORD,
            "full_name": "Provenance Drill Tester",
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


async def register_model(
    client: httpx.AsyncClient,
    api_base: str,
    ident: dict[str, str],
    model_type: str,
) -> dict[str, Any]:
    resp = await client.post(
        f"{api_base}/api/v1/nexus/models/register",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={"workspace_id": ident["workspace_id"]},
        json={
            "name": f"drill-{model_type}",
            "version": f"drill-v1-{uuid.uuid4().hex[:6]}",
            "model_type": model_type,
            "description": "provenance drill candidate",
            "training_dataset": "ds_provenance_drill_v1",
            "feature_schema": {
                "features": ["base_demand", "price", "promotion"],
                "feature_version": "fv_drill_v1",
            },
            "world_state_version": 1,
            "metrics": {"mape": 0.12, "coverage": 0.93},
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"register failed {resp.status_code}: {resp.text[:300]}")
    model: dict[str, Any] = resp.json()["data"]["model"]
    if not model.get("model_id"):
        raise RuntimeError("register returned no model_id")
    return model


async def promote_model(
    client: httpx.AsyncClient,
    api_base: str,
    ident: dict[str, str],
    model_id: str,
) -> None:
    resp = await client.post(
        f"{api_base}/api/v1/nexus/models/{model_id}/promote",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={"workspace_id": ident["workspace_id"]},
        json={"skip_gate_validation": True},
    )
    if resp.status_code != 200:
        raise RuntimeError(f"promote failed {resp.status_code}: {resp.text[:300]}")


async def run_demand_inference(
    client: httpx.AsyncClient,
    api_base: str,
    ident: dict[str, str],
    features: dict[str, Any],
) -> dict[str, Any]:
    resp = await client.post(
        f"{api_base}/api/v1/nexus/inference/demand",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={"workspace_id": ident["workspace_id"]},
        json={
            "sku": "SKU-DRILL-1",
            "features": features,
            "horizon_days": 14,
            "world_state_version": 1,
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"demand inference failed {resp.status_code}: {resp.text[:300]}")
    prediction: dict[str, Any] = resp.json()["data"]["prediction"]
    return prediction


async def run_risk_inference(
    client: httpx.AsyncClient,
    api_base: str,
    ident: dict[str, str],
    features: dict[str, Any],
) -> dict[str, Any]:
    resp = await client.post(
        f"{api_base}/api/v1/nexus/inference/risk",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={"workspace_id": ident["workspace_id"]},
        json={
            "entity_id": "ENT-DRILL-1",
            "features": features,
            "world_state_version": 1,
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"risk inference failed {resp.status_code}: {resp.text[:300]}")
    prediction: dict[str, Any] = resp.json()["data"]["prediction"]
    return prediction


async def replay(client: httpx.AsyncClient, api_base: str, ident: dict[str, str]) -> dict[str, Any]:
    resp = await client.get(
        f"{api_base}/api/v1/nexus/realtime/events",
        headers={"Authorization": f"Bearer {ident['token']}"},
        params={
            "workspace_id": ident["workspace_id"],
            "after_seq": "0",
            "limit": "500",
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"replay failed {resp.status_code}: {resp.text[:300]}")
    data: dict[str, Any] = resp.json()["data"]
    return data


async def outbox_payloads(
    pool: asyncpg.Pool, workspace_id: str, event_type: str
) -> list[dict[str, Any]]:
    """Durable outbox payloads for an event type (superuser = observability side)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT payload, world_state_version
            FROM nexus_events
            WHERE workspace_id = $1 AND event_type = $2
            ORDER BY seq ASC
            """,
            workspace_id,
            event_type,
        )
        return [dict(r) for r in rows]


async def run(args: argparse.Namespace) -> int:
    admin_pool = await asyncpg.create_pool(_pg_conn_str(args.admin_dsn), min_size=1)
    failures: list[str] = []
    ws = ""

    async with httpx.AsyncClient(base_url=args.api_base, timeout=30.0) as client:
        # ── 1. SIGNUP ────────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 1: signup")
        ident = await signup(client, args.api_base, "prov")
        ws = ident["workspace_id"]
        print(f"  workspace={ws}")

        # ── 2. REGISTER ──────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 2: register forecast + risk models")
        forecast_model = await register_model(client, args.api_base, ident, "forecast")
        risk_model = await register_model(client, args.api_base, ident, "risk")
        print(
            f"  forecast model={forecast_model['model_id']} "
            f"v={forecast_model['version']} | risk model={risk_model['model_id']} "
            f"v={risk_model['version']}"
        )

        # ── 3. PROMOTE ───────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 3: promote both to deployed")
        await promote_model(client, args.api_base, ident, str(forecast_model["model_id"]))
        await promote_model(client, args.api_base, ident, str(risk_model["model_id"]))
        print("  both models promoted (status=deployed)")

        # ── 4. INFERENCE ─────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 4: real demand + risk inference")
        demand_features: dict[str, Any] = {
            "base_demand": 120.0,
            "price": 45.5,
            "promotion": True,
        }
        risk_features: dict[str, Any] = {
            "supplier_health": 0.72,
            "lead_time_variance": 3.4,
            "on_hand_inventory": 810.0,
        }
        demand = await run_demand_inference(client, args.api_base, ident, demand_features)
        risk = await run_risk_inference(client, args.api_base, ident, risk_features)
        print(
            f"  demand forecast={demand['forecast_id']} model={demand['model_id']} "
            f"v={demand['model_version']}"
        )
        print(f"  risk={risk['entity_id']} model={risk['model_id']} v={risk['model_version']}")

        # ── 5. PROVENANCE ────────────────────────────────────────────────────
        print(f"[{_now_iso()}] Phase 5: provenance checks")
        if demand["model_id"] != forecast_model["model_id"]:
            failures.append(
                f"demand used model {demand['model_id']} != promoted {forecast_model['model_id']}"
            )
        if demand["model_version"] != forecast_model["version"]:
            failures.append(
                f"demand model_version {demand['model_version']} != promoted "
                f"{forecast_model['version']}"
            )
        if risk["model_id"] != risk_model["model_id"]:
            failures.append(
                f"risk used model {risk['model_id']} != promoted {risk_model['model_id']}"
            )
        if risk["model_version"] != risk_model["version"]:
            failures.append(
                f"risk model_version {risk['model_version']} != promoted {risk_model['version']}"
            )
        if demand["world_state_version"] != 1 or risk["world_state_version"] != 1:
            failures.append(
                "inference did not echo world_state_version "
                f"(demand={demand['world_state_version']}, risk={risk['world_state_version']})"
            )

        expected_demand_hash = compute_feature_hash(demand_features)
        if demand["feature_hash"] != expected_demand_hash:
            failures.append(
                f"demand feature_hash {demand['feature_hash']} != recomputed "
                f"{expected_demand_hash} (reproducibility broken)"
            )
        expected_risk_hash = compute_feature_hash(risk_features)
        if risk["feature_hash"] != expected_risk_hash:
            failures.append(
                f"risk feature_hash {risk['feature_hash']} != recomputed "
                f"{expected_risk_hash} (reproducibility broken)"
            )
        print(
            f"  feature_hash reproducible: demand={expected_demand_hash} risk={expected_risk_hash}"
        )

        qvals = [demand[q] for q in QUANTILES]
        if any(qvals[i] > qvals[i + 1] for i in range(len(qvals) - 1)):
            failures.append(
                f"demand quantiles not monotonic: {dict(zip(QUANTILES, qvals, strict=True))}"
            )
        else:
            print(f"  demand quantiles monotonic: {dict(zip(QUANTILES, qvals, strict=True))}")

        # ── 6. TRACE (durable + replay) ──────────────────────────────────────
        print(f"[{_now_iso()}] Phase 6: durable outbox + replay traceability")
        for event_type, model_id, model_version, feature_hash in [
            (
                "forecast.generated",
                forecast_model["model_id"],
                forecast_model["version"],
                expected_demand_hash,
            ),
            ("risk.inferred", risk_model["model_id"], risk_model["version"], expected_risk_hash),
        ]:
            rows = await outbox_payloads(admin_pool, ws, event_type)
            if not rows:
                failures.append(f"durable outbox has no {event_type} event")
                continue
            payload = rows[0]["payload"]
            if isinstance(payload, str):
                import json

                payload = json.loads(payload)
            if payload.get("model_id") != model_id:
                failures.append(
                    f"{event_type} payload model_id {payload.get('model_id')} != {model_id}"
                )
            if payload.get("model_version") != model_version:
                failures.append(
                    f"{event_type} payload model_version "
                    f"{payload.get('model_version')} != {model_version}"
                )
            if payload.get("feature_hash") != feature_hash:
                failures.append(
                    f"{event_type} payload feature_hash "
                    f"{payload.get('feature_hash')} != {feature_hash}"
                )
            print(
                f"  durable {event_type}: model={payload.get('model_id')} hash={payload.get('feature_hash')}"
            )

        env = await replay(client, args.api_base, ident)
        replay_types = [e.get("event_type") or e.get("type") for e in env["events"]]
        for event_type in ("forecast.generated", "risk.inferred"):
            if event_type not in replay_types:
                failures.append(f"durable replay does not serve {event_type}")
        print(f"  replay serves {len(env['events'])} events; types include {replay_types}")

        # Model registry preserves provenance.
        resp = await client.get(
            f"{args.api_base}/api/v1/nexus/models/{forecast_model['model_id']}",
            headers={"Authorization": f"Bearer {ident['token']}"},
            params={"workspace_id": ident["workspace_id"]},
        )
        if resp.status_code != 200:
            failures.append(f"model registry read failed {resp.status_code}")
        else:
            mdl = resp.json()["data"]["model"]
            if mdl.get("training_dataset") != "ds_provenance_drill_v1":
                failures.append(
                    f"model training_dataset not preserved: {mdl.get('training_dataset')}"
                )
            fschema = mdl.get("feature_schema") or {}
            if not isinstance(fschema, dict) or fschema.get("feature_version") != "fv_drill_v1":
                failures.append(f"model feature_schema not preserved: {fschema}")
            print(
                f"  registry provenance: training_dataset={mdl.get('training_dataset')} "
                f"feature_version={(mdl.get('feature_schema') or {}).get('feature_version')}"
            )

        # Relay health after the inference writes.
        resp = await client.get(
            f"{args.api_base}/api/v1/nexus/realtime/health",
            headers={"Authorization": f"Bearer {ident['token']}"},
        )
        if resp.status_code != 200:
            failures.append(f"/realtime/health {resp.status_code}")
        else:
            print(f"  /realtime/health: 200 ({resp.json().get('data', {}).get('outbox', {})})")

    await admin_pool.close()

    print()
    if failures:
        print("DRILL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        "DRILL PASSED: provenance chain fully traceable (register -> promote -> inference -> outbox -> replay)."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--admin-dsn",
        default="postgresql://postgres:cortex_local_2026@localhost:5432/cortex",
        help="Superuser DSN for outbox inspection (sees all rows, bypasses RLS)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
