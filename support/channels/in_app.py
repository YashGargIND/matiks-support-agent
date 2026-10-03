"""Read pending communication reports; never resolve reports or moderate users."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from support.channels.base import ChannelAdapter
from support.models import RawMessage

COMMUNICATION_REASONS = [
    "inappropriate_language",
    "harassment_bullying",
    "spam_scam",
    "hate_speech",
    "sexual_content",
    "off_topic",
]


class InAppReportAdapter(ChannelAdapter):
    name = "in_app"

    def __init__(self, reader_factory=None):
        from support.data import MongoReader

        self.reader_factory = reader_factory or MongoReader

    def fetch_new(self, since: str | None) -> list[RawMessage]:
        if os.getenv("MONGO_SCHEMA_VERIFIED", "false").lower() != "true":
            raise LookupError("Verify the in-app report mapping first")
        from bson import ObjectId

        query = {
            "reasonKeys": {"$in": COMMUNICATION_REASONS},
            "status": {"$in": ["PENDING", "UNDER_REVIEW"]},
        }
        if since:
            stamp, identifier = json.loads(since)
            parsed = datetime.fromisoformat(stamp)
            query["$or"] = [
                {"reportedAt": {"$gt": parsed}},
                {"reportedAt": parsed, "_id": {"$gt": ObjectId(identifier)}},
            ]
        else:
            query["reportedAt"] = {"$gte": datetime.now(UTC) - timedelta(days=7)}
        reader = self.reader_factory()
        try:
            projection = {field: 1 for field in reader.mapping["inapp_reports"]["projection"]}
            rows = list(
                reader.collection("inapp_reports")
                .find(query, projection)
                .sort([("reportedAt", 1), ("_id", 1)])
                .max_time_ms(3000)
                .limit(100)
            )
        finally:
            reader.close()
        messages = []
        for row in rows:
            if not isinstance(row.get("reportedAt"), datetime) or row["reportedAt"].tzinfo is None:
                raise ValueError("Invalid report timestamp")
            if not isinstance(row.get("reporterId"), ObjectId) or not isinstance(
                row.get("reportedUserId"), ObjectId
            ):
                raise ValueError("Invalid report identity mapping")
            messages.append(
                RawMessage(
                    channel=self.name,
                    channel_ref=str(row["_id"]),
                    created_at=row["reportedAt"].isoformat(),
                    subject="DM safety / harassment report",
                    body="Reported reasons: "
                    + ", ".join(row.get("reasonKeys", []))
                    + "\n"
                    + (row.get("additionalComments") or ""),
                    user_identifier=str(row["reporterId"]),
                    provenance="real",
                )
            )
        return messages

    def cursor(self, raw: RawMessage):
        return json.dumps([raw.created_at, raw.channel_ref])
