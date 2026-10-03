from __future__ import annotations

import os
from time import perf_counter
from uuid import uuid4

from support.config import llm_enabled, read_config  # disables tracing before SDK import
from support.models import now
from support.store import Store

os.environ["OPENAI_AGENTS_DONT_LOG_MODEL_DATA"] = "1"
os.environ["OPENAI_AGENTS_DONT_LOG_TOOL_DATA"] = "1"

from agents import OpenAIChatCompletionsModel, set_tracing_disabled  # noqa: E402
from openai import APIStatusError, AsyncOpenAI  # noqa: E402

set_tracing_disabled(True)


def record_call(
    store: Store,
    ticket_id: str,
    agent: str,
    step: str,
    model: str,
    latency_ms: float,
    usage: dict | None,
    status: str,
    generation_id: str | None = None,
):
    config = read_config()
    incoming = usage.get("prompt_tokens") if usage else None
    outgoing = usage.get("completion_tokens") if usage else None
    cost = usage.get("cost") if usage else None
    source = "provider" if cost is not None else "unknown"
    if cost is None and model in config["prices"] and incoming is not None and outgoing is not None:
        prices = config["prices"][model]
        if prices.get("source") and prices.get("checked_at"):
            cost = (
                incoming * prices["input_per_million"] + outgoing * prices["output_per_million"]
            ) / 1_000_000
            source = "configured_price"
    details = usage.get("prompt_tokens_details") or {} if usage else {}
    cached = details.get("cached_tokens")
    with store.connection() as db:
        db.execute(
            "INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid4().hex,
                now(),
                ticket_id,
                agent,
                step,
                model,
                incoming,
                outgoing,
                cost,
                source,
                latency_ms,
                None if cached is None else int(cached > 0),
                status,
                generation_id,
            ),
        )


class LoggedModel(OpenAIChatCompletionsModel):
    def __init__(self, store: Store, ticket_id: str, agent: str, role: str):
        self.store, self.ticket_id, self.agent, self.role = store, ticket_id, agent, role
        config = read_config()
        self.model_id = config["models"][role]
        if not llm_enabled():
            raise RuntimeError("LLM calls are disabled")
        if not os.getenv("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is missing")
        ticket = store.get(ticket_id)
        if ticket.provenance == "real" and not ticket.pii_reviewed:
            raise RuntimeError("Review the redacted ticket before any model call")
        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
            max_retries=0,
            timeout=config["limits"]["model_timeout_seconds"],
        )
        super().__init__(model=self.model_id, openai_client=client)

    async def close(self):
        await self._client.close()

    async def get_response(self, *args, **kwargs):
        calls = self.store.rows("llm_calls")
        today = now()[:10]
        todays = [c for c in calls if c["timestamp"][:10] == today]
        if any(c["cost_usd"] is None for c in todays):
            raise RuntimeError(
                "Unknown previous model cost; reconcile accounting before continuing"
            )
        if sum(c["cost_usd"] for c in todays) >= read_config()["limits"]["max_daily_spend_usd"]:
            raise RuntimeError("Daily model budget reached")
        start = perf_counter()
        usage, status = None, "error"
        try:
            result = await super().get_response(*args, **kwargs)
            usage = result.raw_usage
            status = "ok"
            return result
        except APIStatusError as error:
            # Provider messages may echo submitted text. Keep only safe metadata.
            self.store.event(
                self.ticket_id,
                "model_http_error",
                {"agent": self.agent, "model": self.model_id, "http_status": error.status_code},
            )
            raise
        finally:
            record_call(
                self.store,
                self.ticket_id,
                self.agent,
                self.role,
                self.model_id,
                (perf_counter() - start) * 1000,
                usage,
                status,
            )
