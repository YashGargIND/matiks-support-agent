from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import getaddresses

from support.channels.base import ChannelAdapter
from support.channels.clickup import task_message
from support.models import RawMessage


class ClickUpSnapshot(ChannelAdapter):
    """Captured read-only API results. No polling/checkpoint or external mutation."""

    name = "clickup_snapshot"

    def __init__(self, tasks: list[dict]):
        self.tasks = tasks

    def fetch_new(self, since: str | None) -> list[RawMessage]:
        # Repeated snapshots are deduplicated by the original ClickUp task ID.
        return sorted(
            (task_message(t) for t in self.tasks), key=lambda m: (m.created_at, m.channel_ref)
        )

    def cursor(self, raw):
        return raw.created_at


class GmailSnapshot(ChannelAdapter):
    name = "gmail_snapshot"

    def __init__(self, messages: list[dict]):
        self.messages = messages

    def fetch_new(self, since: str | None) -> list[RawMessage]:
        items = []
        for message in self.messages:
            payload = message.get("payload", {})
            headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
            recipients = {
                address.lower()
                for _, address in getaddresses([headers.get("to", ""), headers.get("cc", "")])
            }
            if not recipients.intersection({"support@matiks.com", "support@matiks.in"}):
                continue
            sender = getaddresses([headers.get("from", "")])
            if len(sender) != 1 or not sender[0][1]:
                continue

            # Body text only; no attachments, transport headers, or HTML tracking resources.
            def plain(part):
                if part.get("mime_type") == "text/plain":
                    return [part.get("body", {}).get("content") or ""]
                return [text for child in part.get("parts", []) for text in plain(child)]

            body = "\n".join(plain(payload))
            # Quoted outbound campaigns are context, not new support requests.
            lines = []
            for line in body.splitlines():
                if re.match(r"^On .{0,250}wrote:\s*$", line) or re.match(
                    r"^-{2,}\s*(?:Original|Forwarded) message", line, re.I
                ):
                    break
                if not line.startswith(">"):
                    lines.append(line)
            items.append(
                RawMessage(
                    channel="email",
                    channel_ref="gmail:" + message["id"],
                    created_at=datetime.fromtimestamp(
                        int(message["internal_date"]) / 1000, UTC
                    ).isoformat(),
                    subject=headers.get("subject", ""),
                    body="\n".join(lines),
                    user_identifier=sender[0][1],
                    known_names=[sender[0][0]] if sender[0][0] else [],
                )
            )
        return sorted(items, key=lambda m: (m.created_at, m.channel_ref))

    def cursor(self, raw):
        return raw.created_at
