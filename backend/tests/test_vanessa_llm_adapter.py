from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.modules.nexus_spine.p0_migration.llm_adapter import (
    LLMProviderError,
    OpenAICompatibleLLMAdapter,
    build_llm_adapter,
)
from app.modules.nexus_spine.p0_migration.vanessa_pipeline import (
    DeterministicLLMAdapter,
    Evidence,
    IntentType,
    StructuredIntent,
)


@pytest.mark.asyncio
async def test_model_adapter_classifies_only_declared_intents_and_extracts_explicit_entities():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                '{"intent":"risk_query","confidence":0.91,'
                                '"entities":{"supplier_id":"SUP-104","tool":"nexus.decision.execute"}}'
                                "\n```"
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleLLMAdapter(
        base_url="https://model-gateway.example/v1",
        api_key="test-secret",
        model="test-model",
        client=client,
    )
    try:
        intent = await adapter.classify_intent("Show risk for supplier SUP-104")
    finally:
        await client.aclose()

    assert intent.intent == IntentType.RISK_QUERY
    assert intent.confidence == pytest.approx(0.91)
    assert intent.entities["supplier_id"] == "SUP-104"
    assert intent.entities["tool"] == "nexus.decision.execute"


@pytest.mark.asyncio
async def test_model_cannot_invent_or_select_tools_outside_the_static_allowlist():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    adapter = OpenAICompatibleLLMAdapter(
        base_url="https://model-gateway.example/v1",
        api_key="test-secret",
        model="test-model",
        client=client,
    )
    try:
        intent = StructuredIntent(
            intent=IntentType.RISK_QUERY,
            entities={
                "supplier_id": "SUP-104",
                "tool": "nexus.decision.execute",
                "sql": "DROP TABLE nexus_decisions",
            },
            confidence=0.99,
            raw_text="show risks",
        )
        calls = await adapter.plan_tools(
            intent,
            ["nexus.risk.read", "nexus.decision.execute"],
        )
    finally:
        await client.aclose()

    assert len(calls) == 1
    assert calls[0].tool == "nexus.risk.read"
    assert calls[0].args == {"supplier_id": "SUP-104"}


@pytest.mark.asyncio
async def test_synthesis_receives_workspace_evidence_and_grounding_constraints():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured["payload"] = payload
        captured["authorization"] = request.headers.get("Authorization")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Supplier SUP-104 has two open risks [tool:nexus.risk.read]."}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleLLMAdapter(
        base_url="https://model-gateway.example/v1",
        api_key="test-secret",
        model="test-model",
        client=client,
    )
    try:
        output = await adapter.synthesize(
            StructuredIntent(
                intent=IntentType.RISK_QUERY,
                confidence=0.95,
                raw_text="What risks affect SUP-104?",
            ),
            [
                Evidence(
                    source="tool:nexus.risk.read",
                    tool="nexus.risk.read",
                    data={"count": 2, "risks": [{"entity_id": "SUP-104"}]},
                )
            ],
        )
    finally:
        await client.aclose()

    assert "two open risks" in output
    assert captured["authorization"] == "Bearer test-secret"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "only the supplied workspace-scoped tool evidence" in payload["messages"][0]["content"]
    assert "SUP-104" in payload["messages"][1]["content"]


@pytest.mark.asyncio
async def test_model_gateway_errors_do_not_leak_provider_response_body():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid secret=test-secret")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleLLMAdapter(
        base_url="https://model-gateway.example/v1",
        api_key="test-secret",
        model="test-model",
        client=client,
    )
    try:
        with pytest.raises(LLMProviderError, match="HTTP 401") as exc:
            await adapter.classify_intent("Show open risks")
    finally:
        await client.aclose()

    assert "test-secret" not in str(exc.value)
    assert "invalid secret" not in str(exc.value)


def test_deterministic_adapter_is_rejected_in_production():
    with pytest.raises(ValidationError, match="CORTEX_LLM_PROVIDER"):
        Settings(
            env="prod",
            jwt_secret="x" * 40,
            llm_provider="deterministic",
        )


def test_deterministic_adapter_remains_available_in_dev_and_test():
    adapter = build_llm_adapter(Settings(env="test", llm_provider="deterministic"))
    assert isinstance(adapter, DeterministicLLMAdapter)


def test_production_adapter_requires_secure_configured_endpoint_and_model():
    with pytest.raises(ValidationError, match="CORTEX_LLM_MODEL"):
        Settings(
            env="prod",
            jwt_secret="x" * 40,
            llm_provider="openai_compatible",
            llm_api_key="configured-secret",
        )

    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(
            env="prod",
            jwt_secret="x" * 40,
            llm_provider="openai_compatible",
            llm_api_key="configured-secret",
            llm_model="configured-model",
            llm_base_url="http://model-gateway.internal/v1",
        )

    settings = Settings(
        env="prod",
        jwt_secret="x" * 40,
        llm_provider="openai_compatible",
        llm_api_key="configured-secret",
        llm_model="configured-model",
        llm_base_url="https://model-gateway.example/v1",
    )
    assert settings.llm_provider == "openai_compatible"
