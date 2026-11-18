"""Agent and AI-gateway routes act only on the caller's own workspace.

Regression. ``/agents/deliberate``, ``/agents/tools/execute``,
``/agents/conversations*``, ``/agents/decision-room/{id}`` and ``/ai/infer``
took the workspace from an ``X-Workspace-Id`` header exactly as the caller
sent it, and the conversation routes returned any record by id. The records
live in one dictionary shared by the whole server, so a signed-in user of one
customer could:

* list another customer's deliberations by naming their workspace,
* read any deliberation by its id,
* store a deliberation in, and broadcast a realtime event to, another
  customer's workspace.

The workspace is now decided by the verified sign-in token.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import agent_runtime
from app.api.v1.router import api_router
from app.config import get_settings
from app.infrastructure.security import (
    DEV_FALLBACK_WORKSPACE,
    AuthContext,
    resolve_request_workspace,
)
from app.modules.identity.jwt_auth import issue_token
from app.modules.multi_agent.runtime.conversation_store import (
    ConversationRecord,
    ConversationStore,
)

JWT_SECRET = "agent-isolation-secret-0123456789abcdef0123456789"


@pytest.fixture
def strict_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A deployed environment: identity comes only from a verified token."""
    monkeypatch.setenv("CORTEX_ENV", "pilot")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("CORTEX_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CORTEX_LLM_API_KEY", "not-a-real-key-used-only-in-tests")
    monkeypatch.setenv("CORTEX_LLM_BASE_URL", "https://model-gateway.test/v1")
    monkeypatch.setenv("CORTEX_LLM_MODEL", "test-only-model")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def broadcasts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record realtime broadcasts instead of sending them."""
    sent: list[dict[str, Any]] = []

    async def _record(**kwargs: Any) -> int:
        sent.append(kwargs)
        return 0

    monkeypatch.setattr(agent_runtime._rt_gateway, "broadcast", _record)
    return sent


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> ConversationStore:
    """A fresh conversation store, so tests do not see each other's records."""
    fresh = ConversationStore()
    monkeypatch.setattr(agent_runtime, "_conv_store", fresh)
    return fresh


@pytest.fixture
def client(
    strict_env: None, store: ConversationStore, broadcasts: list[dict[str, Any]]
) -> TestClient:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return TestClient(app)


class Member:
    """A signed-in user of one customer workspace."""

    def __init__(self, role: str = "analyst") -> None:
        self.user_id = uuid4()
        self.workspace_id = str(uuid4())
        token, _expires = issue_token(
            user_id=self.user_id,
            workspace_id=self.workspace_id,
            role=role,
            email=f"{self.user_id.hex[:8]}@example.com",
        )
        self.headers = {"Authorization": f"Bearer {token}"}

    def naming(self, workspace_id: str) -> dict[str, str]:
        return {**self.headers, "X-Workspace-Id": workspace_id}


def _deliberate(client: TestClient, headers: dict[str, str], text: str = "Port strike") -> Any:
    return client.post(
        "/api/v1/agents/deliberate",
        json={"description": text, "task_type": "disruption_mitigation"},
        headers=headers,
    )


def _conversation_ids(client: TestClient, headers: dict[str, str]) -> list[str]:
    listed = client.get("/api/v1/agents/conversations", headers=headers)
    assert listed.status_code == 200, listed.text
    return [c["conversation_id"] for c in listed.json()["conversations"]]


def test_a_deliberation_is_filed_under_the_callers_own_workspace(
    client: TestClient, store: ConversationStore, broadcasts: list[dict[str, Any]]
) -> None:
    alpha = Member()

    done = _deliberate(client, alpha.headers)

    assert done.status_code == 200, done.text
    ids = _conversation_ids(client, alpha.headers)
    assert len(ids) == 1
    record = store.get(ids[0])
    assert record is not None
    # No header was sent: the workspace is the one in the sign-in token, not
    # the old shared "default_workspace" bucket every caller used to land in.
    assert record.workspace_id == alpha.workspace_id
    assert record.workspace_id != DEV_FALLBACK_WORKSPACE
    assert [b["workspace_id"] for b in broadcasts] == [alpha.workspace_id]


