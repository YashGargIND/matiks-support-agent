from __future__ import annotations

import json

import httpx
import pytest
from agents import Agent, Runner, function_tool
from agents.run import RunConfig
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from openai import AsyncOpenAI

from support.agents_flow import settings
from support.llm import LoggedModel


async def test_sdk_executes_a_typed_tool_without_network():
    calls = []

    @function_tool
    def facts_lookup(topic: str) -> str:
        """Look up a verified local policy."""
        calls.append(topic)
        return "No verified policy exists; escalate."

    model = ScriptedModel(
        [
            ModelStep(
                output=[function_call("facts_lookup", {"topic": "streak"}, call_id="test-call")]
            ),
            ModelStep(output=[assistant_message("Human review required.")]),
        ]
    )
    agent = Agent(name="Tool smoke", model=model, tools=[facts_lookup])
    result = await Runner.run(
        agent, "Check the streak policy", run_config=RunConfig(tracing_disabled=True)
    )
    assert calls == ["streak"]
    assert result.final_output == "Human review required."
    assert len(model.calls) == 2
    model.assert_complete()


async def test_openrouter_usage_survives_sdk_and_is_logged(store, ticket, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-never-sent")
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        assert request.url.host == "openrouter.ai"
        return httpx.Response(
            200,
            json={
                "id": "gen-local-mock",
                "object": "chat.completion",
                "created": 1,
                "model": "openai/gpt-4.1-mini",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Review required."},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "total_tokens": 110,
                    "cost": 0.00125,
                    "prompt_tokens_details": {"cached_tokens": 25},
                },
            },
        )

    model = LoggedModel(store, ticket.id, "test", "triage")
    model._client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        result = await Runner.run(
            Agent(name="Accounting smoke", model=model, model_settings=settings()),
            "Safe synthetic test",
            run_config=RunConfig(tracing_disabled=True),
        )
        assert result.final_output == "Review required."
        row = store.rows("llm_calls")[0]
        assert row["input_tokens"] == 100 and row["output_tokens"] == 10
        assert row["cost_usd"] == 0.00125 and row["cost_source"] == "provider"
        assert row["cache_hit"] == 1
        assert observed[0]["provider"]["require_parameters"] is True
        assert observed[0]["provider"]["data_collection"] == "deny"
        # OpenRouter's verified GPT-4.1 endpoints do not advertise this parameter.
        # With require_parameters enabled, including it rejects every endpoint.
        assert "parallel_tool_calls" not in observed[0]
    finally:
        await model._client.close()


def test_real_ticket_cannot_call_model_before_pii_review(store, ticket, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    ticket.provenance = "real"
    store.save(ticket)
    with pytest.raises(RuntimeError, match="Review"):
        LoggedModel(store, ticket.id, "test", "triage")


async def test_provider_error_does_not_leak_payload_or_invent_cost(store, ticket, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-never-sent")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            404, json={"error": {"code": 404, "message": "Echoed secret: sensitive@example.com"}}
        )

    model = LoggedModel(store, ticket.id, "test", "triage")
    await model.close()
    model._client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    agent = Agent(name="Error accounting", model=model, model_settings=settings())
    try:
        from openai import NotFoundError

        with pytest.raises(NotFoundError):
            await Runner.run(agent, "Synthetic input", run_config=RunConfig(tracing_disabled=True))
        row = store.rows("llm_calls")[0]
        assert row["status"] == "error" and row["cost_usd"] is None
        event = next(e for e in store.rows("events") if e["kind"] == "model_http_error")
        assert json.loads(event["data"])["http_status"] == 404
        assert "sensitive@example.com" not in json.dumps(store.rows("events"))
        with pytest.raises(RuntimeError, match="Unknown previous model cost"):
            await Runner.run(agent, "Retry", run_config=RunConfig(tracing_disabled=True))
        assert len(requests) == 1
    finally:
        await model.close()
