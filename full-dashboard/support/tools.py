from __future__ import annotations

import json
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from support.config import read_config
from support.contracts import CONTRACTS
from support.models import Evidence, now
from support.store import Store

TOPICS = {
    "resolve_user",
    "get_user_cohort",
    "get_streak_history",
    "get_purchases",
    "get_merch_orders",
    "get_merch_delivery_stats",
    "get_gameplay_stats",
    "search_gcp_logs",
    "get_chat_history",
    "code_search",
    "get_module_owner",
}


class DataProvider(Protocol):
    def fetch(self, topic: str, user_id: str | None) -> tuple[dict, str]: ...


class UnconfiguredProvider:
    def fetch(self, topic: str, user_id: str | None) -> tuple[dict, str]:
        raise LookupError(f"{topic} has no verified read-only source mapping")


class ToolHub:
    def __init__(
        self, store: Store, ticket_id: str, run_id: str, provider: DataProvider | None = None
    ):
        self.store, self.ticket_id, self.run_id = store, ticket_id, run_id
        self.provider = provider or UnconfiguredProvider()
        self.calls = 0
        self.cache: dict[str, Evidence] = {}

    def fetch(self, topic: str, user_id: str | None = None) -> Evidence:
        if topic not in TOPICS:
            raise ValueError("Unknown read-only tool")
        key = json.dumps([topic, user_id])
        if key in self.cache:
            return self.cache[key]
        if self.calls >= read_config()["limits"]["max_tool_calls"]:
            raise RuntimeError("Tool call cap reached")
        self.calls += 1
        start = perf_counter()
        try:
            data, source = self.provider.fetch(topic, user_id)
            if topic in CONTRACTS:
                data = CONTRACTS[topic].model_validate(data).model_dump(mode="json")
            if len(json.dumps(data, default=str)) > 20000:
                raise ValueError("Tool result exceeds 20 KB limit")
            available = True
        except Exception as error:
            # Do not store exception messages, which can contain credentials/PII.
            data, source, available = (
                {"unavailable": True, "error_type": type(error).__name__},
                f"tool:{topic}",
                False,
            )
        record = Evidence(
            id=f"ev:{uuid4().hex}",
            ticket_id=self.ticket_id,
            run_id=self.run_id,
            tool=topic,
            data=self.store.redact_evidence(self.ticket_id, data),
            source=source,
            available=available,
        )
        self.store.evidence(record)
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    uuid4().hex,
                    now(),
                    self.ticket_id,
                    self.run_id,
                    topic,
                    json.dumps({"user_id_present": user_id is not None}),
                    (perf_counter() - start) * 1000,
                    len(record.model_dump_json()),
                    int(available),
                ),
            )
        self.cache[key] = record
        return record