def test_another_customer_cannot_list_or_read_the_deliberation(client: TestClient) -> None:
    alpha, beta = Member(), Member()
    assert _deliberate(client, alpha.headers, "Alpha confidential shortage").status_code == 200
    (alpha_conversation,) = _conversation_ids(client, alpha.headers)

    # Beta's own list is empty: Alpha's record is not in a shared bucket.
    assert _conversation_ids(client, beta.headers) == []

    # Naming Alpha's workspace is refused outright.
    named = client.get("/api/v1/agents/conversations", headers=beta.naming(alpha.workspace_id))
    assert named.status_code == 403

    # Knowing the id is not enough either. 404, identical to an unknown id.
    for path in (
        f"/api/v1/agents/conversations/{alpha_conversation}",
        f"/api/v1/agents/decision-room/{alpha_conversation}",
    ):
        foreign = client.get(path, headers=beta.headers)
        unknown = client.get(
            path.replace(alpha_conversation, "conv_does_not_exist"), headers=beta.headers
        )
        assert foreign.status_code == 404, path
        assert foreign.json() == unknown.json()
        assert "confidential" not in foreign.text
        # ... and naming the owner's workspace does not turn it into a read.
        assert client.get(path, headers=beta.naming(alpha.workspace_id)).status_code == 403

    # The owner still reads it, with or without naming their own workspace.
    for headers in (alpha.headers, alpha.naming(alpha.workspace_id)):
        own = client.get(f"/api/v1/agents/conversations/{alpha_conversation}", headers=headers)
        assert own.status_code == 200
        assert own.json()["task_description"] == "Alpha confidential shortage"
        room = client.get(f"/api/v1/agents/decision-room/{alpha_conversation}", headers=headers)
        assert room.status_code == 200


def test_a_caller_cannot_write_or_broadcast_into_another_workspace(
    client: TestClient, store: ConversationStore, broadcasts: list[dict[str, Any]]
) -> None:
    alpha, beta = Member(), Member()

    planted = _deliberate(client, beta.naming(alpha.workspace_id), "planted by beta")

    assert planted.status_code == 403
    assert store.list_by_workspace(alpha.workspace_id) == []
    assert broadcasts == []
    assert _conversation_ids(client, alpha.headers) == []

    tool = client.post(
        "/api/v1/agents/tools/execute",
        json={"tool_name": "get_world_state", "input_data": {}},
        headers=beta.naming(alpha.workspace_id),
    )
    assert tool.status_code == 403

    own_tool = client.post(
        "/api/v1/agents/tools/execute",
        json={"tool_name": "get_world_state", "input_data": {}},
        headers=beta.headers,
    )
    assert own_tool.status_code == 200, own_tool.text
    assert beta.workspace_id in own_tool.text
    assert alpha.workspace_id not in own_tool.text


def test_agent_routes_require_sign_in(client: TestClient) -> None:
    for method, path in (
        ("get", "/api/v1/agents/conversations"),
        ("get", "/api/v1/agents/conversations/conv_x"),
        ("get", "/api/v1/agents/decision-room/conv_x"),
        ("get", "/api/v1/agents/registry"),
    ):
        assert getattr(client, method)(path).status_code == 401, path
    assert _deliberate(client, {}).status_code == 401
    # Identity headers alone are not an identity in a deployed environment.
    forged = {"X-User-Id": "attacker", "X-User-Workspaces": "any", "X-Workspace-Id": "any"}
    assert client.get("/api/v1/agents/conversations", headers=forged).status_code == 401


