from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta

import httpx

from support.channels.base import ChannelAdapter
from support.config import read_config
from support.models import RawMessage


def task_message(task: dict) -> RawMessage:
    """Shared normalization for the GET adapter and connected-app snapshots."""
    list_id = str((task.get("list") or {}).get("id", os.getenv("CLICKUP_LIST_ID", "")))
    mapping = read_config().get("clickup_fields", {}).get(list_id, {})
    fields = {f["id"]: f.get("value") for f in task.get("custom_fields", [])}
    email = fields.get(mapping.get("email"))
    username = fields.get(mapping.get("username"))
    # The verified feedback form stores Suggestion as option orderindex 1.
    topic = fields.get(mapping.get("topic"))
    suggestion = str(topic) in {"1", "2cc005ec-16a0-44cb-9a1f-a6737e867e25"}
    original_name = task.get("name", "")
    if original_name.startswith("Suggestion:"):
        suggestion = True
    subject = "Feature suggestion" if suggestion else "Feedback report"
    creator = task.get("creator") or {}
    names = [n for n in (username, creator.get("username")) if isinstance(n, str)]
    return RawMessage(
        channel="clickup",
        channel_ref=str(task["id"]),
        created_at=datetime.fromtimestamp(int(task["date_created"]) / 1000, UTC).isoformat(),
        subject=subject
        + " · "
        + datetime.fromtimestamp(int(task["date_created"]) / 1000, UTC).strftime("%d %b %H:%M UTC"),
        body=task.get("description")
        or task.get("text_content")
        or task.get("markdown_description")
        or "",
        user_identifier=email
        if isinstance(email, str) and email
        else username
        if isinstance(username, str)
        else "",
        known_names=names,
        attachments_meta=[
            {"type": a.get("extension", "unknown")} for a in task.get("attachments", [])
        ],
    )


class ClickUpAdapter(ChannelAdapter):
    name = "clickup"

    def cursor(self, raw):
        return self._next_cursor

    def fetch_new(self, since: str | None) -> list[RawMessage]:
        token, list_id = os.getenv("CLICKUP_API_TOKEN"), os.getenv("CLICKUP_LIST_ID")
        if not token or not list_id:
            raise ValueError("ClickUp token/list ID are not configured")
        if not re.fullmatch(r"\d+", list_id):
            raise ValueError("ClickUp list ID must be numeric")
        if read_config()["limits"]["max_tickets_per_ingest"] != 100:
            raise ValueError("ClickUp pagination currently requires a 100-task batch cap")
        checkpoint = {"timestamp": None, "page": 0}
        if since:
            checkpoint = (
                json.loads(since) if since.startswith("{") else {"timestamp": since, "page": 0}
            )
        params = {
            "include_closed": "false",
            "order_by": "created",
            "reverse": "true",
            "page": checkpoint["page"],
        }
        if since:
            params["date_created_gt"] = (
                int(datetime.fromisoformat(checkpoint["timestamp"]).timestamp() * 1000) - 1
            )
        else:
            lookback = read_config().get("clickup_initial_lookback_days", 7)
            if not isinstance(lookback, int) or not 1 <= lookback <= 90:
                raise ValueError("Initial ClickUp lookback must be 1–90 days")
            params["date_created_gt"] = (
                int((datetime.now(UTC) - timedelta(days=lookback)).timestamp() * 1000) - 1
            )
        with httpx.Client(timeout=20) as client:
            response = client.get(
                f"https://api.clickup.com/api/v2/list/{list_id}/task",
                headers={"Authorization": token},
                params=params,
            )
            response.raise_for_status()
            tasks = response.json()["tasks"]
        timestamps = [int(t["date_created"]) for t in tasks]
        if timestamps != sorted(timestamps):
            raise ValueError("ClickUp response must be ordered oldest first; checkpoint withheld")
        messages = [
            task_message(task)
            for task in tasks[: read_config()["limits"]["max_tickets_per_ingest"]]
        ]
        if messages:
            stamp = messages[-1].created_at
            same_boundary = checkpoint["timestamp"] == stamp and all(
                m.created_at == stamp for m in messages
            )
            self._next_cursor = json.dumps(
                {
                    "timestamp": stamp,
                    "page": checkpoint["page"] + 1 if same_boundary and len(messages) == 100 else 0,
                }
            )
        return messages
