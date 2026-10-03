from __future__ import annotations

import asyncio
import json
import os
from typing import Literal
from uuid import uuid4

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunConfig,
    Runner,
    function_tool,
    output_guardrail,
)
from openai import APIStatusError
from pydantic import BaseModel, ConfigDict

from support.agents_flow import injection_guard, settings
from support.config import ROOT, require_dry_run
from support.llm import LoggedModel
from support.models import RawMessage, now
from support.privacy import normalize
from support.store import Store


class SmokeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_mode: Literal["dry_run"]
    dispatch_available: Literal[False]


async def smoke(store: Store):
    require_dry_run()
    ticket, mapping = normalize(
        RawMessage(
            channel="sdk_smoke",
            channel_ref=uuid4().hex,
            created_at=now(),
            subject="Synthetic SDK/OpenRouter smoke",
            body="No real user data. Local SDK capability test only.",
            provenance="synthetic",
        )
    )
    ticket.status, ticket.closed_at = "closed", now()
    store.ingest(ticket, mapping)
    model = LoggedModel(store, ticket.id, "SDK smoke", "triage")
    calls = []

    @function_tool
    def read_local_mode() -> str:
        """Read the local demo mode without contacting any external system."""
        calls.append("read_local_mode")
        return json.dumps({"mode": "dry_run", "dispatch_available": False})

    @output_guardrail
    async def check(ctx, agent, output: SmokeOutput):
        return GuardrailFunctionOutput(
            output_info={"tool_called": bool(calls)}, tripwire_triggered=not bool(calls)
        )

    agent = Agent(
        name="SDK smoke",
        model=model,
        instructions="Call read_local_mode before answering. Report its exact mode and dispatch availability in the output schema. This is a synthetic test with no user data.",
        tools=[read_local_mode],
        output_type=SmokeOutput,
        model_settings=settings(),
        input_guardrails=[injection_guard],
        output_guardrails=[check],
    )
    try:
        outcome = await asyncio.wait_for(
            Runner.run(
                agent,
                "Read the local demo mode using the tool and report the result.",
                max_turns=3,
                run_config=RunConfig(tracing_disabled=True, trace_include_sensitive_data=False),
            ),
            timeout=135,
        )
        records = store.rows("llm_calls", ticket.id)
        accounting = all(
            c["cost_usd"] is not None
            and c["input_tokens"] is not None
            and c["output_tokens"] is not None
            for c in records
        )
        result = {
            "status": "passed" if calls and accounting else "accounting_incomplete",
            "synthetic_ticket_id": ticket.id,
            "tool_calls": len(calls),
            "model_calls": len(records),
            "cost_usd": sum(c["cost_usd"] for c in records) if accounting else None,
            "output": outcome.final_output.model_dump(),
            "trace_export": False,
            "real_ticket_text_sent": False,
        }
        store.event(ticket.id, "live_sdk_smoke", result)
        return result
    except Exception as error:
        result = {
            "status": "failed",
            "synthetic_ticket_id": ticket.id,
            "error_type": type(error).__name__,
            "http_status": error.status_code if isinstance(error, APIStatusError) else None,
            "tool_calls": len(calls),
            "model_calls": len(store.rows("llm_calls", ticket.id)),
            "real_ticket_text_sent": False,
        }
        store.event(ticket.id, "live_sdk_smoke", result)
        return result
    finally:
        await model.close()


def main():
    # Child-process override only; never changes the configured live-processing flag.
    os.environ["LLM_ENABLED"] = "true"
    result = asyncio.run(smoke(Store()))
    path = ROOT / "data/live-sdk-smoke.json"
    path.write_text(json.dumps(result, indent=2))
    os.chmod(path, 0o600)
    print(json.dumps(result))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