def test_ai_gateway_uses_the_callers_workspace_and_guards_the_shared_registry(
    client: TestClient,
) -> None:
    alpha, beta = Member(), Member()
    body = {"task": "SUPPLIER_SIMILARITY", "input_data": {}}

    assert client.post("/api/v1/ai/infer", json=body, headers=beta.headers).status_code == 200
    foreign = client.post("/api/v1/ai/infer", json=body, headers=beta.naming(alpha.workspace_id))
    assert foreign.status_code == 403

    # The model registry is shared by every customer on the server: changing
    # what it serves needs a platform administrator. An organization's own
    # admin is not enough: sign-up makes everybody the admin of their own
    # organization.
    for action in ("promote", "rollback"):
        path = f"/api/v1/ai/models/model_x/{action}"
        for role in ("viewer", "analyst", "operator", "admin"):
            refused = client.post(path, headers=Member(role=role).headers)
            assert refused.status_code == 403, f"{action} as {role}"
        # A platform administrator passes the gate (the unknown model id is then a 400).
        assert client.post(path, headers=Member(role="system_admin").headers).status_code == 400


def _auth(workspaces: list[str], anonymous: bool = False) -> AuthContext:
    return AuthContext(user_id="u1", workspace_ids=workspaces, is_anonymous=anonymous)


def test_resolve_request_workspace_rules() -> None:
    from fastapi import HTTPException

    member = _auth(["ws-own"])
    # Nothing named: the caller's own workspace.
    assert resolve_request_workspace(member) == "ws-own"
    assert resolve_request_workspace(member, "") == "ws-own"
    assert resolve_request_workspace(member, "   ") == "ws-own"
    # Their own, named explicitly.
    assert resolve_request_workspace(member, "ws-own") == "ws-own"
    assert resolve_request_workspace(member, " ws-own ") == "ws-own"
    # Somebody else's.
    with pytest.raises(HTTPException) as refused:
        resolve_request_workspace(member, "ws-other")
    assert refused.value.status_code == 403
    # The old shared bucket is not reachable by a signed-in member either.
    with pytest.raises(HTTPException):
        resolve_request_workspace(member, DEV_FALLBACK_WORKSPACE)
    # The anonymous development principal (local environments only) has no
    # workspace of its own and keeps the shared label.
    anonymous = _auth([], anonymous=True)
    assert resolve_request_workspace(anonymous) == DEV_FALLBACK_WORKSPACE
    assert resolve_request_workspace(anonymous, "ws-any") == "ws-any"


def _record(conversation_id: str, workspace_id: str) -> ConversationRecord:
    return ConversationRecord(
        conversation_id=conversation_id,
        tenant_id="default_tenant",
        organization_id="default_org",
        workspace_id=workspace_id,
        task_id=f"task_{conversation_id}",
        task_description="x",
        status="CONSENSUS",
        consensus_score=1.0,
        started_at=datetime(2026, 11, 18, tzinfo=UTC),
        completed_at=None,
    )


def test_store_reads_are_scoped_and_the_store_is_bounded() -> None:
    store = ConversationStore(max_records=3)
    store.save(_record("c1", "ws-a"))
    store.save(_record("c2", "ws-b"))

    assert store.get_in_workspace("c1", "ws-a") is not None
    assert store.get_in_workspace("c1", "ws-b") is None
    assert store.get_in_workspace("missing", "ws-a") is None
    assert [c.conversation_id for c in store.list_by_workspace("ws-b")] == ["c2"]

    # Oldest records are dropped once the limit is reached, so repeated calls
    # cannot grow the server's memory without bound.
    store.save(_record("c3", "ws-a"))
    store.save(_record("c4", "ws-a"))
    assert store.get("c1") is None
    assert {c for c in ("c2", "c3", "c4") if store.get(c)} == {"c2", "c3", "c4"}
    # Saving an existing record again refreshes it instead of evicting others.
    store.save(_record("c2", "ws-b"))
    store.save(_record("c5", "ws-a"))
    assert store.get("c2") is not None
    assert store.get("c3") is None
